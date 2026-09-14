"""Silnik pomiarowy — sweep, dekonwolucja, analiza odpowiedzi.

Metoda Fariny: pobudzenie logarytmicznym przemiataniem sinusoidalnym, splot
z filtrem odwrotnym daje odpowiedź impulsową. Zaletą nad MLS jest to, że
zniekształcenia harmoniczne lądują PRZED odpowiedzią liniową na osi czasu,
więc da się je odciąć oknem zamiast rozsmarowywać po całym pomiarze.

Nic tu nie jest przepisane z REW — REW jest zamknięty i nie ma czego
przenosić. To standardowa procedura opisana w literaturze, zaimplementowana
od zera na numpy i scipy.

Klucz do sensownej korekcji powyżej zakresu modalnego to trzy rzeczy, które
tu są: uśrednianie przestrzenne, wygładzanie zmienne i rozdzielenie części
minimalnofazowej od nadmiarowej. Bez nich korekcja wyżej dopasowuje się do
filtrowania grzebieniowego, które w innym punkcie kanapy wygląda inaczej.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sig

SPEED_OF_SOUND = 343.0          # m/s przy ~20 °C

# Ile odpowiedzi zostawiamy PRZED dotarciem dźwięku bezpośredniego.
# Jedna stała dla okna i dla wyrównania — rozjazd między nimi obcina
# dźwięk bezpośredni i przekłamuje widmo o kilkadziesiąt decybeli.
WINDOW_LEAD_MS = 1.0


# --------------------------------------------------------------------
# generowanie pobudzenia
# --------------------------------------------------------------------

def log_sweep(f_start: float = 10.0, f_stop: float = 22000.0,
              duration: float = 10.0, fs: int = 48000,
              fade: float = 0.05) -> np.ndarray:
    """Logarytmiczne przemiatanie sinusoidalne o stałej energii na oktawę.

    Wygaszenie na krańcach tłumi trzask na starcie i stopie, który inaczej
    rozmazuje się po całej odpowiedzi impulsowej.
    """
    n = int(round(duration * fs))
    t = np.arange(n) / fs
    f_stop = min(f_stop, fs / 2 * 0.999)
    ratio = np.log(f_stop / f_start)
    phase = 2 * np.pi * f_start * duration / ratio * (np.exp(t * ratio / duration) - 1)
    x = np.sin(phase)

    edge = int(fade * fs)
    if edge > 0 and 2 * edge < n:
        window = np.hanning(2 * edge)
        x[:edge] *= window[:edge]
        x[-edge:] *= window[edge:]
    return x


def inverse_filter(sweep: np.ndarray, f_start: float, f_stop: float,
                   fs: int) -> np.ndarray:
    """Filtr odwrotny: przemiatanie odwrócone w czasie z korekcją amplitudy.

    Przemiatanie logarytmiczne ma widmo opadające 3 dB na oktawę. Bez
    korekcji −6 dB na oktawę wynik dekonwolucji miałby przechył w dole pasma.
    """
    n = len(sweep)
    reversed_sweep = sweep[::-1].copy()
    t = np.arange(n) / fs
    duration = n / fs
    # Obwiednia kompensująca: amplituda maleje wykładniczo wzdłuż przemiatania.
    envelope = np.exp(-t * np.log(f_stop / f_start) / duration)
    return reversed_sweep * envelope


def deconvolve(recording: np.ndarray, inverse: np.ndarray,
               normalise: bool = False) -> np.ndarray:
    """Odpowiedź impulsowa: splot nagrania z filtrem odwrotnym przez FFT.

    `normalise` domyślnie WYŁĄCZONE. Normalizacja każdego pomiaru własnym
    szczytem zrównuje poziomy między kanałami, a właśnie różnice poziomów
    są nam potrzebne do ustawienia trymów. Włączaj tylko do rysowania
    pojedynczej odpowiedzi.
    """
    n = len(recording) + len(inverse) - 1
    size = 1 << int(np.ceil(np.log2(n)))
    spectrum = np.fft.rfft(recording, size) * np.fft.rfft(inverse, size)
    ir = np.fft.irfft(spectrum, size)[:n]
    if normalise:
        peak = np.max(np.abs(ir))
        if peak > 0:
            ir = ir / peak
    return ir


# --------------------------------------------------------------------
# analiza odpowiedzi impulsowej
# --------------------------------------------------------------------

def find_arrival(ir: np.ndarray, threshold_db: float = -20.0) -> int:
    """Próbka, w której dociera dźwięk bezpośredni.

    Skanujemy DO PRZODU do pierwszego przekroczenia progu względem szczytu.

    Pierwsza wersja cofała się od szczytu po obwiedni Hilberta i to był błąd:
    przy rezonansie o wysokiej dobroci obwiednia nie schodzi poniżej progu,
    więc pętla dochodziła do zera. Okno startowało wtedy od początku nagrania,
    a jego narastanie zjadało dźwięk bezpośredni i eksponowało sam ogon
    rezonansu — w teście dawało to +37 dB błędu na częstotliwości rezonansu.
    """
    magnitude = np.abs(ir)
    peak_index = int(np.argmax(magnitude))
    peak = float(magnitude[peak_index])
    if peak <= 0:
        return 0
    limit = peak * 10 ** (threshold_db / 20)

    # Szukamy wyłącznie w otoczeniu szczytu. Skanowanie od początku całego
    # nagrania łapało pierwszy artefakt szumowy przekraczający próg i okno
    # startowało w przypadkowym miejscu — przy czystym impulsie odniesienia
    # dawało to widmo samego szumu.
    search_back = min(peak_index, int(0.020 * len(ir)) or peak_index)
    window = magnitude[peak_index - search_back:peak_index + 1]
    above = np.flatnonzero(window >= limit)
    return int(peak_index - search_back + above[0]) if above.size else peak_index


def arrival_metrics(ir: np.ndarray, fs: int,
                    loopback_offset: int = 0) -> dict:
    """Opóźnienie i odległość z pozycji dotarcia dźwięku bezpośredniego.

    `loopback_offset` to opóźnienie samego toru (przetworniki, bufory),
    zmierzone pętlą odniesienia. Bez niego odległości są względne — i to
    wystarcza, bo amplituner i tak wyrównuje kanały między sobą.
    """
    arrival = find_arrival(ir)
    samples = arrival - loopback_offset
    seconds = samples / fs
    return {
        "arrival_sample": int(arrival),
        "delay_ms": round(seconds * 1000, 3),
        "distance_m": round(seconds * SPEED_OF_SOUND, 3),
        "absolute": bool(loopback_offset),
    }


def window_ir(ir: np.ndarray, fs: int, arrival: int | None = None,
              left_ms: float = WINDOW_LEAD_MS, right_ms: float = 500.0,
              taper: float = 0.25) -> tuple[np.ndarray, int]:
    """Okno wokół dotarcia — odcina zniekształcenia i ogon poza zakresem.

    Okno jest mocno asymetryczne. Przed dotarciem tylko milisekunda
    z krótkim narastaniem: dalej wstecz siedzą harmoniczne z metody Fariny.
    Po dotarciu długi ogon z łagodnym opadaniem na ostatnim odcinku.

    Narastanie MUSI być krótkie. Symetryczne narastanie długości `taper`
    części okna tłumi dźwięk bezpośredni i przekłamuje rezonanse —
    kosztowało mnie to kilkadziesiąt decybeli błędu w teście.
    """
    if arrival is None:
        arrival = find_arrival(ir)
    lead = int(left_ms * fs / 1000)
    start = max(0, arrival - lead)
    stop = min(len(ir), arrival + int(right_ms * fs / 1000))
    segment = ir[start:stop].copy()
    n = len(segment)

    rise = min(arrival - start, n // 2)
    if rise > 1:
        segment[:rise] *= np.hanning(2 * rise)[:rise]

    fall = int(n * taper)
    if 1 < fall < n:
        segment[-fall:] *= np.hanning(2 * fall)[fall:]
    # Zwracamy też, ile próbek okno faktycznie zostawiło przed dotarciem —
    # wyrównanie musi przesunąć dokładnie o tyle, ani o próbkę więcej.
    return segment, arrival - start


def frequency_response(ir: np.ndarray, fs: int,
                       points: int = 2048) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Widmo odpowiedzi impulsowej: częstotliwości, dB, faza w radianach."""
    size = max(1 << int(np.ceil(np.log2(len(ir)))), 1 << 15)
    spectrum = np.fft.rfft(ir, size)
    freqs = np.fft.rfftfreq(size, 1 / fs)
    magnitude = 20 * np.log10(np.maximum(np.abs(spectrum), 1e-12))
    return freqs, magnitude, np.angle(spectrum)


