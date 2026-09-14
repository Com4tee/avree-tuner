"""Model equalizera parametrycznego — projekt filtrów i ich przechowywanie.

Dlaczego własny, skoro amplituner ma equalizer graficzny?

Sprawdziłem empirycznie na AVR-X3300W:
  * `PSGEQ ON/OFF` działa, ale WYŁĄCZNIE przy `PSMULTEQ:OFF` — equalizer
    graficzny i Audyssey wykluczają się wzajemnie;
  * wartości pasm NIE są adresowalne po sieci. Przetestowane składnie
    (PSGEQFL63, SSGEQFL63, PSGEQ FL 63, SSGEQFL 63, PSGEQ6355) milczą.
    Suwaki istnieją tylko w menu ekranowym;
  * trybu `PSMULTEQ:MANUAL` ten model nie ma — Deviceinfo.xml wymienia
    tylko Reference, L/R Bypass, Flat i Off.

Czyli: equalizera z ręki, sterowanego po LAN, w tym amplitunerze nie ma.
Robimy własny. Filtry zaprojektowane tutaj mają trzy możliwe ujścia:

  1. PODGLĄD      — rysunek krzywej na tle pomiaru; działa od razu
  2. TOR PC       — splot w strumieniu wychodzącym z komputera przez
                    TOSLINK/DLNA, przy Audyssey wyłączonym; pełna kontrola
  3. DSP AUDYSSEY — wgranie przez plik .ady; wymaga zbudowania kanału uploadu

Matematyka to standardowe biquady z receptur Roberta Bristow-Johnsona
(Audio EQ Cookbook). Liczymy je tu, po stronie serwera, żeby ten sam model
obsłużył podgląd, eksport i późniejsze przetwarzanie dźwięku.
"""

from __future__ import annotations

import cmath
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .discovery import CONFIG_PATH

EQ_PATH = CONFIG_PATH.parent / "eq.json"

# Typy filtrów, które ma sens mieć pod ręką przy strojeniu pomieszczenia.
FILTER_TYPES = {
    "PK": "Peaking — dzwon o zadanej dobroci",
    "LS": "Low shelf — półka dolna",
    "HS": "High shelf — półka górna",
    "LP": "Low pass — odcięcie góry",
    "HP": "High pass — odcięcie dołu",
    "NO": "Notch — wąskie wycięcie",
}

# Kanały, które ten amplituner faktycznie obsługuje w konfiguracji 5.2.
EQ_CHANNELS = ["FL", "FR", "C", "SL", "SR", "SW", "SW2"]

DEFAULT_SAMPLE_RATE = 48000


@dataclass
class Band:
    """Jedno pasmo. `enabled` pozwala odsłuchać filtr bez kasowania go."""

    freq: float = 100.0
    gain: float = 0.0
    q: float = 2.0
    type: str = "PK"
    enabled: bool = True

    def biquad(self, fs: int = DEFAULT_SAMPLE_RATE) -> tuple[float, ...]:
        """Współczynniki (b0, b1, b2, a0, a1, a2) wg Audio EQ Cookbook."""
        a_gain = 10 ** (self.gain / 40.0)          # amplituda dla shelf/peak
        w0 = 2 * math.pi * max(1.0, min(self.freq, fs / 2 - 1)) / fs
        cos_w0 = math.cos(w0)
        sin_w0 = math.sin(w0)
        q = max(0.05, self.q)
        alpha = sin_w0 / (2 * q)

        if self.type == "PK":
            b0 = 1 + alpha * a_gain
            b1 = -2 * cos_w0
            b2 = 1 - alpha * a_gain
            a0 = 1 + alpha / a_gain
            a1 = -2 * cos_w0
            a2 = 1 - alpha / a_gain
        elif self.type == "NO":
            b0, b1, b2 = 1.0, -2 * cos_w0, 1.0
            a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
        elif self.type in ("LS", "HS"):
            # Współczynnik kształtu półki; 2*sqrt(A)*alpha to wariant
            # z receptury, stabilny dla szerokiego zakresu Q.
            sqrt_a = math.sqrt(a_gain)
            beta = 2 * sqrt_a * alpha
            if self.type == "LS":
                b0 = a_gain * ((a_gain + 1) - (a_gain - 1) * cos_w0 + beta)
                b1 = 2 * a_gain * ((a_gain - 1) - (a_gain + 1) * cos_w0)
                b2 = a_gain * ((a_gain + 1) - (a_gain - 1) * cos_w0 - beta)
                a0 = (a_gain + 1) + (a_gain - 1) * cos_w0 + beta
                a1 = -2 * ((a_gain - 1) + (a_gain + 1) * cos_w0)
                a2 = (a_gain + 1) + (a_gain - 1) * cos_w0 - beta
            else:
                b0 = a_gain * ((a_gain + 1) + (a_gain - 1) * cos_w0 + beta)
                b1 = -2 * a_gain * ((a_gain - 1) + (a_gain + 1) * cos_w0)
                b2 = a_gain * ((a_gain + 1) + (a_gain - 1) * cos_w0 - beta)
                a0 = (a_gain + 1) - (a_gain - 1) * cos_w0 + beta
                a1 = 2 * ((a_gain - 1) - (a_gain + 1) * cos_w0)
                a2 = (a_gain + 1) - (a_gain - 1) * cos_w0 - beta
        elif self.type == "LP":
            b0 = (1 - cos_w0) / 2
            b1 = 1 - cos_w0
            b2 = (1 - cos_w0) / 2
            a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
        elif self.type == "HP":
            b0 = (1 + cos_w0) / 2
            b1 = -(1 + cos_w0)
            b2 = (1 + cos_w0) / 2
            a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
        else:
            raise ValueError(f"nieznany typ filtra: {self.type}")

        return (b0, b1, b2, a0, a1, a2)

    def response_db(self, freqs: list[float], fs: int = DEFAULT_SAMPLE_RATE) -> list[float]:
        """Odpowiedź amplitudowa filtra w dB dla podanych częstotliwości."""
        if not self.enabled:
            return [0.0] * len(freqs)
        b0, b1, b2, a0, a1, a2 = self.biquad(fs)
        out = []
        for f in freqs:
            z = cmath.exp(-2j * math.pi * f / fs)
            num = b0 + b1 * z + b2 * z * z
            den = a0 + a1 * z + a2 * z * z
            mag = abs(num / den) if den != 0 else 1e-9
            out.append(20 * math.log10(max(mag, 1e-9)))
        return out


