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

from . import analiza, audio, measure, optimize

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


    # ---- wnioski liczone z pomiaru ----
    #
    # Umowa pozycji dla porównania A/B: pomiary z Audyssey WŁĄCZONYM idą na
    # pozycje 1..N, z WYŁĄCZONYM na 101..100+N. Dzięki temu jedno i drugie
    # mieści się w istniejącej strukturze bez dokładania pól, a pary
    # pozycja↔pozycja są oczywiste: 1 i 101 to ten sam punkt w pokoju.
    AB_OFFSET = 100

    def subset_curve(self, channel: str, positions: list[int],
                     mode: str = "auto") -> dict | None:
        """Uśrednienie wybranych pozycji, a nie wszystkich."""
        wanted = set(int(p) for p in positions)
        items = [m for m in self.measurements
                 if m.channel == channel and m.position in wanted]
        if not items:
            return None
        result = measure.analyse_set(items, mode=mode)
        freqs, mag = log_grid(result["freqs"], result["magnitude"])
        _, smoothed = log_grid(result["freqs"], result["smoothed"])
        return {"freqs": freqs, "magnitude": mag, "smoothed": smoothed,
                "positions": sorted(wanted)}

    def crossover(self, channel: str) -> dict:
        """Proponowany punkt podziału z opadania zmierzonego kanału."""
        curve = self.combined(channel)
        if curve is None:
            return {"ready": False, "note": f"brak pomiarów kanału {channel}"}
        out = analiza.crossover_advice(curve["freqs"], curve["smoothed"])
        out["channel"] = channel
        out["positions"] = curve["positions"]
        return out

    def ab_positions(self, channel: str) -> dict:
        """Które pozycje są zmierzone z Audyssey ON, a które z OFF."""
        on, off = [], []
        for m in self.measurements:
            if m.channel != channel:
                continue
            (off if m.position > self.AB_OFFSET else on).append(m.position)
        return {"on": sorted(on), "off": sorted(off)}

    def correction(self, channel: str) -> dict:
        """Krzywa korekcji Audyssey z różnicy pomiarów ON i OFF.

        Gotowych filtrów nie da się odczytać z procesora — takiej komendy
        nie ma. Ta różnica jest tym samym, tylko zmierzonym akustycznie,
        i pokazuje dodatkowo wpływ głośnika oraz pomieszczenia.
        """
        pos = self.ab_positions(channel)
        if not pos["on"] or not pos["off"]:
            return {"ready": False, "positions": pos, "note": (
                "potrzebne oba komplety: z Audyssey włączonym (pozycje 1..N) "
                "i wyłączonym (101..100+N)")}

        on = self.subset_curve(channel, pos["on"])
        off = self.subset_curve(channel, pos["off"])
        if on is None or off is None:
            return {"ready": False, "positions": pos, "note": "brak danych"}

        out = analiza.correction_curve(on["freqs"], on["smoothed"], off["smoothed"])
        out["ready"] = True
        out["channel"] = channel
        out["positions"] = pos
        out["on_db"] = on["smoothed"]
        out["off_db"] = off["smoothed"]
        return out

    def clear(self, channel: str | None = None) -> dict:
        with self._lock:
            if channel:
                self.measurements = [m for m in self.measurements
                                     if m.channel != channel]
            else:
                self.measurements = []
            return {"ok": True, "count": len(self.measurements)}

    # ---- optymalizacja ----

    def optimise(self, channel: str, constraints: dict | None = None,
                 mode: str = "auto", tilt: float = 0.0) -> dict:
        """Dobiera filtry dla uśrednionej odpowiedzi kanału.

        Pracujemy na krzywej WYGŁADZONEJ i uśrednionej po pozycjach.
        Na surowym pomiarze z jednego punktu optymalizator goniłby
        filtrowanie grzebieniowe, które kilka centymetrów dalej wygląda
        zupełnie inaczej.
        """
        items = [m for m in self.measurements if m.channel == channel]
        if not items:
            raise audio.AudioError(f"brak pomiarów kanału {channel}")

        analysis = measure.analyse_set(items, mode=mode)
        freqs = analysis["freqs"]
        smoothed = analysis["smoothed"]

        given = dict(constraints or {})
        usable = analysis.get("usable_range") or {}

        # Górną granicę bierzemy z pomiaru, o ile użytkownik nie narzucił
        # własnej: powyżej częstotliwości, na której pozycje przestają się
        # zgadzać, filtr poprawia jeden punkt i psuje pozostałe.
        suggested = usable.get("limit_hz")
        if suggested and "f_high" not in given:
            given["f_high"] = float(min(suggested, 20000.0))

        limits = optimize.Constraints(**given)
        target = optimize.target_curve(freqs, smoothed, tilt_db_per_octave=tilt)
        result = optimize.fit_filters(freqs, smoothed, target, limits,
                                      self.setup.samplerate)

        # Do rysowania przerzedzamy tak samo jak pomiary, żeby krzywe
        # leżały na tej samej siatce.
        grid, before = log_grid(freqs, smoothed)
        _, after = log_grid(freqs, np.asarray(result["corrected"]))
        _, target_grid = log_grid(freqs, np.asarray(result["target"]))
        _, filters = log_grid(
            freqs, optimize.simulate(result["bands"], freqs, self.setup.samplerate))

        result["curves"] = {"freqs": grid, "before": before, "after": after,
                            "target": target_grid, "filters": filters}
        result["channel"] = channel
        result["positions"] = analysis["positions"]
        result["usable_range"] = usable
        result["f_high_source"] = ("pomiar" if suggested and "f_high" not in (constraints or {})
                                   else "ustawienie")
        result.pop("corrected", None)
        result.pop("target", None)
        return result

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
