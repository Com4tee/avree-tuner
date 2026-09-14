"""Wnioski liczone z pomiaru: punkty podziału i krzywa korekcji Audyssey.

Dwie rzeczy, których nie da się zgadnąć, a da się policzyć.

## Punkt podziału

Częstotliwość podziału powinna wynikać z tego, dokąd sięga głośnik, a nie
z okrągłej liczby. Liczymy ją z jego zmierzonego opadania: szukamy punktu
−3 dB i −6 dB względem poziomu odniesienia w paśmie średnim, a podział
stawiamy z zapasem POWYŻEJ punktu −3 dB. Zapas jest konieczny, bo w okolicy
własnego opadania głośnik ma już duże zniekształcenia i mały zapas wysterowania,
nawet jeśli poziom jeszcze nie spadł.

## Krzywa korekcji Audyssey

Gotowych filtrów nie da się odczytać z procesora — sprawdzone, takiej komendy
nie ma (około 600 przetestowanych nazw, `GET_RESPON` działa tylko w sesji
kalibracji). Ale różnica dwóch pomiarów tego samego kanału, raz z Audyssey
włączonym i raz wyłączonym, JEST tą krzywą — zmierzoną akustycznie.

To jest nawet lepsze niż odczyt filtru: pokazuje, co faktycznie dociera do
ucha, razem z głośnikiem i pomieszczeniem, a nie sam przebieg filtru w DSP.
"""

from __future__ import annotations

import numpy as np

# Wartości, które przyjmuje X3300W — nie ma sensu proponować innych.
CROSSOVER_FREQS = [40, 60, 80, 90, 100, 110, 120, 150, 200, 250]

# O ile powyżej punktu -3 dB stawiamy podział. Mnożnik, nie stała liczba
# herców: głośnik sięgający 40 Hz i taki sięgający 100 Hz potrzebują
# proporcjonalnie różnego zapasu.
CROSSOVER_MARGIN = 1.5


def _reference_level(freqs: np.ndarray, db: np.ndarray,
                     band: tuple[float, float] = (200.0, 800.0)) -> float:
    """Poziom odniesienia ze środka pasma, gdzie głośnik jest sobą."""
    mask = (freqs >= band[0]) & (freqs <= band[1])
    return float(np.median(db[mask])) if mask.any() else float(np.median(db))


def rolloff_point(freqs: np.ndarray, db: np.ndarray, drop_db: float = 3.0,
                  reference: float | None = None) -> float | None:
    """Częstotliwość, poniżej której poziom spada o `drop_db`.

    Idziemy OD GÓRY w dół i bierzemy pierwsze przejście przez próg. Szukanie
    od dołu trafiałoby w przypadkowe minimum modalne — w pokoju poniżej
    100 Hz takich dziur jest kilka i żadna nie jest granicą głośnika.
    """
    freqs = np.asarray(freqs, dtype=float)
    db = np.asarray(db, dtype=float)
    ref = _reference_level(freqs, db) if reference is None else reference
    target = ref - drop_db

    band = np.where(freqs <= 800.0)[0]
    if band.size < 3:
        return None

    # Szukamy przejścia przez próg: punkt wyżej jest jeszcze nad progiem,
    # punkt niżej już pod nim.
    for i in range(band[-1], band[0], -1):
        below, above = db[i - 1], db[i]
        if below <= target < above:
            f_below, f_above = freqs[i - 1], freqs[i]
            if above == below:
                return float(f_below)
            t = (target - below) / (above - below)
            return float(10 ** (np.log10(f_below)
                                + t * (np.log10(f_above) - np.log10(f_below))))
    return None


def crossover_advice(freqs, db, allowed: list[int] | None = None) -> dict:
    """Proponowany punkt podziału dla zmierzonego kanału."""
    allowed = allowed or CROSSOVER_FREQS
    freqs = np.asarray(freqs, dtype=float)
    db = np.asarray(db, dtype=float)
    ref = _reference_level(freqs, db)

    f3 = rolloff_point(freqs, db, 3.0, ref)
    f6 = rolloff_point(freqs, db, 6.0, ref)
    f10 = rolloff_point(freqs, db, 10.0, ref)

    if f3 is None:
        return {
            "ready": False,
            "note": ("nie znalazłem opadania −3 dB poniżej 800 Hz — "
                     "kanał gra pełnym pasmem albo pomiar nie sięga dość nisko"),
            "reference_db": round(ref, 2),
            "f3_hz": None, "f6_hz": None,
        }

    wanted = f3 * CROSSOVER_MARGIN
    higher = [v for v in allowed if v >= wanted]
    suggested = higher[0] if higher else allowed[-1]

    return {
        "ready": True,
        "reference_db": round(ref, 2),
        "f3_hz": round(f3, 1),
        "f6_hz": round(f6, 1) if f6 else None,
        "f10_hz": round(f10, 1) if f10 else None,
        "wanted_hz": round(wanted, 1),
        "suggested_hz": suggested,
        "margin": CROSSOVER_MARGIN,
        "note": (f"−3 dB przy {f3:.0f} Hz; z zapasem ×{CROSSOVER_MARGIN} wypada "
                 f"{wanted:.0f} Hz, najbliższa dostępna w górę to {suggested} Hz"),
    }