@dataclass
class ChannelEq:
    channel: str
    bands: list[Band] = field(default_factory=list)
    gain: float = 0.0            # wspólne przesunięcie poziomu kanału
    enabled: bool = True


@dataclass
class EqDesign:
    """Cały projekt korekcji: wszystkie kanały plus ustawienia globalne."""

    channels: dict[str, ChannelEq] = field(default_factory=dict)
    master_enabled: bool = False
    # Gdzie filtry mają trafić. 'preview' nic nie robi poza rysunkiem.
    destination: str = "preview"
    notes: str = ""

    def channel(self, name: str) -> ChannelEq:
        if name not in self.channels:
            self.channels[name] = ChannelEq(channel=name)
        return self.channels[name]

    def to_dict(self) -> dict:
        return {
            "master_enabled": self.master_enabled,
            "destination": self.destination,
            "notes": self.notes,
            "channels": {
                name: {
                    "channel": ch.channel, "gain": ch.gain, "enabled": ch.enabled,
                    "bands": [asdict(b) for b in ch.bands],
                }
                for name, ch in self.channels.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EqDesign":
        design = cls(
            master_enabled=bool(data.get("master_enabled", False)),
            destination=str(data.get("destination", "preview")),
            notes=str(data.get("notes", "")),
        )
        for name, ch in (data.get("channels") or {}).items():
            entry = design.channel(name)
            entry.gain = float(ch.get("gain", 0.0))
            entry.enabled = bool(ch.get("enabled", True))
            entry.bands = [
                Band(
                    freq=float(b.get("freq", 100.0)),
                    gain=float(b.get("gain", 0.0)),
                    q=float(b.get("q", 2.0)),
                    type=str(b.get("type", "PK")),
                    enabled=bool(b.get("enabled", True)),
                )
                for b in (ch.get("bands") or [])
            ]
        return design


def log_freqs(start: float = 10.0, stop: float = 24000.0, points: int = 380) -> list[float]:
    """Siatka logarytmiczna — tak, jak rysuje się wykresy akustyczne."""
    ratio = math.log10(stop / start)
    return [start * 10 ** (ratio * i / (points - 1)) for i in range(points)]


def channel_response(ch: ChannelEq, freqs: list[float],
                     fs: int = DEFAULT_SAMPLE_RATE) -> dict:
    """Krzywa sumaryczna kanału plus krzywa każdego pasma osobno.

    Osobne krzywe są potrzebne do rysowania: bez nich nie widać, które
    pasmo odpowiada za który fragment sumy, a przy strojeniu z ręki to
    jest najważniejsza informacja.
    """
    per_band = [b.response_db(freqs, fs) for b in ch.bands]
    total = [ch.gain] * len(freqs)
    if ch.enabled:
        for curve in per_band:
            for i, v in enumerate(curve):
                total[i] += v
    return {
        "freqs": [round(f, 2) for f in freqs],
        "total": [round(v, 3) for v in total],
        "bands": [[round(v, 3) for v in curve] for curve in per_band],
        "max_gain": round(max(total), 2) if total else 0.0,
        "min_gain": round(min(total), 2) if total else 0.0,
    }


# --------------------------------------------------------------------
# trwałość
# --------------------------------------------------------------------

def load() -> EqDesign:
    try:
        return EqDesign.from_dict(json.loads(EQ_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return default_design()


def save(design: EqDesign) -> None:
    try:
        EQ_PATH.parent.mkdir(parents=True, exist_ok=True)
        EQ_PATH.write_text(json.dumps(design.to_dict(), indent=2, ensure_ascii=False),
                           encoding="utf-8")
    except OSError:
        pass


def default_design() -> EqDesign:
    """Pusty projekt z jednym nieaktywnym pasmem na kanał — żeby było od czego zacząć."""
    design = EqDesign()
    for name in EQ_CHANNELS:
        ch = design.channel(name)
        ch.bands = [Band(freq=60.0, gain=0.0, q=2.0, type="PK", enabled=False)]
    return design