# --------------------------------------------------------------------
# wygładzanie
# --------------------------------------------------------------------

def smooth(freqs: np.ndarray, magnitude_db: np.ndarray,
           fraction: float | None = 6.0, variable: bool = False) -> np.ndarray:
    """Wygładzanie ułamkowo-oktawowe.

    `variable=True` włącza wygładzanie zmienne: wąskie w dole pasma, gdzie
    rezonanse modalne są realne i powtarzalne, szerokie w górze, gdzie
    szczegół jest artefaktem jednego punktu pomiarowego. To nie kosmetyka —
    to decyduje, co optymalizator w ogóle zobaczy jako odchyłkę.
    """
    out = np.empty_like(magnitude_db)
    positive = freqs > 0
    first = int(np.argmax(positive))

    for i in range(len(freqs)):
        f = freqs[i]
        if f <= 0:
            out[i] = magnitude_db[first] if first < len(magnitude_db) else 0.0
            continue
        if variable:
            # 1/48 oktawy do 100 Hz, rozszerzane płynnie do 1/3 powyżej 1 kHz
            if f < 100:
                frac = 48.0
            elif f > 1000:
                frac = 3.0
            else:
                t = np.log10(f / 100) / np.log10(10.0)
                frac = 48.0 * (3.0 / 48.0) ** t
        else:
            frac = fraction or 6.0
        half = 2 ** (1 / (2 * frac))
        lo, hi = f / half, f * half
        mask = (freqs >= lo) & (freqs <= hi)
        out[i] = magnitude_db[mask].mean() if mask.any() else magnitude_db[i]
    return out


