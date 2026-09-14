"""Podgląd ekranu amplitunera — dziewięć linii przeglądarki źródeł sieciowych.

Amplituner wystawia zawartość ekranu komendą `NSE`: dziewięć linii po sto
znaków. Linia 0 to nagłówek, 1–7 to pozycje menu, 8 to stopka ze
stronicowaniem. Przed tekstem każdej linii poza nagłówkiem stoi jeden bajt
ikony i kursora.

Czego ten podgląd NIE pokazuje: pełnego menu konfiguracji na ekranie
telewizora. `NSE` dotyczy przeglądarki źródeł sieciowych — Media Server,
radia internetowego, USB. Przy innym źródle bywa pusty.

## Dlaczego port 5000, a nie 23

Amplituner przyjmuje **jedno** połączenie telnet na porcie 23 naraz i to
połączenie trzyma już reszta aplikacji. Port 5000 mówi tym samym protokołem
ASCII (sprawdzone: `PW?` → `PWON`, `NSFRN ?` → nazwa urządzenia), ale jest
osobnym gniazdem — można go otworzyć równolegle, nie odbierając nikomu
sterowania. To było odkrycie przy skanowaniu portów: obok 23 i 8080
amplituner nasłuchuje też na 1024 (AirPlay), 1256 (Audyssey), 5000, 5001
i 6666.
"""

from __future__ import annotations

import socket
import threading
import time

PORT = 5000
LINES = 9
LINE_WIDTH = 100

# Bajt przed tekstem linii. Wartości ustalone z obserwacji — pełnej tabeli
# ikon nie znam, więc rozpoznajemy tylko to, co widzieliśmy na urządzeniu.
MARKERS = {
    0x04: "pusta",
    0x0C: "wpis",
    0x24: "stopka",
}


def parse(raw: bytes) -> list[dict]:
    """Rozbiera surową odpowiedź na linie ekranu."""
    screen: dict[int, dict] = {}
    for chunk in raw.split(b"\r"):
        if not chunk.startswith(b"NSE") or len(chunk) < 5:
            continue
        try:
            index = int(chunk[3:4])
        except ValueError:
            continue
        body = chunk[4:]
        # Nagłówek (linia 0) idzie bez bajtu ikony — reszta z nim.
        if index == 0:
            marker, text = None, body
        else:
            marker, text = body[0], body[1:]
        screen[index] = {
            "index": index,
            "marker": marker,
            "kind": MARKERS.get(marker, "?" if marker is not None else "naglowek"),
            "text": text.decode("utf-8", "replace").rstrip("\x00 ").rstrip(),
        }
    return [screen.get(i, {"index": i, "marker": None, "kind": "brak", "text": ""})
            for i in range(LINES)]


class Display:
    """Trzyma połączenie i odświeża obraz ekranu na żądanie."""

    def __init__(self, host: str = "", timeout: float = 3.0) -> None:
        self.host = host
        self.timeout = timeout
        self.lines: list[dict] = []
        self.updated = 0.0
        self.error = ""
        self._lock = threading.Lock()

    def refresh(self, host: str = "") -> dict:
        """Pyta o ekran i zapamiętuje wynik.

        Osobne połączenie na każde odpytanie. Trwałe gniazdo nic by tu nie
        dało — amplituner i tak odsyła całe dziewięć linii naraz, a otwarte
        połączenie potrafi zamilknąć po kilkudziesięciu sekundach bezczynności.
        """
        host = host or self.host
        if not host:
            return self.snapshot("nie znam adresu amplitunera")

        sock = socket.socket()
        sock.settimeout(self.timeout)
        raw = b""
        try:
            sock.connect((host, PORT))
            sock.sendall(b"NSE\r")
            deadline = time.time() + self.timeout
            while time.time() < deadline:
                try:
                    chunk = sock.recv(8192)
                except socket.timeout:
                    break
                if not chunk:
                    break
                raw += chunk
                # Linia 8 to stopka — po niej nic więcej nie przyjdzie.
                if b"NSE8" in raw:
                    break
        except OSError as e:
            return self.snapshot(f"port {PORT} na {host}: {e}")
        finally:
            sock.close()

        lines = parse(raw)
        with self._lock:
            self.host = host
            self.lines = lines
            self.updated = time.time()
            self.error = "" if any(l["text"] for l in lines) else "ekran pusty"
        return self.snapshot()

    def snapshot(self, error: str | None = None) -> dict:
        with self._lock:
            return {
                "host": self.host,
                "lines": list(self.lines),
                "title": self.lines[0]["text"] if self.lines else "",
                "footer": self.lines[8]["text"] if len(self.lines) > 8 else "",
                "updated": round(self.updated, 1),
                "age_s": round(time.time() - self.updated, 1) if self.updated else None,
                "error": error if error is not None else self.error,
            }

    def as_text(self) -> str:
        """Ekran jako zwykły tekst — do konsoli i do logu."""
        return "\n".join(l["text"] for l in self.lines)
