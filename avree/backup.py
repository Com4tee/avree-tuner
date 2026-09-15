"""Zrzut wszystkich odczytywalnych nastaw amplitunera.

Po co: nastawy, które Audyssey wypracowało podczas kalibracji — odległości,
poziomy kanałów, podziały, konfiguracja głośników — da się odczytać i
wprowadzić z ręki. Same krzywe korekcyjne nie, ale one są najmniej warte
z tego zestawu i najłatwiejsze do odtworzenia własnym pomiarem.

Najcenniejsza pozycja w tym zrzucie to **różnica odległości SW i SW2**.
To jest wyrównanie czasowe dwóch subwooferów wypracowane przez Sub EQ HT
i jedyna rzecz, której nie da się odtworzyć bez mikrofonu Denona wpiętego
we wzmacniacz.

Zrzut jest zapisywany jako JSON i jako gotowa lista komend do wklejenia —
przywrócenie nie wymaga tego modułu ani nawet tej aplikacji, wystarczy
telnet i kopiuj-wklej.
"""

from __future__ import annotations

import json
import socket
import time
from datetime import datetime
from pathlib import Path

# Port 5000 zamiast 23: przyjmuje ten sam protokół, ale jest osobnym
# gniazdem, więc zrzut można zrobić bez odbierania sterowania aplikacji.
PORT = 5000

# Grupy zapytań. Kolejność ma znaczenie przy odtwarzaniu: najpierw
# konfiguracja głośników, potem dopiero ich odległości i poziomy —
# wzmacniacz odrzuca nastawy dla kanałów, których nie ma.
QUERIES = [
    ("konfiguracja głośników", "SSSPC ?"),
    ("częstotliwości podziału", "SSCFR ?"),
    ("tryb subwoofera", "SSSWM ?"),
    ("filtr LFE", "SSLFL ?"),
    ("ODLEGŁOŚCI", "SSSDE ?"),
    ("odległości Dolby-enabled", "SSDSS ?"),
    ("poziomy kanałów (setup)", "SSLEV ?"),
    ("poziomy kanałów (bieżące)", "CV?"),
    ("poziom subwooferów", "PSSWL ?"),
    ("tryby Audyssey", "PSMULTEQ: ?"),
    ("dynamic eq", "PSDYNEQ ?"),
    ("dynamic volume", "PSDYNVOL ?"),
    ("reference level offset", "PSREFLEV ?"),
    ("poziom LFE", "PSLFE ?"),
    ("przypisanie HDMI", "SSHDM ?"),
    ("przypisanie analogowe", "SSANA ?"),
    ("przypisanie cyfrowe", "SSDIN ?"),
    ("przypisanie wideo", "SSVDO ?"),
    ("przypisanie component", "SSCMP ?"),
    ("konwersja wideo", "SSCNV ?"),
    ("poziomy źródeł", "SSSLD ?"),
    ("auto lip sync", "SSALS ?"),
    ("menu ekranowe", "SSOSD ?"),
    ("końcówki mocy", "SSPAA ?"),
    ("nazwa urządzenia", "NSFRN ?"),
    ("wersja firmware", "SSINFFRM ?"),
]

# Które linie odpowiedzi da się wprost wysłać z powrotem jako nastawę.
# Reszta jest tylko do wglądu — np. SSSDESTP to krok nastawy, nie wartość.
RESTORABLE_PREFIXES = ("SSSDE", "SSDSS", "SSLEV", "CV", "SSSPC", "SSCFR",
                       "SSSWM", "SSLFL", "SSHDM", "SSANA", "SSDIN", "SSVDO",
                       "SSCMP", "SSCNV", "SSSLD", "SSALS", "SSOSD")
SKIP_LINES = ("SSSDESTP", "CVEND", "MVMAX", "DCAUTO", "SSCFR IDV")


def _ask(host: str, command: str, settle: float = 1.6) -> list[str]:
    sock = socket.socket()
    sock.settimeout(5.0)
    try:
        sock.connect((host, PORT))
        time.sleep(0.15)
        try:
            sock.recv(8192)                  # cokolwiek wisi w buforze
        except OSError:
            pass
        sock.sendall(command.encode() + b"\r")
        time.sleep(settle)
        out = b""
        sock.settimeout(1.2)
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                out += chunk
        except OSError:
            pass
    except OSError as e:
        return [f"!BŁĄD {e}"]
    finally:
        sock.close()
    return [l.decode("utf-8", "replace").strip()
            for l in out.split(b"\r") if l.strip()]


def _ask_via_app(app_url: str, command: str, settle: float = 1.8) -> list[str]:
    """Odczyt przez działającą aplikację, czyli przez port 23.

    Potrzebne, bo port 5000 bywa niedostępny — po cyklu zasilania przestaje
    odpowiadać, choć połączenie się zestawia. Port 23 działa wtedy dalej,
    tylko trzyma go aplikacja, więc idziemy przez jej API.
    """
    import urllib.request

    def _log(n: int = 400) -> list[dict]:
        r = urllib.request.urlopen(f"{app_url}/api/log?n={n}", timeout=10)
        return json.loads(r.read())["lines"]

    before = len(_log())
    body = json.dumps({"action": "raw", "value": command}).encode()
    urllib.request.urlopen(urllib.request.Request(
        f"{app_url}/api/command", data=body,
        headers={"Content-Type": "application/json"}), timeout=10).read()
    time.sleep(settle)
    lines = _log()
    fresh = lines[before:] if len(lines) > before else lines
    return [e["line"] for e in fresh if e.get("dir") == "rx"]


