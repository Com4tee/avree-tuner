"""Zestrojenie czasowe dwóch subwooferów przez przemiatanie opóźnienia.

Metoda, wprost z pytania użytkownika: puszczamy ten sam sygnał w oba suby,
krok po kroku przesuwamy opóźnienie jednego z nich i mierzymy mikrofonem
w miejscu odsłuchu. Tam, gdzie fale sumują się najlepiej, poziom w paśmie
jest najwyższy. To maksimum jest szukaną nastawą.

Dlaczego akurat tak, a nie „zmierz każdy sub osobno i policz różnicę":
wzmacniacz podaje oba subwoofery z tego samego sygnału LFE i nie da się
z zewnątrz wyciszyć jednego z nich (`CVSW2` schodzi do −12 dB, nie do ciszy).
Przemiatanie nie wymaga rozdzielania kanałów — mierzy od razu to, co słychać
na kanapie, czyli sumę. To jest zaleta, nie kompromis.

Sterowanie opóźnieniem idzie przez odległość kanału:

    SSSDESW  0427M     subwoofer 1
    SSSDESW2 0886M     subwoofer 2
    SSSDESTP 01M       krok 1 cm

Sprawdzone na AVR-X3300W: odczyt i zapis działają. Krok 1 cm to 29 µs przy
343 m/s — przy 50 Hz odpowiada przesunięciu fazy o pół stopnia. Zmiana
odległości nie unieważnia filtrów Audyssey, to osobna warstwa nastaw.

Czego ta metoda NIE załatwia. Maksimum znalezione dla jednej pozycji
mikrofonu jest optymalne dla tej pozycji. Przy kanapie trzyosobowej warto
powtórzyć pomiar w kilku punktach i wziąć nastawę, która wypada dobrze
wszędzie, zamiast idealnej w jednym miejscu i gorszej obok.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import numpy as np

from . import audio, measure

SPEED_OF_SOUND = 343.0            # m/s, 20 °C


def cm_to_ms(centimetres: float) -> float:
    """Ile milisekund opóźnienia odpowiada danej odległości."""
    return centimetres / 100.0 / SPEED_OF_SOUND * 1000.0


def phase_degrees(centimetres: float, freq_hz: float) -> float:
    """O ile stopni przesuwa się faza przy danej częstotliwości."""
    wavelength_cm = SPEED_OF_SOUND / freq_hz * 100.0
    return centimetres / wavelength_cm * 360.0


@dataclass
class AlignPlan:
    """Zakres przemiatania."""

    channel: str = "SW2"          # który subwoofer przesuwamy
    span_cm: int = 150            # ile w każdą stronę od bieżącej nastawy
    step_cm: int = 5              # co ile centymetrów
    f_low: float = 20.0           # dolna granica pasma oceny
    f_high: float = 120.0         # górna granica pasma oceny
    settle_s: float = 0.35        # ile czekamy, aż wzmacniacz przyjmie nastawę
    duration: float = 1.5         # długość sygnału pomiarowego

    def candidates(self, centre_cm: int, lo: int = 0, hi: int = 1800) -> list[int]:
        """Lista nastaw do sprawdzenia, przycięta do zakresu urządzenia."""
        raw = range(centre_cm - self.span_cm,
                    centre_cm + self.span_cm + 1, max(1, self.step_cm))
        return [v for v in raw if lo <= v <= hi]

    def points(self, centre_cm: int) -> int:
        return len(self.candidates(centre_cm))

    def estimate_seconds(self, centre_cm: int) -> float:
        per = self.settle_s + self.duration + 0.6   # +nagrywanie i ogon
        return round(self.points(centre_cm) * per, 1)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "channel", "span_cm", "step_cm", "f_low", "f_high",
            "settle_s", "duration")}


def band_level_db(recording: np.ndarray, samplerate: int,
                  f_low: float, f_high: float) -> float:
    """Poziom sygnału w zadanym paśmie, w dB.

    Liczymy wprost z nagrania, bez dekonwolucji: interesuje nas wyłącznie
    RÓŻNICA między kolejnymi nastawami, a sygnał pobudzający jest za każdym
    razem ten sam. Dekonwolucja nic by tu nie wniosła poza czasem liczenia.
    """
    data = np.asarray(recording, dtype=np.float64)
    if data.size == 0:
        return -120.0
    window = np.hanning(len(data))
    spectrum = np.abs(np.fft.rfft(data * window))
    freqs = np.fft.rfftfreq(len(data), 1.0 / samplerate)
    mask = (freqs >= f_low) & (freqs <= f_high)
    if not mask.any():
        return -120.0
    energy = float(np.sqrt((spectrum[mask] ** 2).sum()) / len(data))
    return round(20 * np.log10(max(energy, 1e-12)), 2)


@dataclass
class SubAlign:
    """Przemiatanie opóźnienia subwoofera z pomiarem mikrofonem."""

    setup: audio.CaptureSetup = field(default_factory=audio.CaptureSetup)
    plan: AlignPlan = field(default_factory=AlignPlan)
    out_channel: int = 0          # którym wyjściem karty gramy sygnał

    running: bool = False
    done: int = 0
    total: int = 0
    note: str = ""
    error: str = ""
    original_cm: int | None = None
    restored: bool = False
    results: list[dict] = field(default_factory=list)

    _thread: threading.Thread | None = field(default=None, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # ---- sygnał pomiarowy ----

    def signal(self) -> np.ndarray:
        """Krótki sweep ograniczony do pasma subwoofera.

        Wąskie pasmo zamiast pojedynczego tonu, bo pojedyncza częstotliwość
        potrafi mieć maksimum w zupełnie innym miejscu niż całe pasmo —
        wtedy zestroiłoby się 40 Hz kosztem 70 Hz.
        """
        return measure.log_sweep(
            self.plan.f_low, self.plan.f_high,
            self.plan.duration, self.setup.samplerate)

    # ---- przebieg ----

    def start(self, avr) -> dict:
        with self._lock:
            if self.running:
                return {"ok": False, "error": "przemiatanie już trwa"}

        current = (avr.snapshot().get("distances") or {}).get(self.plan.channel)
        if current is None:
            raise RuntimeError(
                f"nie znam bieżącej odległości kanału {self.plan.channel}. "
                "Odśwież stan amplitunera (SSSDE ?) i spróbuj ponownie.")

        self.original_cm = int(current)
        self.restored = False
        self.results = []
        self.done = 0
        self.total = self.plan.points(self.original_cm)
        self.error = ""
        self.note = "start…"
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(avr,), daemon=True)
        self.running = True
        self._thread.start()
        return {"ok": True, "total": self.total,
                "original_cm": self.original_cm,
                "estimate_s": self.plan.estimate_seconds(self.original_cm)}

    def stop(self) -> dict:
        self._stop.set()
        return {"ok": True}

    def _run(self, avr) -> None:
        signal = self.signal()
        candidates = self.plan.candidates(self.original_cm)
        try:
            for value in candidates:
                if self._stop.is_set():
                    self.note = "przerwane przez użytkownika"
                    break

                avr.set_distance_cm(self.plan.channel, value)
                time.sleep(self.plan.settle_s)

                recorded = audio.play_and_record(
                    signal, self.setup, self.out_channel, tail_seconds=0.6)
                mic = recorded[:, self.setup.mic_channel]
                level = band_level_db(mic, self.setup.samplerate,
                                      self.plan.f_low, self.plan.f_high)

                self.results.append({
                    "cm": value,
                    "delta_cm": value - self.original_cm,
                    "delta_ms": round(cm_to_ms(value - self.original_cm), 3),
                    "level_db": level,
                    "peak": round(float(np.abs(mic).max()), 4),
                })
                self.done += 1
                self.note = (f"{self.done}/{self.total} — "
                             f"{value} cm: {level:+.2f} dB")
        except Exception as e:                       # noqa: BLE001
            self.error = str(e)
            self.note = "przerwane błędem"
        finally:
            # Nastawa MUSI wrócić na swoje miejsce, także po błędzie —
            # inaczej zostawiamy wzmacniacz z przypadkową wartością
            # z połowy przemiatania.
            self._restore(avr)
            self.running = False

    def _restore(self, avr) -> None:
        if self.original_cm is None:
            return
        for attempt in range(3):
            try:
                avr.set_distance_cm(self.plan.channel, self.original_cm)
                time.sleep(0.3)
                now = (avr.snapshot().get("distances") or {}).get(self.plan.channel)
                if now is not None and int(now) == self.original_cm:
                    self.restored = True
                    return
            except Exception:                        # noqa: BLE001
                time.sleep(0.5)
        self.error = (self.error + " | " if self.error else "") + (
            f"NIE UDAŁO SIĘ PRZYWRÓCIĆ {self.plan.channel} na "
            f"{self.original_cm} cm — ustaw ręcznie")

    # ---- wynik ----

    def analyse(self) -> dict:
        """Najlepsza nastawa i to, ile na niej zyskujemy."""
        if len(self.results) < 3:
            return {"ready": False, "note": "za mało punktów"}

        cm = np.array([r["cm"] for r in self.results], dtype=float)
        db = np.array([r["level_db"] for r in self.results], dtype=float)

        best = int(np.argmax(db))
        worst = int(np.argmin(db))

        # Wierzchołek dopasowany parabolą przez trzy punkty wokół maksimum —
        # daje rozdzielczość lepszą niż krok przemiatania, bo prawdziwe
        # maksimum rzadko wypada dokładnie w zmierzonym punkcie.
        refined = float(cm[best])
        if 0 < best < len(cm) - 1:
            y0, y1, y2 = db[best - 1], db[best], db[best + 1]
            denom = y0 - 2 * y1 + y2
            if denom != 0:
                offset = 0.5 * (y0 - y2) / denom
                if abs(offset) <= 1.0:
                    refined = float(cm[best] + offset * (cm[best] - cm[best - 1]))

        current_db = None
        for r in self.results:
            if r["cm"] == self.original_cm:
                current_db = r["level_db"]

        return {
            "ready": True,
            "best_cm": int(round(refined)),
            "best_measured_cm": int(cm[best]),
            "best_db": float(db[best]),
            "worst_cm": int(cm[worst]),
            "worst_db": float(db[worst]),
            "span_db": round(float(db[best] - db[worst]), 2),
            "current_cm": self.original_cm,
            "current_db": current_db,
            "gain_vs_current_db": (round(float(db[best]) - current_db, 2)
                                   if current_db is not None else None),
            "shift_cm": (int(round(refined)) - self.original_cm
                         if self.original_cm is not None else None),
            "shift_ms": round(cm_to_ms(int(round(refined)) - (self.original_cm or 0)), 3),
            "phase_at_50hz": round(
                phase_degrees(int(round(refined)) - (self.original_cm or 0), 50.0), 1),
        }

    def overview(self) -> dict:
        return {
            "running": self.running,
            "done": self.done,
            "total": self.total,
            "note": self.note,
            "error": self.error,
            "original_cm": self.original_cm,
            "restored": self.restored,
            "plan": self.plan.to_dict(),
            "results": self.results,
            "analysis": self.analyse(),
        }
