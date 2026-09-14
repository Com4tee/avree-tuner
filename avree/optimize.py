"""Dobór filtrów korekcyjnych ze zmierzonej odpowiedzi.

Metoda zachłanna: znajdź największe odchylenie od celu, dopasuj do niego
jeden filtr, odejmij jego działanie od bieżącej odpowiedzi, powtórz.
Prosta, przewidywalna i łatwa do obejrzenia krok po kroku — w przeciwieństwie
do optymalizacji globalnej, gdzie nie wiadomo, skąd wziął się dany filtr.

Ograniczenia nie są opcją, tylko sednem. Przy aktywnych kolumnach z własnym
limiterem każdy dodatni decybel skraca zapas przed jego zadziałaniem, więc
domyślnie korygujemy WYŁĄCZNIE cięciami. Zamiast podbijać dziury, obniżamy
poziom całego kanału — efekt na osi jest ten sam, a nagłówek zostaje.

Czego ten moduł świadomie NIE robi: nie decyduje, jak wysoko sięgać.
Ta decyzja należy do `correctable_mask` w measure.py, która na dziś nie
działa. Do czasu jej naprawy górna granica jest parametrem od użytkownika.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .eq import Band

# Minimalne odchylenie, które w ogóle warto korygować. Poniżej tego
# filtr wnosi więcej ryzyka niż pożytku.
MIN_DEVIATION_DB = 1.0


@dataclass
class Constraints:
    """Granice, w których optymalizator może się poruszać."""

    f_low: float = 20.0           # dolna granica korekcji
    f_high: float = 300.0         # górna granica korekcji
    max_boost_db: float = 0.0     # 0 = wyłącznie cięcia
    max_cut_db: float = 12.0
    max_q: float = 8.0
    min_q: float = 0.5
    max_bands: int = 8
    min_deviation_db: float = MIN_DEVIATION_DB

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "f_low", "f_high", "max_boost_db", "max_cut_db",
            "max_q", "min_q", "max_bands", "min_deviation_db")}


def target_curve(freqs: np.ndarray, measured_db: np.ndarray,
                 reference_band: tuple[float, float] = (200.0, 500.0),
                 tilt_db_per_octave: float = 0.0,
                 pivot_hz: float = 1000.0) -> np.ndarray:
    """Krzywa, do której zmierzamy.

    Poziom odniesienia bierzemy ze średniej w wybranym paśmie, a nie
    z całości: inaczej głęboka dziura modalna zaniża cel i optymalizator
    zaczyna podbijać wszystko dookoła.

    `tilt_db_per_octave` pozwala zadać opadanie w stronę góry pasma —
    w typowym pomieszczeniu odsłuchowym łagodny spadek brzmi naturalniej
    niż idealna prosta.
    """
    mask = (freqs >= reference_band[0]) & (freqs <= reference_band[1])
    level = float(np.median(measured_db[mask])) if mask.any() else float(np.median(measured_db))
    if not tilt_db_per_octave:
        return np.full_like(freqs, level)
    octaves = np.log2(np.maximum(freqs, 1e-6) / pivot_hz)
    return level + octaves * tilt_db_per_octave


def _estimate_q(freqs: np.ndarray, deviation: np.ndarray,
                index: int, constraints: Constraints) -> float:
    """Dobroć z szerokości odchylenia na połowie jego wysokości."""
    peak = deviation[index]
    if peak == 0:
        return constraints.min_q
    half = peak / 2.0
    sign = np.sign(peak)

    lo = index
    while lo > 0 and sign * deviation[lo] > sign * half:
        lo -= 1
    hi = index
    while hi < len(deviation) - 1 and sign * deviation[hi] > sign * half:
        hi += 1

    f_lo, f_hi = freqs[lo], freqs[hi]
    if f_hi <= f_lo or f_lo <= 0:
        return constraints.max_q
    q = freqs[index] / (f_hi - f_lo)
    return float(np.clip(q, constraints.min_q, constraints.max_q))


def fit_filters(freqs: np.ndarray, measured_db: np.ndarray,
                target_db: np.ndarray | None = None,
                constraints: Constraints | None = None,
                fs: int = 48000) -> dict:
    """Dobiera filtry zachłannie, krok po kroku.

    Zwraca też przebieg pracy: co znalazł w którym kroku i ile zostało.
    Dzięki temu widać, dlaczego powstał dany filtr, zamiast dostać
    nieprzejrzysty zestaw liczb.
    """
    constraints = constraints or Constraints()
    if target_db is None:
        target_db = target_curve(freqs, measured_db)

    band_mask = (freqs >= constraints.f_low) & (freqs <= constraints.f_high)
    if not band_mask.any():
        return {"bands": [], "steps": [], "error": "pusty zakres korekcji"}

    current = measured_db.astype(float).copy()
    bands: list[Band] = []
    steps: list[dict] = []

    for _ in range(constraints.max_bands):
        deviation = current - target_db
        working = np.where(band_mask, deviation, 0.0)

        # Przy zakazie podbijania interesują nas wyłącznie nadmiary.
        if constraints.max_boost_db <= 0:
            working = np.where(working > 0, working, 0.0)

        index = int(np.argmax(np.abs(working)))
        peak = float(working[index])
        if abs(peak) < constraints.min_deviation_db:
            break

        gain = -peak
        gain = float(np.clip(gain, -constraints.max_cut_db, constraints.max_boost_db))
        if abs(gain) < 0.1:
            break

        q = _estimate_q(freqs, working, index, constraints)
        band = Band(freq=round(float(freqs[index]), 1), gain=round(gain, 2),
                    q=round(q, 2), type="PK", enabled=True)
        bands.append(band)

        response = np.array(band.response_db(list(freqs), fs))
        current = current + response

        residual = current - target_db
        steps.append({
            "freq": band.freq, "gain": band.gain, "q": band.q,
            "deviation_before": round(peak, 2),
            "residual_max": round(float(np.abs(residual[band_mask]).max()), 2),
        })

    residual = current - target_db
    in_band = residual[band_mask]
    # Cięcia obniżają poziom, więc proponujemy trym, który to nadrabia.
    trim = -float(np.median(in_band)) if in_band.size else 0.0

    return {
        "bands": [
            {"freq": b.freq, "gain": b.gain, "q": b.q, "type": b.type, "enabled": True}
            for b in bands
        ],
        "steps": steps,
        "constraints": constraints.to_dict(),
        "result": {
            "before_db": round(float(np.abs(measured_db[band_mask]
                                            - target_db[band_mask]).max()), 2),
            "after_db": round(float(np.abs(in_band).max()), 2) if in_band.size else 0.0,
            "std_before": round(float((measured_db[band_mask]
                                       - target_db[band_mask]).std()), 2),
            "std_after": round(float(in_band.std()), 2) if in_band.size else 0.0,
            "suggested_trim_db": round(trim, 1),
            "total_boost_db": round(max(0.0, max((b.gain for b in bands), default=0.0)), 2),
        },
        "corrected": [round(float(v), 2) for v in current],
        "target": [round(float(v), 2) for v in target_db],
    }


def simulate(bands: list[dict], freqs: np.ndarray, fs: int = 48000) -> np.ndarray:
    """Sumaryczna odpowiedź zestawu filtrów — do rysunku i kontroli."""
    total = np.zeros_like(np.asarray(freqs, dtype=float))
    for entry in bands:
        if not entry.get("enabled", True):
            continue
        band = Band(freq=float(entry["freq"]), gain=float(entry["gain"]),
                    q=float(entry["q"]), type=str(entry.get("type", "PK")))
        total += np.array(band.response_db(list(freqs), fs))
    return total