def dump(host: str, app_url: str = "http://127.0.0.1:8731",
         ask=None) -> dict:
    """Odczytuje wszystko, co się da. Wyłącznie zapytania.

    Najpierw próbuje portu 5000 (nie odbiera nikomu sterowania). Jeśli ten
    milczy, przechodzi na port 23 przez aplikację. Bez tego zrzut potrafi
    wyjść pusty i wyglądać, jakby wzmacniacz nic nie miał do powiedzenia.
    """
    data: dict[str, list[str]] = {}

    # Najtańsza droga: gotowa funkcja odczytu podana przez wywołującego.
    # Serwer podaje tu własne `avr.ask`, dzięki czemu zrzut idzie po istniejącym
    # połączeniu telnet, bez nowych gniazd i bez odpytywania samego siebie
    # po HTTP. Bez tego zrzut z interfejsu trwał ponad dwie minuty: najpierw
    # 26 nieudanych prób na porcie 5000, potem 26 przelotów przez własne API.
    if ask is not None:
        for label, query in QUERIES:
            try:
                data[label] = list(ask(query))
            except Exception as e:                   # noqa: BLE001
                data[label] = [f"!BŁĄD {e}"]
        return {"host": host,
                "when": datetime.now().isoformat(timespec="seconds"),
                "via": "połączenie aplikacji",
                "groups": data}

    direct_ok = False
    for label, query in QUERIES:
        lines = _ask(host, query)
        data[label] = lines
        if lines and not lines[0].startswith("!"):
            direct_ok = True

    if not direct_ok and app_url:
        for label, query in QUERIES:
            try:
                data[label] = _ask_via_app(app_url, query)
            except Exception as e:                   # noqa: BLE001
                data[label] = [f"!BŁĄD {e}"]

    return {
        "host": host,
        "when": datetime.now().isoformat(timespec="seconds"),
        "via": "port 5000" if direct_ok else "port 23 (aplikacja)",
        "groups": data,
    }


def restore_commands(snapshot: dict) -> list[str]:
    """Zamienia zrzut na listę komend przywracających nastawy."""
    out: list[str] = []
    for lines in snapshot.get("groups", {}).values():
        for line in lines:
            if line.startswith("!") or any(line.startswith(s) for s in SKIP_LINES):
                continue
            if line.startswith(RESTORABLE_PREFIXES):
                out.append(line)
    # Bez duplikatów, z zachowaniem kolejności.
    seen, unique = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def highlights(snapshot: dict) -> dict:
    """To, co naprawdę boli stracić."""
    dist = {}
    for line in snapshot.get("groups", {}).get("ODLEGŁOŚCI", []):
        if line.startswith("SSSDE") and not line.startswith("SSSDESTP"):
            key, _, val = line[5:].partition(" ")
            if val.rstrip("M").isdigit():
                dist[key] = int(val.rstrip("M"))
    levels = {}
    for line in snapshot.get("groups", {}).get("poziomy kanałów (setup)", []):
        if line.startswith("SSLEV"):
            key, _, val = line[5:].partition(" ")
            if val.isdigit():
                levels[key] = int(val)
    sw, sw2 = dist.get("SW"), dist.get("SW2")
    return {
        "distances_cm": dist,
        "levels_raw": levels,
        "levels_db": {k: round((v - 50) / 2.0, 1) for k, v in levels.items()},
        "sub_offset_cm": (sw2 - sw) if (sw is not None and sw2 is not None) else None,
        "sub_offset_ms": (round((sw2 - sw) / 100.0 / 343.0 * 1000, 3)
                          if (sw is not None and sw2 is not None) else None),
    }


def save(host: str, folder: Path, ask=None) -> dict:
    """Zrzut na dysk: JSON plus gotowa lista komend do wklejenia."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    snap = dump(host, ask=ask)
    snap["highlights"] = highlights(snap)
    commands = restore_commands(snap)

    json_path = folder / f"nastawy-{stamp}.json"
    json_path.write_text(json.dumps(snap, ensure_ascii=False, indent=1),
                         encoding="utf-8")

    txt_path = folder / f"przywroc-{stamp}.txt"
    head = [
        "# Przywrócenie nastaw AVR-X3300W",
        f"# Zrzut z {snap['when']}, urządzenie {host}",
        "#",
        "# Wyślij te linie po telnecie (port 23 albo 5000), po jednej,",
        "# z odstępem ~150 ms. Nie wymaga tej aplikacji.",
        "#",
        "# NAJWAŻNIEJSZE: różnica odległości subwooferów to wyrównanie",
        "# czasowe z Sub EQ HT — jedyna rzecz, której nie odtworzysz bez",
        "# mikrofonu Denona wpiętego we wzmacniacz.",
        "#",
    ]
    h = snap["highlights"]
    if h["sub_offset_cm"] is not None:
        head.append(f"#   SW  = {h['distances_cm'].get('SW')} cm")
        head.append(f"#   SW2 = {h['distances_cm'].get('SW2')} cm")
        head.append(f"#   różnica = {h['sub_offset_cm']} cm = {h['sub_offset_ms']} ms")
        head.append("#")
    txt_path.write_text("\n".join(head + commands) + "\n", encoding="utf-8")

    return {"json": str(json_path), "commands": str(txt_path),
            "count": len(commands), "highlights": h}