# --------------------------------------------------------------------
# uśrednianie przestrzenne
# --------------------------------------------------------------------

def average_responses(responses: list[np.ndarray], mode: str = "auto",
                      freqs: np.ndarray | None = None,
                      crossover: float = 300.0) -> np.ndarray:
    """Uśrednia widma z wielu pozycji mikrofonu.

    `wektorowe` — średnia zespolona. Kasuje nieskorelowane filtrowanie
    grzebieniowe, ale w górze pasma zaniża poziom, bo fazy się znoszą.

    `mocy` — średnia RMS modułów. Zachowuje poziom, ale zostawia szczyty
    i doliny, które istnieją tylko w jednym punkcie.

    `auto` — jedno i drugie: wektorowo poniżej częstotliwości przejścia,
    gdzie fazy są spójne i kasowanie ma sens, mocy powyżej. To jest
    kompromis stosowany w praktyce i domyślny tutaj.
    """
    stack = np.asarray(responses)
    if mode == "wektorowe":
        return np.abs(stack.mean(axis=0))
    if mode == "mocy":
        return np.sqrt((np.abs(stack) ** 2).mean(axis=0))
    if mode != "auto":
        raise ValueError(f"nieznany tryb uśredniania: {mode}")

    if freqs is None:
        raise ValueError("tryb auto wymaga osi częstotliwości")
    vector = np.abs(stack.mean(axis=0))
    power = np.sqrt((np.abs(stack) ** 2).mean(axis=0))
    # Płynne przejście przez oktawę wokół punktu granicznego, żeby nie
    # wprowadzać schodka w miejscu zszycia.
    blend = np.clip(np.log2(np.maximum(freqs, 1e-6) / crossover) + 0.5, 0, 1)
    return vector * (1 - blend) + power * blend