def correction_curve(freqs, db_on, db_off, align_band=(200.0, 500.0)) -> dict:
    """Krzywa korekcji jako różnica pomiarów Audyssey ON i OFF.

    Oba pomiary wyrównujemy poziomem w wybranym paśmie, bo Audyssey zmienia
    też trym kanału. Bez wyrównania cała krzywa byłaby przesunięta o stałą
    i wyglądała na podbicie albo obcięcie całego pasma.
    """
    freqs = np.asarray(freqs, dtype=float)
    on = np.asarray(db_on, dtype=float)
    off = np.asarray(db_off, dtype=float)
    if on.shape != off.shape or on.shape != freqs.shape:
        raise ValueError("pomiary ON i OFF muszą być na tej samej siatce")

    mask = (freqs >= align_band[0]) & (freqs <= align_band[1])
    offset = (float(np.median(on[mask]) - np.median(off[mask]))
              if mask.any() else 0.0)
    delta = on - off - offset

    def band_mean(lo, hi):
        m = (freqs >= lo) & (freqs < hi)
        return round(float(delta[m].mean()), 2) if m.any() else None

    bands = {
        "20–60 Hz": band_mean(20, 60),
        "60–200 Hz": band_mean(60, 200),
        "200–800 Hz": band_mean(200, 800),
        "800–2k": band_mean(800, 2000),
        "2k–6k": band_mean(2000, 6000),
        "6k–12k": band_mean(6000, 12000),
        "12k–20k": band_mean(12000, 20000),
    }

    treble = (freqs >= 4000) & (freqs <= 16000)
    treble_mean = float(delta[treble].mean()) if treble.any() else 0.0
    treble_max = float(delta[treble].max()) if treble.any() else 0.0

    # Gdzie korekcja podbija najmocniej — to jest odpowiedź na pytanie
    # "skąd się wzięła ta górka".
    peak_index = int(np.argmax(delta)) if delta.size else 0

    return {
        "freqs": [round(float(f), 2) for f in freqs],
        "delta_db": [round(float(v), 2) for v in delta],
        "level_offset_db": round(offset, 2),
        "bands": bands,
        "treble_mean_db": round(treble_mean, 2),
        "treble_max_db": round(treble_max, 2),
        "max_boost_db": round(float(delta.max()), 2),
        "max_boost_hz": round(float(freqs[peak_index]), 1),
        "max_cut_db": round(float(delta.min()), 2),
        "max_cut_hz": round(float(freqs[int(np.argmin(delta))]), 1),
        "verdict": _verdict(treble_mean, treble_max),
    }


def _verdict(treble_mean: float, treble_max: float) -> str:
    """Krótka ocena tego, co korekcja robi z górą pasma."""
    if treble_mean >= 3.0:
        return (f"Audyssey podnosi górę pasma średnio o {treble_mean:+.1f} dB "
                f"(szczyt {treble_max:+.1f} dB). To tłumaczy jasne brzmienie "
                "i wcześniejsze wchodzenie limiterów w kolumnach.")
    if treble_mean >= 1.0:
        return (f"Umiarkowane podbicie góry, średnio {treble_mean:+.1f} dB. "
                "Słyszalne, ale to raczej nie jedyna przyczyna.")
    if treble_mean <= -1.0:
        return (f"Audyssey ŚCISZA górę o {treble_mean:+.1f} dB — jasność "
                "nie bierze się z korekcji, szukaj w trybie dźwięku albo "
                "w ustawieniu samych kolumn.")
    return (f"Góra pasma praktycznie nietknięta ({treble_mean:+.1f} dB). "
            "Przyczyna jasnego brzmienia leży poza korekcją MultEQ.")
