"""Splot w torze PC — pętla systemowa, filtr, wyjście do amplitunera.

Bierzemy to, co Windows właśnie odtwarza (pętla WASAPI na urządzeniu
wyjściowym), przepuszczamy przez kaskadę biquadów z `dsp.py` i wypuszczamy
dalej. Dzięki temu korekcja działa na WSZYSTKIM, co gra na komputerze —
foobar, przeglądarka, gra — bez wtyczek do poszczególnych programów.

Dwie drogi wyjścia, bo mamy dwie różne sytuacje:

* `http`  — nieskończony WAV pod adresem HTTP, który amplituner odtwarza
  przez UPnP. Jedyna droga, gdy PC nie ma z amplitunerem połączenia
  kablowego. Opóźnienie idzie w sekundy, bo renderer buforuje — do muzyki
  w porządku, do filmu nie, bo obraz ucieknie dźwiękowi.

* `device` — przetworzony dźwięk wraca na INNE urządzenie wyjściowe
  (np. wyjście optyczne albo HDMI idące do amplitunera). Opóźnienie rzędu
  kilkudziesięciu milisekund. Wymaga dwóch osobnych urządzeń: Windows gra
  do pierwszego, my nasłuchujemy tego pierwszego i gramy do drugiego.
  Wskazanie tego samego urządzenia z obu stron dałoby sprzężenie, więc
  jest to jawnie blokowane.

Dlaczego `soundcard`, a nie `sounddevice` używane przy pomiarze:
sounddevice 0.5.6 nie wystawia pętli WASAPI. Jego `WasapiSettings` ma
tylko `exclusive`, `auto_convert` i `explicit_sample_format` — nie ma
`loopback`, a otwarcie wyjścia jako wejścia kończy się błędem
"Invalid number of channels". Sprawdzone na tym komputerze. Tor pomiarowy
zostaje przy sounddevice, bo tam potrzebujemy jednoczesnego grania
i nagrywania na wspólnym zegarze, co sounddevice robi przez `playrec`.

Uwaga o poziomie: pętla WASAPI słyszy dźwięk PO suwaku głośności Windows.
Ściszony system to cichszy strumień i gorszy stosunek do szumu kwantyzacji
po konwersji na 16 bitów. Głośność systemowa powinna stać na maksimum,
a regulować należy amplitunerem.
"""

from __future__ import annotations

import ctypes
import queue
import struct
import sys
import threading
import time

import numpy as np

from .dsp import MultiChannelFilter

try:
    import soundcard as sc
except Exception as _e:                              # noqa: BLE001
    sc = None
    _IMPORT_ERROR = str(_e)
else:
    _IMPORT_ERROR = ""


class StreamError(RuntimeError):
    pass


# --------------------------------------------------------------------
# COM na wątek
# --------------------------------------------------------------------
# soundcard rozmawia z WASAPI przez COM, a COM jest inicjowany OSOBNO dla
# każdego wątku. Biblioteka robi to raz, przy imporcie, czyli na wątku
# głównym — a nasz serwer HTTP obsługuje każde żądanie na nowym wątku.
# Bez tego pierwsze wejście w zakładkę kończy się błędem 0x800401f0
# (CO_E_NOTINITIALIZED). Sprawdzone: dokładnie tak się to objawiło.

_COINIT_MULTITHREADED = 0x0
_RPC_E_CHANGED_MODE = 0x80010106      # wątek jest już w innym apartamencie
_com_local = threading.local()


def _com_init() -> None:
    """Wprowadza bieżący wątek do COM. Bezpieczne do wielokrotnego wołania."""
    if sys.platform != "win32" or getattr(_com_local, "ready", False):
        return
    hr = ctypes.windll.ole32.CoInitializeEx(None, _COINIT_MULTITHREADED)
    # S_OK (0) i S_FALSE (1) znaczą "gotowe". RPC_E_CHANGED_MODE oznacza,
    # że wątek siedzi już w apartamencie jednowątkowym — COM działa, tylko
    # nie my go otworzyliśmy, więc też nie zamykamy.
    if hr & 0xFFFFFFFF not in (0, 1, _RPC_E_CHANGED_MODE):
        raise StreamError(f"nie udało się zainicjować COM: 0x{hr & 0xFFFFFFFF:08x}")
    _com_local.ready = True


def _require() -> None:
    if sc is None:
        raise StreamError(
            f"biblioteka soundcard niedostępna ({_IMPORT_ERROR}). "
            "Zainstaluj: pip install soundcard")
    _com_init()


BLOCK = 1024              # próbek na blok — 21,3 ms przy 48 kHz
QUEUE_BLOCKS = 24         # ile bloków trzymamy dla odbiorcy (~0,5 s)


def devices() -> dict:
    """Urządzenia wyjściowe — każde może być i źródłem pętli, i celem."""
    _require()
    try:
        speakers = sc.all_speakers()
        default = sc.default_speaker()
    except Exception as e:                           # noqa: BLE001
        return {"available": False, "error": str(e), "speakers": []}
    return {
        "available": True,
        "speakers": [{"name": s.name, "channels": s.channels,
                      "default": s.name == default.name} for s in speakers],
        "default": default.name,
    }


