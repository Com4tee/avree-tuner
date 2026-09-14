"""Sesja pomiarowa — spina wejście audio z analizą i trzyma wyniki.

Jedno miejsce, które wie o całej procedurze: co zagrać, w który kanał,
jak długo czekać, co z tego policzyć i jak podać do narysowania.

Wyniki podajemy do interfejsu w siatce logarytmicznej po kilkuset punktach.
Surowe widmo ma kilkanaście tysięcy prążków, z czego w dole pasma prawie
wszystkie są puste, a w górze i tak nie da się ich odróżnić na wykresie.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import numpy as np

from . import audio, measure

# Kanały, które umiemy zaadresować, i ich indeks w strumieniu wielokanałowym.
# Kolejność Windows dla 5.1: FL, FR, FC, LFE, BL, BR.
# UWAGA: nie jest to pewnik. Część API i formatów używa innej kolejności,
# dlatego mapę trzeba potwierdzić pomiarowo — patrz `identify_channels`.
DEFAULT_CHANNEL_MAP = {
    "FL": 0, "FR": 1, "C": 2, "LFE": 3, "SL": 4, "SR": 5,
}

CHANNEL_LABELS = {
    "FL": "Front L", "FR": "Front R", "C": "Center",
    "LFE": "Subwoofery (LFE)", "SL": "Surround L", "SR": "Surround R",
}


def log_grid(freqs: np.ndarray, values: np.ndarray,
             low: float = 15.0, high: float = 22000.0,
             points: int = 420) -> tuple[list[float], list[float]]:
    """Przerzedza widmo na siatkę logarytmiczną do rysowania.

    W każdym oczku bierzemy średnią, a nie najbliższy prążek — inaczej
    w górze pasma losowo trafiamy w szczyt albo w dolinę grzebienia
    i wykres zmienia się przy każdym odświeżeniu.
    """
    edges = np.logspace(np.log10(low), np.log10(high), points + 1)
    centres, out = [], []
    for i in range(points):
        mask = (freqs >= edges[i]) & (freqs < edges[i + 1])
        if not mask.any():
            continue
        centres.append(round(float(np.sqrt(edges[i] * edges[i + 1])), 2))
        out.append(round(float(values[mask].mean()), 2))
    return centres, out


@dataclass
class SessionState:
    running: bool = False
    step: str = ""
    channel: str = ""
    position: int = 0
    error: str | None = None
    progress: float = 0.0


@dataclass
class MeasureSession:
    """Pomiary jednego zestawu: wiele kanałów, wiele pozycji mikrofonu."""

    setup: audio.CaptureSetup = field(default_factory=audio.CaptureSetup)
    f_start: float = 15.0
    f_stop: float = 22000.0
    duration: float = 6.0
    channel_map: dict = field(default_factory=lambda: dict(DEFAULT_CHANNEL_MAP))
    measurements: list[measure.Measurement] = field(default_factory=list)
    loopback_offset: int = 0
    state: SessionState = field(default_factory=SessionState)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _monitor: audio.LevelMonitor | None = field(default=None, repr=False)

    # ---- podgląd poziomu ----

    def monitor_start(self) -> dict:
        with self._lock:
            if self._monitor is None:
                self._monitor = audio.LevelMonitor(
                    self.setup.input_device, self.setup.input_channels,
                    self.setup.samplerate)
            if not self._monitor.running:
                self._monitor.start()
            return {"ok": True}

    def monitor_stop(self) -> dict:
        with self._lock:
            if self._monitor:
                self._monitor.stop()
            return {"ok": True}

    def monitor_read(self) -> dict:
        with self._lock:
            if self._monitor is None or not self._monitor.running:
                return {"running": False}
            data = self._monitor.read()
            data["running"] = True
            return data

    # ---- pojedynczy pomiar ----

    def sweep(self) -> tuple[np.ndarray, np.ndarray]:
        s = measure.log_sweep(self.f_start, self.f_stop, self.duration,
                              self.setup.samplerate)
        inv = measure.inverse_filter(s, self.f_start, self.f_stop,
                                     self.setup.samplerate)
        return s, inv

    def run_one(self, channel: str, position: int = 1) -> dict:
        """Jeden sweep w jeden kanał, z analizą i zapisem wyniku."""
        index = self.channel_map.get(channel)
        if index is None:
            raise audio.AudioError(f"nie znam kanału {channel}")

        with self._lock:
            if self.state.running:
                raise audio.AudioError("pomiar już trwa")
            self.state = SessionState(running=True, step="odtwarzanie",
                                      channel=channel, position=position)

        # Monitor poziomu blokuje wejście, więc zwalniamy je na czas pomiaru.
        was_monitoring = self._monitor is not None and self._monitor.running
        if was_monitoring:
            self._monitor.stop()

        try:
            signal, inverse = self.sweep()
            recorded = audio.play_and_record(signal, self.setup, index)

            self.state.step = "analiza"
            self.state.progress = 0.6
            quality = audio.capture_quality(recorded, self.setup.mic_channel)

            mic = recorded[:, self.setup.mic_channel]
            ir = measure.deconvolve(mic, inverse)

            # Pętla odniesienia daje bezwzględne opóźnienie toru.
            offset = self.loopback_offset
            if self.setup.reference_channel is not None:
                ref = recorded[:, self.setup.reference_channel]
                ref_ir = measure.deconvolve(ref, inverse)
                offset = measure.find_arrival(ref_ir)
                self.loopback_offset = offset

            item = measure.Measurement(channel, position, self.setup.samplerate, ir)
            item.analyse(loopback_offset=offset)

            with self._lock:
                self.measurements = [
                    m for m in self.measurements
                    if not (m.channel == channel and m.position == position)
                ]
                self.measurements.append(item)
            return {"ok": True, "quality": quality,
                    "metrics": item.metrics, "curve": self.curve(channel, position)}
        except Exception as e:                        # noqa: BLE001
            self.state.error = str(e)
            raise
        finally:
            self.state.running = False
            self.state.step = ""
            self.state.progress = 0.0
            if was_monitoring:
                try:
                    self._monitor.start()
                except Exception:                     # noqa: BLE001
                    pass

    # ---- wyniki do rysowania ----

    def curve(self, channel: str, position: int) -> dict | None:
        item = next((m for m in self.measurements
                     if m.channel == channel and m.position == position), None)
        if item is None:
            return None
        freqs, mag = log_grid(item.freqs, item.magnitude)
        _, smoothed = log_grid(
            item.freqs, measure.smooth(item.freqs, item.magnitude, variable=True))
        return {"channel": channel, "position": position, "freqs": freqs,
                "magnitude": mag, "smoothed": smoothed, "metrics": item.metrics}

    def combined(self, channel: str, mode: str = "auto") -> dict | None:
        """Uśrednienie wszystkich pozycji danego kanału."""
        items = [m for m in self.measurements if m.channel == channel]
        if not items:
            return None
        result = measure.analyse_set(items, mode=mode)
        freqs, mag = log_grid(result["freqs"], result["magnitude"])
        _, smoothed = log_grid(result["freqs"], result["smoothed"])
        distances = [d for d in result["distances"] if d is not None]
        return {
            "channel": channel,
            "positions": result["positions"],
            "freqs": freqs, "magnitude": mag, "smoothed": smoothed,
            "distance_m": round(float(np.mean(distances)), 3) if distances else None,
            # Flaga z measure.py: maska korygowalności NIE jest zweryfikowana.
            "correctable_verified": result.get("correctable_verified", False),
        }

    def overview(self) -> dict:
        with self._lock:
            done: dict[str, list[int]] = {}
            for m in self.measurements:
                done.setdefault(m.channel, []).append(m.position)
            return {
                "setup": self.setup.to_dict(),
                "sweep": {"f_start": self.f_start, "f_stop": self.f_stop,
                          "duration": self.duration},
                "channels": [
                    {"code": c, "label": CHANNEL_LABELS.get(c, c),
                     "index": self.channel_map.get(c),
                     "positions": sorted(done.get(c, []))}
                    for c in self.channel_map
                ],
                "loopback_offset": self.loopback_offset,
                "loopback_ms": round(self.loopback_offset / self.setup.samplerate * 1000, 2),
                "state": {
                    "running": self.state.running, "step": self.state.step,
                    "channel": self.state.channel, "position": self.state.position,
                    "error": self.state.error,
                },
                "count": len(self.measurements),
            }

    def clear(self, channel: str | None = None) -> dict:
        with self._lock:
            if channel:
                self.measurements = [m for m in self.measurements
                                     if m.channel != channel]
            else:
                self.measurements = []
            return {"ok": True, "count": len(self.measurements)}

    # ---- mapa kanałów ----

    def identify_channels(self, indices: list[int] | None = None,
                          duration: float = 2.0) -> list[dict]:
        """Ustala pomiarowo, który indeks wyjścia trafia w który głośnik.

        Kolejność kanałów w strumieniu wielokanałowym nie jest pewnikiem:
        Windows używa FL, FR, FC, LFE, BL, BR, ale część API i formatów
        stosuje FL, FR, BL, BR, FC, LFE. Pomylenie oznacza mierzenie
        centralnego w przekonaniu, że to subwoofer.

        Zamiast wierzyć dokumentacji, puszczamy krótki sweep w każdy indeks
        po kolei i notujemy poziom oraz czas dotarcia. Różne głośniki stoją
        w różnej odległości, więc te dwie liczby wystarczą, żeby je rozróżnić
        — resztę przypisania robi człowiek, słysząc, co zagrało.
        """
        if indices is None:
            indices = list(range(self.setup.output_channels))

        short = measure.log_sweep(self.f_start, self.f_stop, duration,
                                  self.setup.samplerate)
        inverse = measure.inverse_filter(short, self.f_start, self.f_stop,
                                         self.setup.samplerate)
        results = []
        for index in indices:
            try:
                recorded = audio.play_and_record(short, self.setup, index,
                                                 tail_seconds=0.5)
            except audio.AudioError as e:
                results.append({"index": index, "error": str(e)})
                continue
            mic = recorded[:, self.setup.mic_channel]
            level = float(np.abs(mic).max())
            entry = {
                "index": index,
                "peak_db": round(20 * np.log10(max(level, 1e-9)), 1),
                "silent": level < 0.003,
            }
            if not entry["silent"]:
                ir = measure.deconvolve(mic, inverse)
                entry.update(measure.arrival_metrics(ir, self.setup.samplerate,
                                                     self.loopback_offset))
            results.append(entry)
            time.sleep(0.3)
        return results