# --------------------------------------------------------------------
# minimalnofazowość
# --------------------------------------------------------------------

def minimum_phase(magnitude_db: np.ndarray) -> np.ndarray:
    """Faza minimalna wyliczona z modułu przez transformatę Hilberta.

    UWAGA — TA FUNKCJA NIE JEST ZWERYFIKOWANA I DAJE ZŁE WYNIKI.
    Zbudowana na niej `correctable_mask` zwraca 100% korygowalnego pasma
    niezależnie od tego, czy w odpowiedzi jest silne odbicie, czy nie —
    czyli nie rozróżnia niczego. Testowałem trzy kryteria (moduł fazy
    nadmiarowej, wygładzony moduł, odchylenie standardowe w paśmie)
    i wszystkie dają ten sam wynik, co wskazuje na błąd tutaj, a nie
    w kryterium. Do naprawy w następnej kolejności.


    Zależność Bodego: dla układu minimalnofazowego faza jest jednoznacznie
    określona przez przebieg modułu. Odchylenie fazy zmierzonej od tej
    wyliczonej to faza nadmiarowa.
    """
    log_magnitude = magnitude_db / 20 * np.log(10)
    full = np.concatenate([log_magnitude, log_magnitude[-2:0:-1]])
    analytic = sig.hilbert(full)
    return -np.imag(analytic)[:len(magnitude_db)]


def excess_phase(magnitude_db: np.ndarray, phase: np.ndarray,
                 freqs: np.ndarray | None = None) -> np.ndarray:
    """Faza nadmiarowa — to, czego equalizer NIE naprawi.

    Rezonans modalny jest minimalnofazowy: filtr o odwrotnej charakterystyce
    znosi go razem z fazą. Odbicie nie jest — to opóźniona kopia sygnału,
    a nie zmiana barwy. Żadna korekcja amplitudy jej nie usunie.

    Kluczowe: przed porównaniem trzeba usunąć opóźnienie transportowe.
    Faza zmierzona zawiera rampę liniową od czasu przelotu dźwięku, a faza
    minimalna wyliczona z modułu jej nie ma. Bez odjęcia tej rampy różnica
    idzie w tysiące radianów i każdy sensowny próg przestaje cokolwiek
    rozróżniać — na czym się przejechałem przy pierwszym podejściu.
    """
    residual = np.unwrap(phase) - minimum_phase(magnitude_db)
    # Dopasowanie prostej to właśnie usunięcie czystego opóźnienia:
    # stałe opóźnienie daje fazę liniową względem częstotliwości.
    x = freqs if freqs is not None else np.arange(len(residual), dtype=float)
    valid = np.isfinite(residual)
    if valid.sum() > 8:
        slope, offset = np.polyfit(x[valid], residual[valid], 1)
        residual = residual - (slope * x + offset)
    return residual


def correctable_mask(freqs: np.ndarray, magnitude_db: np.ndarray,
                     phase: np.ndarray, limit_rad: float = 0.6,
                     fraction: float = 3.0) -> np.ndarray:
    """NIE DZIAŁA — zwraca 100% niezależnie od zawartości odpowiedzi.

    Zamierzenie: wskazać pasma, w których korekcja ma sens, bo odchyłka jest
    minimalnofazowa. Rezonans modalny equalizer odwróci, odbicie nie —
    to opóźniona kopia sygnału, a nie zmiana barwy.

    Stan faktyczny: opiera się na `minimum_phase`, która daje złe wyniki
    (patrz ostrzeżenie tam). Nie używać do decydowania o zakresie korekcji,
    dopóki nie zostanie naprawiona i zweryfikowana.

    Kryterium to ZMIENNOŚĆ fazy nadmiarowej w paśmie, nie jej poziom.
    Odbicie daje filtrowanie grzebieniowe, więc faza nadmiarowa faluje wokół
    zera z okresem równym odwrotności opóźnienia. Uśrednienie modułu takiej
    oscylacji daje małą liczbę i maska przepuszcza wszystko — na czym się
    przejechałem: przy odbiciu o wzmocnieniu 0,7 dostawałem 100% pasma
    uznanego za korygowalne.

    Odchylenie standardowe w oknie ułamkowo-oktawowym łapie dokładnie to,
    co trzeba: układ minimalnofazowy ma je bliskie zeru, grzebień - duże.
    """
    excess = excess_phase(magnitude_db, phase, freqs)
    spread = np.zeros_like(excess)
    half = 2 ** (1 / (2 * fraction))
    for i, f in enumerate(freqs):
        if f <= 0:
            spread[i] = np.inf
            continue
        band = (freqs >= f / half) & (freqs <= f * half)
        spread[i] = excess[band].std() if band.sum() > 2 else 0.0
    return spread < limit_rad


