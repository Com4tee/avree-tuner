"""Protokół Audyssey MultEQ Editor — binarny kanał TCP na porcie 1256.

To jest DRUGI kanał sterowania, niezależny od telnetu na porcie 23. Telnet
daje nastawy (odległości, poziomy, podziały). Ten daje dane kalibracji:
odpowiedzi impulsowe z pomiaru i wgrywanie własnych współczynników filtrów.

Sprostowanie do wcześniejszych wniosków w tym projekcie: twierdziłem, że
z wzmacniacza nie da się wyciągnąć danych pomiarowych i że komunikacja jest
jednokierunkowa. To było **błędne**. Kanał jest dwukierunkowy i odpowiada
JSON-em. Sprawdzone na AVR-X3300W.

## Format ramki

    54 | 00 13 | 00 00 | "GET_AVRINF" | 00 00 00 | <ładunek> | 6c
    'T'  dł.    rezerwa   komenda 10 B   dł. ład.    JSON/bin   suma

* bajt 0     — marker 0x54 ('T')
* bajty 1–2  — długość CAŁEJ ramki, big-endian
* bajty 3–4  — zera
* bajty 5–14 — nazwa komendy, 10 bajtów, dopełniona spacjami
* bajty 15–17— długość ładunku, 3 bajty big-endian
* ładunek    — JSON albo dane binarne
* ostatni    — suma wszystkich poprzednich bajtów modulo 256

Odpowiedź ma ten sam format, ale marker 0x52 ('R').

Dwie pułapki, na które sam wpadłem przy odgadywaniu formatu:

1. Wzmacniacz ODBIJA nazwę komendy, jeśli ją zna, a wpisuje "ERROR", jeśli
   nie zna — NIEZALEŻNIE od tego, czy suma kontrolna się zgadza. To świetna
   wyrocznia do mapowania zestawu komend, ale łatwo ją pomylić z sukcesem:
   przy złej sumie i tak dostaje się `{"Comm":"NACK"}`.

2. Pole komendy ma 10 bajtów, więc dłuższe nazwy są OBCINANE. `GET_RESPON2`
   i `GET_RESPONS` „działają" tylko dlatego, że obcinają się do `GET_RESPON`.

## Skąd wzięty

Format ramki i pełna lista komend pochodzą z publicznego repozytorium
`srinivas486/audyssey-rew-tuner` (plik COMMAND_INVENTORY.md), opisującego
działanie otwartych narzędzi A1 Evo / OCA. Płatna aplikacja MultEQ Editor
nie była dekompilowana. Odpowiedzi poniżej są zweryfikowane na sprzęcie.
"""

from __future__ import annotations

import json
import socket
import struct
from typing import Any

PORT = 1256
MARKER_REQUEST = 0x54             # 'T'
MARKER_RESPONSE = 0x52            # 'R'
CMD_FIELD = 10                    # bajtów na nazwę komendy

# --------------------------------------------------------------------
# Zestaw komend
# --------------------------------------------------------------------
# ODCZYT — bezpieczne, nie zmieniają niczego w urządzeniu.
READ_ONLY = {
    "GET_AVRINF": "typ korekcji, czasy, opóźnienie systemowe",
    "GET_AVRSTS": "przypisanie kanałów, mikrofon, końcówki mocy",
}

# SESJA KALIBRACJI — wprowadzają wzmacniacz w tryb pomiarowy.
# UWAGA: wejście w ten tryb to początek NOWEJ kalibracji. Istniejące
# krzywe Audyssey mogą zostać nadpisane. Nie wołać bez świadomej zgody.
SESSION = {
    "ENTER_AUDY": "wejście w tryb kalibracji",
    "EXIT_AUDMD": "wyjście z trybu kalibracji",
    "SET_POSNUM": "numer pozycji mikrofonu",
    "START_CHNL": "wyzwolenie sweepu dla kanału, zwraca odległość i poziom",
    "GET_RESPON": "pobranie odpowiedzi impulsowej (float32, wiele pakietów)",
}

# ZAPIS WSPÓŁCZYNNIKÓW — wgranie własnej korekcji.
WRITE_COEFS = {
    "INIT_COEFS": "start wgrywania współczynników",
    "SET_COEFDT": "współczynniki filtru, 126 liczb float32 na pakiet",
    "FINZ_COEFS": "zamknięcie wgrywania",
    "SET_SETDAT": "nastawy: odległości, poziomy, podziały",
    "SET_AUDYFINFLG": "flaga zakończenia kalibracji",
}

ALL_COMMANDS = {**READ_ONLY, **SESSION, **WRITE_COEFS}


class AudysseyError(RuntimeError):
    pass


# --------------------------------------------------------------------
# Kodowanie ramek
# --------------------------------------------------------------------

