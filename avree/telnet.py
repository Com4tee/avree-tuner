"""Klient protokołu sterowania Denon/Marantz (TCP 23).

Uwaga: telnetlib zniknęło ze standardowej biblioteki w Pythonie 3.13,
więc gadamy gołym socketem. To i tak czystsze - Denon nie negocjuje
żadnych opcji telnetu, to zwykły strumień ASCII z CR jako terminatorem.

Charakterystyka protokołu, która determinuje ten kod:
  * komenda = ASCII zakończone CR (\r), bez LF
  * zapytanie = komenda + '?' , np. 'MV?'
  * amplituner sam z siebie wypycha zmiany stanu (nacisnięcie pilota,
    zmiana źródła) - odbiór musi być ciągły, nie request/response
  * jedno zapytanie może wygenerować wiele linii odpowiedzi
  * urządzenie dopuszcza JEDNO połączenie telnet naraz
  * między komendami trzeba odczekać, inaczej AVR gubi znaki
"""

from __future__ import annotations

import socket
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable

DEFAULT_PORT = 23
INTER_COMMAND_DELAY = 0.12   # Denon dokumentuje min. 200 ms; 120 ms działa stabilnie
CONNECT_TIMEOUT = 5.0


class DenonTelnetError(RuntimeError):
    pass


class DenonTelnet:
    """Trwałe połączenie z AVR. Wątek czytający zbiera wszystko, co przyjdzie."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, history: int = 2000) -> None:
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._rx = threading.Thread(target=self._reader, daemon=True)
        self._buffer = ""
        self._lines: deque[tuple[float, str]] = deque(maxlen=history)
        self._lock = threading.Lock()
        self._listeners: list[Callable[[str], None]] = []
        self._running = False
        self._last_tx = 0.0

    # ---- cykl życia -------------------------------------------------

    def connect(self) -> None:
        try:
            self._sock = socket.create_connection((self.host, self.port), CONNECT_TIMEOUT)
        except OSError as e:
            raise DenonTelnetError(
                f"nie mogę się połączyć z {self.host}:{self.port} - {e}. "
                "Sprawdź, czy amplituner jest włączony i czy nie trzyma go już "
                "inna aplikacja (AVR przyjmuje tylko JEDNO połączenie telnet)."
            ) from e
        self._sock.settimeout(0.25)
        self._running = True
        self._rx.start()

    def close(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
            self._sock = None

    def __enter__(self) -> "DenonTelnet":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- odbiór -----------------------------------------------------

    def _reader(self) -> None:
        while self._running and self._sock:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            self._buffer += chunk.decode("ascii", "replace")
            # AVR terminuje CR; część firmware'ów dokłada LF
            while "\r" in self._buffer:
                line, self._buffer = self._buffer.split("\r", 1)
                line = line.strip("\n\r ")
                if not line:
                    continue
                with self._lock:
                    self._lines.append((time.time(), line))
                for cb in list(self._listeners):
                    try:
                        cb(line)
                    except Exception:
                        pass

    def on_event(self, callback: Callable[[str], None]) -> None:
        """Rejestruje callback wołany dla każdej linii z amplitunera."""
        self._listeners.append(callback)

    # ---- nadawanie --------------------------------------------------

    def send(self, command: str) -> None:
        if not self._sock:
            raise DenonTelnetError("brak połączenia")
        gap = time.time() - self._last_tx
        if gap < INTER_COMMAND_DELAY:
            time.sleep(INTER_COMMAND_DELAY - gap)
        self._sock.sendall((command + "\r").encode("ascii"))
        self._last_tx = time.time()

    def ask(self, command: str, settle: float = 0.35) -> list[str]:
        """Wysyła zapytanie i zwraca linie, które przyszły w oknie `settle`.

        Świadomie nie dopasowujemy odpowiedzi do zapytania: AVR miesza
        odpowiedzi ze zdarzeniami asynchronicznymi, a jedno zapytanie
        (np. SSSOD ?) sypie kilkunastoma liniami.
        """
        mark = len(self._lines)
        self.send(command)
        time.sleep(settle)
        with self._lock:
            return [line for _, line in list(self._lines)[mark:]]

    def query_many(self, commands: Iterable[str], settle: float = 0.35) -> dict[str, list[str]]:
        return {cmd: self.ask(cmd, settle) for cmd in commands}

    # ---- podgląd ----------------------------------------------------

    def drain(self) -> list[str]:
        with self._lock:
            out = [line for _, line in self._lines]
            self._lines.clear()
        return out
