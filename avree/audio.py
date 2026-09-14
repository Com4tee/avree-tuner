"""Wejście i wyjście dźwięku — odtwarzanie sweepu i nagrywanie odpowiedzi.

Jedyne miejsce w projekcie, które dotyka karty dźwiękowej. Reszta modułu
pomiarowego dostaje gotowe tablice próbek i nie wie, skąd pochodzą.

Trzy rzeczy, które decydują o poprawności pomiaru:

1. Odtwarzanie i nagrywanie MUSZĄ być jednoczesne, na tym samym strumieniu.
   `sounddevice.playrec` gwarantuje wspólny zegar, więc położenie odpowiedzi
   w nagraniu jest powtarzalne. Osobne strumienie rozjeżdżają się o
   nieprzewidywalną liczbę próbek i odległości wychodzą losowe.

2. Sweep trafia do JEDNEGO kanału wyjściowego. Pozostałe dostają ciszę,
   więc mierzymy jeden głośnik naraz.

3. Kanał odniesienia (pętla wyjście-wejście) daje bezwzględne opóźnienie
   toru. Bez niego odległości są względne — co do wyrównania kanałów
   między sobą wystarcza, ale do odczytu odległości w metrach już nie.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np

try:
    import sounddevice as sd
except Exception as _e:                              # noqa: BLE001
    sd = None
    _IMPORT_ERROR = str(_e)
else:
    _IMPORT_ERROR = ""


class AudioError(RuntimeError):
    pass


def _require() -> None:
    if sd is None:
        raise AudioError(
            f"biblioteka sounddevice niedostępna ({_IMPORT_ERROR}). "
            "Zainstaluj: pip install sounddevice")


# --------------------------------------------------------------------
# urządzenia
# --------------------------------------------------------------------

def host_apis() -> list[dict]:
    _require()
    return [
        {"index": i, "name": a["name"], "devices": len(a["devices"]),
         "default_input": a["default_input_device"],
         "default_output": a["default_output_device"]}
        for i, a in enumerate(sd.query_hostapis())
    ]


def devices() -> dict:
    """Wejścia i wyjścia widziane przez system, z podziałem na API.

    Interesują nas dwie rzeczy, które od razu mówią, czy pomiar w ogóle
    wyjdzie: czy jest ASIO (niski i stały czas reakcji) oraz czy któreś
    wyjście wystawia więcej niż dwa kanały (warunek mierzenia centralnego
    i surroundów).
    """
    _require()
    ins, outs = [], []
    for i, d in enumerate(sd.query_devices()):
        api = sd.query_hostapis(d["hostapi"])["name"]
        entry = {
            "index": i, "name": d["name"], "api": api,
            "inputs": d["max_input_channels"],
            "outputs": d["max_output_channels"],
            "samplerate": int(d["default_samplerate"]),
            "latency_in": round(d["default_low_input_latency"] * 1000, 1),
            "latency_out": round(d["default_low_output_latency"] * 1000, 1),
        }
        if d["max_input_channels"] > 0:
            ins.append(entry)
        if d["max_output_channels"] > 0:
            outs.append(entry)
    return {
        "apis": host_apis(),
        "inputs": ins,
        "outputs": outs,
        "has_asio": any(a["name"] == "ASIO" for a in host_apis()),
        "multichannel": [o for o in outs if o["outputs"] > 2],
    }


def check(input_device: int | None, output_device: int | None,
          samplerate: int = 48000, channels_out: int = 2,
          channels_in: int = 2) -> dict:
    """Sprawdza, czy zadana kombinacja da się w ogóle otworzyć."""
    _require()
    try:
        sd.check_output_settings(device=output_device, channels=channels_out,
                                 samplerate=samplerate)
        sd.check_input_settings(device=input_device, channels=channels_in,
                                samplerate=samplerate)
        return {"ok": True}
    except Exception as e:                           # noqa: BLE001
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# podgląd poziomu
# --------------------------------------------------------------------

class LevelMonitor:
    """Ciągły odczyt poziomu z wejścia — do ustawienia wzmocnienia.

    Bez tego pomiar zaczyna się w ciemno: za cicho i tonie w szumie,
    za głośno i wchodzi w obcięcie, czego w widmie nie widać wprost,
    a psuje wynik.
    """

    def __init__(self, device: int | None, channels: int = 2,
                 samplerate: int = 48000) -> None:
        _require()
        self.device = device
        self.channels = channels
        self.samplerate = samplerate
        self._stream: "sd.InputStream | None" = None
        self._lock = threading.Lock()
        self._peak = np.zeros(channels)
        self._rms = np.zeros(channels)
        self._clipped = np.zeros(channels, dtype=bool)

    def _callback(self, indata, frames, time_info, status) -> None:
        block = np.asarray(indata)
        with self._lock:
            peak = np.abs(block).max(axis=0)
            self._peak = np.maximum(self._peak * 0.85, peak)
            self._rms = np.sqrt((block ** 2).mean(axis=0) + 1e-20)
            self._clipped |= peak >= 0.999

    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
        stream = sd.InputStream(device=self.device, channels=self.channels,
                                samplerate=self.samplerate, blocksize=1024,
                                callback=self._callback)
        stream.start()
        self._stream = stream

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()

    @property
    def running(self) -> bool:
        return self._stream is not None

    def read(self) -> dict:
        with self._lock:
            peak, rms, clipped = self._peak.copy(), self._rms.copy(), self._clipped.copy()
        to_db = lambda x: [round(float(20 * np.log10(max(v, 1e-9))), 1) for v in x]
        return {
            "peak_db": to_db(peak),
            "rms_db": to_db(rms),
            "clipped": [bool(c) for c in clipped],
            "channels": self.channels,
        }

    def reset_clip(self) -> None:
        with self._lock:
            self._clipped[:] = False


# --------------------------------------------------------------------
# pomiar
# --------------------------------------------------------------------

@dataclass
class CaptureSetup:
    """Konfiguracja toru pomiarowego."""

    input_device: int | None = None
    output_device: int | None = None
    samplerate: int = 48000
    output_channels: int = 2      # ile kanałów ma wyjście
    input_channels: int = 2       # ile kanałów ma wejście
    mic_channel: int = 0          # na którym wejściu siedzi mikrofon
    reference_channel: int | None = None   # pętla odniesienia, jeśli jest
    output_gain: float = 0.35     # amplituda sweepu, zapas do obcięcia

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "input_device", "output_device", "samplerate", "output_channels",
            "input_channels", "mic_channel", "reference_channel", "output_gain")}


def play_and_record(signal: np.ndarray, setup: CaptureSetup,
                    out_channel: int, tail_seconds: float = 1.0) -> np.ndarray:
    """Wypuszcza sygnał w jeden kanał i nagrywa wejścia jednocześnie.

    Ogon po sweepie daje pomieszczeniu czas na wybrzmienie — bez niego
    obcinamy własną odpowiedź impulsową.
    """
    _require()
    if not 0 <= out_channel < setup.output_channels:
        raise AudioError(
            f"kanał {out_channel} poza zakresem wyjścia "
            f"({setup.output_channels} kanałów)")

    tail = int(tail_seconds * setup.samplerate)
    buffer = np.zeros((len(signal) + tail, setup.output_channels), dtype=np.float32)
    buffer[:len(signal), out_channel] = signal * setup.output_gain

    try:
        recorded = sd.playrec(
            buffer,
            samplerate=setup.samplerate,
            device=(setup.input_device, setup.output_device),
            channels=setup.input_channels,
            blocking=True,
        )
    except Exception as e:                           # noqa: BLE001
        raise AudioError(f"nie udało się odtworzyć i nagrać: {e}") from e
    return np.asarray(recorded, dtype=np.float64)


def capture_quality(recorded: np.ndarray, mic_channel: int) -> dict:
    """Ocena nagrania: czy nie za cicho, czy nie obcięte."""
    mic = recorded[:, mic_channel]
    peak = float(np.abs(mic).max())
    peak_db = 20 * np.log10(max(peak, 1e-9))
    # Szum szacujemy z pierwszych 200 ms, zanim sweep zdąży dojść.
    head = mic[:min(len(mic) // 10, 9600)]
    noise_db = 20 * np.log10(max(float(np.sqrt((head ** 2).mean())), 1e-9))
    warnings = []
    if peak >= 0.999:
        warnings.append("sygnał obcięty — zmniejsz wzmocnienie wejścia")
    elif peak_db < -40:
        warnings.append("bardzo cicho — podnieś wzmocnienie albo głośność")
    if peak_db - noise_db < 30:
        warnings.append("mały odstęp od szumu — pomiar będzie niepewny")
    return {
        "peak_db": round(peak_db, 1),
        "noise_db": round(noise_db, 1),
        "snr_db": round(peak_db - noise_db, 1),
        "warnings": warnings,
    }