def build(command: str, payload: bytes = b"") -> bytes:
    """Buduje ramkę żądania wraz z sumą kontrolną."""
    name = command.encode("ascii")
    if len(name) > CMD_FIELD:
        raise AudysseyError(
            f"nazwa {command!r} ma {len(name)} bajtów, a pole ma {CMD_FIELD} — "
            "zostałaby obcięta i trafiła w inną komendę")
    body = bytearray()
    body += bytes([MARKER_REQUEST])
    body += b"\x00\x00"                       # miejsce na długość
    body += b"\x00\x00"
    body += name.ljust(CMD_FIELD)
    body += struct.pack(">I", len(payload))[1:]
    body += payload
    total = len(body) + 1                     # +1 na sumę kontrolną
    body[1:3] = struct.pack(">H", total)
    return bytes(body) + bytes([sum(body) & 0xFF])


def parse(frame: bytes) -> dict:
    """Rozbiera ramkę odpowiedzi."""
    if len(frame) < 18:
        raise AudysseyError(f"ramka za krótka: {len(frame)} bajtów")
    length = struct.unpack(">H", frame[1:3])[0]
    command = frame[5:5 + CMD_FIELD].decode("ascii", "replace").strip()
    payload_len = int.from_bytes(frame[15:18], "big")
    payload = frame[18:18 + payload_len]
    return {
        "marker": frame[0],
        "length": length,
        "command": command,
        "payload_len": payload_len,
        "payload": payload,
        "complete": len(frame) >= length,
    }


def as_json(payload: bytes) -> Any:
    try:
        return json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


# --------------------------------------------------------------------
# Rozmowa
# --------------------------------------------------------------------

def request(host: str, command: str, payload: bytes = b"",
            timeout: float = 5.0) -> dict:
    """Wysyła jedną komendę i zwraca rozebraną odpowiedź.

    Każda komenda idzie osobnym połączeniem — tak samo robią otwarte
    narzędzia i tak samo znosi to wzmacniacz. Próba zrównoleglenia kończy
    się brakiem odpowiedzi: sprawdzone, 452 zapytania na 544 przepadły
    przy dwunastu wątkach naraz.
    """
    if command not in ALL_COMMANDS:
        raise AudysseyError(f"nieznana komenda: {command}")

    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((host, PORT))
        sock.sendall(build(command, payload))
        data = b""
        while True:
            chunk = sock.recv(16384)
            if not chunk:
                break
            data += chunk
            if len(data) >= 3 and len(data) >= struct.unpack(">H", data[1:3])[0]:
                break
    except OSError as e:
        raise AudysseyError(f"port {PORT} na {host}: {e}") from e
    finally:
        sock.close()

    out = parse(data)
    out["json"] = as_json(out["payload"])
    if out["json"] == {"Comm": "NACK"}:
        out["nack"] = True
    return out


def info(host: str, timeout: float = 5.0) -> dict:
    """Co wzmacniacz mówi o swojej korekcji. Czysty odczyt.

    Zwrócone na AVR-X3300W:
        EQType       MultEQXT32
        SWLvlMatch   true   (dopasowanie poziomu subwooferów, Sub EQ HT)
        SysDelay     280
        ADC          2.115
        LFC / Auro   false
    """
    r = request(host, "GET_AVRINF", timeout=timeout)
    return r.get("json") or {}


def status(host: str, timeout: float = 5.0) -> dict:
    """Przypisanie kanałów i stan wejścia mikrofonowego. Czysty odczyt.

    Na AVR-X3300W `ChSetup` wymienia SWMIX1 i SWMIX2 — oba subwoofery
    widziane osobno, co zgadza się z `SSSPCSWF 2SP` po telnecie.
    """
    r = request(host, "GET_AVRSTS", timeout=timeout)
    return r.get("json") or {}


def channels(host: str, timeout: float = 5.0) -> list[str]:
    """Lista kanałów, które wzmacniacz uważa za obecne."""
    setup = status(host, timeout).get("ChSetup") or []
    out = []
    for entry in setup:
        out.extend(entry.keys())
    return out


def probe_command(host: str, command: str, timeout: float = 2.0) -> bool:
    """Czy wzmacniacz zna taką komendę.

    Korzysta z tego, że nazwa znanej komendy wraca w odpowiedzi, a nieznanej
    zamienia się w "ERROR". Działa nawet przy odmowie — i tak dostajemy NACK.
    """
    name = command[:CMD_FIELD]
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((host, PORT))
        raw = bytearray(build("GET_AVRINF"))
        raw[5:5 + CMD_FIELD] = name.encode("ascii").ljust(CMD_FIELD)
        raw[-1] = sum(raw[:-1]) & 0xFF
        sock.sendall(bytes(raw))
        data = sock.recv(4096)
    except OSError:
        return False
    finally:
        sock.close()
    if len(data) < 15:
        return False
    return data[5:15].decode("ascii", "replace").strip() != "ERROR"