def wav_header(fs: int, channels: int, bits: int = 16) -> bytes:
    """Nagłówek WAV o nieznanej długości.

    Rozmiary wpisujemy jako 0xFFFFFFFF, bo strumień nie ma końca. Odtwarzacze
    traktują to jako "graj, aż połączenie padnie" — inaczej musielibyśmy
    z góry znać długość, której nie ma.
    """
    byte_rate = fs * channels * bits // 8
    block_align = channels * bits // 8
    return (b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, fs,
                                    byte_rate, block_align, bits)
            + b"data" + struct.pack("<I", 0xFFFFFFFF))


class LoopbackStream:
    """Przechwytywanie dźwięku systemowego, filtracja, rozdział do odbiorców."""

    def __init__(self) -> None:
        self.fs = 48000
        self.channels = 2
        self.filter = MultiChannelFilter(self.fs, self.channels)
        self.running = False
        self.source = ""
        self.sink = ""                # "" = tylko HTTP
        self.error = ""
        self.blocks = 0
        self.dropped = 0
        self.started_at = 0.0
        self.load = 0.0               # ułamek budżetu czasu rzeczywistego
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._clients: list[queue.Queue] = []
        self._lock = threading.Lock()

    # ---- konfiguracja --------------------------------------------------

    def configure(self, design, mapping: dict[int, str] | None = None) -> None:
        """Podpina projekt equalizera. Można w trakcie grania."""
        self.filter.configure(design, mapping or {0: "FL", 1: "FR"})

    def set_enabled(self, on: bool) -> None:
        self.filter.enabled = bool(on)
        if not on:
            self.filter.reset()

    # ---- odbiorcy ------------------------------------------------------

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=QUEUE_BLOCKS)
        with self._lock:
            self._clients.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def _publish(self, payload: bytes) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                # Odbiorca nie nadąża. Wyrzucamy NAJSTARSZY blok, nie nowy:
                # inaczej kolejka zamarza na starym materiale i opóźnienie
                # rośnie w nieskończoność zamiast się stabilizować.
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except (queue.Empty, queue.Full):
                    pass
                self.dropped += 1

    # ---- praca ---------------------------------------------------------

    def start(self, source: str = "", sink: str = "", fs: int = 48000) -> dict:
        _require()
        if self.running:
            return {"ok": False, "error": "strumień już działa"}

        speakers = {s.name: s for s in sc.all_speakers()}
        if not source:
            source = sc.default_speaker().name
        if source not in speakers:
            raise StreamError(f"nie ma takiego urządzenia: {source}")
        if sink:
            if sink not in speakers:
                raise StreamError(f"nie ma takiego urządzenia: {sink}")
            if sink == source:
                raise StreamError(
                    "źródło i cel to to samo urządzenie — powstałoby "
                    "sprzężenie. Wskaż inne wyjście albo zostaw tylko HTTP.")

        self.fs = fs
        self.source, self.sink = source, sink
        self.error = ""
        self.blocks = self.dropped = 0
        self.load = 0.0
        self.filter = MultiChannelFilter(fs, self.channels)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.started_at = time.time()

        # Chwila na otwarcie strumienia — żeby błąd urządzenia wrócił
        # od razu w odpowiedzi, a nie dopiero przy następnym odpytaniu.
        time.sleep(0.4)
        if self.error:
            return {"ok": False, "error": self.error}
        return {"ok": True, "status": self.status()}

    def stop(self) -> dict:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
        self._thread = None
        self.running = False
        with self._lock:
            for q in self._clients:
                try:
                    q.put_nowait(b"")        # sygnał końca dla odbiorców
                except queue.Full:
                    pass
        return {"ok": True}

    def _run(self) -> None:
        budget = BLOCK / self.fs
        try:
            _com_init()                              # to jest nowy wątek
            mic = sc.get_microphone(self.source, include_loopback=True)
            player = (sc.get_speaker(self.sink).player(
                samplerate=self.fs, channels=self.channels, blocksize=BLOCK)
                if self.sink else None)

            with mic.recorder(samplerate=self.fs, channels=self.channels,
                              blocksize=BLOCK) as rec:
                if player is not None:
                    player.__enter__()
                self.running = True
                try:
                    while not self._stop.is_set():
                        block = rec.record(numframes=BLOCK)
                        t0 = time.perf_counter()

                        out = self.filter.process(block)
                        np.clip(out, -1.0, 1.0, out=out)

                        if player is not None:
                            player.play(out.astype(np.float32))
                        if self._clients:
                            self._publish(
                                (out * 32767.0).astype("<i2").tobytes())

                        dt = time.perf_counter() - t0
                        self.load = 0.9 * self.load + 0.1 * (dt / budget)
                        self.blocks += 1
                finally:
                    if player is not None:
                        player.__exit__(None, None, None)
        except Exception as e:                       # noqa: BLE001
            self.error = str(e)
        finally:
            self.running = False

    # ---- podgląd -------------------------------------------------------

    def status(self) -> dict:
        return {
            "running": self.running,
            "source": self.source,
            "sink": self.sink,
            "samplerate": self.fs,
            "channels": self.channels,
            "eq_enabled": self.filter.enabled,
            "blocks": self.blocks,
            "dropped": self.dropped,
            "seconds": round(self.blocks * BLOCK / self.fs, 1) if self.blocks else 0.0,
            "clients": len(self._clients),
            "load_percent": round(self.load * 100, 1),
            "input_peak_db": _db(self.filter.bypass_peak),
            "output_peak_db": _db(self.filter.output_peak),
            "headroom_db": self.filter.headroom_db(),
            "error": self.error,
        }


def _db(value: float) -> float:
    return round(float(20 * np.log10(max(value, 1e-9))), 1)