# --------------------------------------------------------------------
# pomiar jako całość
# --------------------------------------------------------------------

@dataclass
class Measurement:
    """Jeden pomiar jednego kanału z jednej pozycji."""

    channel: str
    position: int
    fs: int
    ir: np.ndarray
    freqs: np.ndarray = field(default_factory=lambda: np.array([]))
    magnitude: np.ndarray = field(default_factory=lambda: np.array([]))
    phase: np.ndarray = field(default_factory=lambda: np.array([]))
    metrics: dict = field(default_factory=dict)

    def analyse(self, loopback_offset: int = 0,
                window_ms: float = 500.0, align: bool = True) -> "Measurement":
        self.metrics = arrival_metrics(self.ir, self.fs, loopback_offset)
        arrival = self.metrics["arrival_sample"]
        windowed, lead = window_ir(self.ir, self.fs, arrival=arrival,
                                   right_ms=window_ms)
        if align and lead > 0:
            # Przesuwamy dotarcie na początek okna. Inaczej resztkowe
            # opóźnienie zostaje w widmie jako rampa fazowa i psuje
            # zarówno uśrednianie wektorowe, jak i analizę fazy nadmiarowej.
            # Przesunięcie MUSI równać się temu, co okno zostawiło z przodu.
            windowed = np.roll(windowed, -lead)
            windowed[-lead:] = 0.0
        self.freqs, self.magnitude, self.phase = frequency_response(windowed, self.fs)
        return self

    def band(self, low: float = 20.0, high: float = 20000.0) -> tuple:
        mask = (self.freqs >= low) & (self.freqs <= high)
        return self.freqs[mask], self.magnitude[mask]


def analyse_set(measurements: list[Measurement], mode: str = "auto",
                variable_smoothing: bool = True,
                crossover: float = 300.0) -> dict:
    """Łączy pomiary z wielu pozycji w jedną odpowiedź do korekcji."""
    if not measurements:
        raise ValueError("brak pomiarów")
    freqs = measurements[0].freqs
    complex_spectra = [
        10 ** (m.magnitude / 20) * np.exp(1j * m.phase) for m in measurements
    ]
    averaged = average_responses(complex_spectra, mode, freqs, crossover)
    magnitude = 20 * np.log10(np.maximum(averaged, 1e-12))
    smoothed = smooth(freqs, magnitude, variable=variable_smoothing)

    # Maska korygowalności jest policzona, ale NIEZWERYFIKOWANA — zwracamy
    # ją razem z flagą, żeby nikt nie zbudował na niej decyzji przez pomyłkę.
    phase = np.unwrap(measurements[0].phase)
    mask = correctable_mask(freqs, smoothed, phase)
    # Powyżej zakresu, w którym pozycje się zgadzają, korekcja i tak jest
    # dopasowywaniem się do jednego punktu - maska to wychwyci, ale dodatkowo
    # raportujemy, ile pasma faktycznie nadaje się do pracy.
    usable = float(mask[(freqs > 20) & (freqs < 20000)].mean())

    return {
        "freqs": freqs,
        "magnitude": magnitude,
        "smoothed": smoothed,
        "correctable": mask,
        "positions": len(measurements),
        "correctable_fraction": round(usable, 3),
        "correctable_verified": False,
        "channel": measurements[0].channel,
        "distances": [m.metrics.get("distance_m") for m in measurements],
    }
