"""Tabele komend protokołu Denon/Marantz.

Źródło: oficjalne PDF-y "DENON AVR control protocol" + weryfikacja
empiryczna na AVR-X3300W. Komendy oznaczone UNVERIFIED nie zostały
jeszcze potwierdzone na tym modelu - probe.py je odsiewa.
"""

from __future__ import annotations

# --- zapytania o stan podstawowy -------------------------------------
BASIC_QUERIES = [
    "PW?",          # zasilanie (PWON / PWSTANDBY)
    "ZM?",          # strefa główna ON/OFF
    "MV?",          # głośność główna + MVMAX
    "MU?",          # wyciszenie
    "SI?",          # źródło wejściowe
    "MS?",          # tryb dźwięku / surround
    "SD?",          # tryb wejścia cyfrowego
    "DC?",          # digital input mode
    "SV?",          # video select
    "SLP?",         # sleep timer
]

# --- Audyssey i korekcja ---------------------------------------------
# To jest serce projektu - wszystko, co da się odczytać o stanie korekcji.
AUDYSSEY_QUERIES = [
    "PSMULTEQ: ?",  # AUDYSSEY / BYP.LR / FLAT / MANUAL / OFF
    "PSDYNEQ ?",    # Dynamic EQ ON/OFF   <- główny podejrzany o podbitą górę
    "PSDYNVOL ?",   # Dynamic Volume OFF/LIT/MED/HEV
    "PSREFLEV ?",   # Reference Level Offset 0/5/10/15 dB
    "PSLFC ?",      # Low Frequency Containment
    "PSCNTAMT ?",   # Containment Amount 1-7
    "PSBAS ?",      # ton. bas
    "PSTRE ?",      # ton. sopran
    "PSTONECTRL ?", # tone control ON/OFF
    "PSDRC ?",      # Dynamic Range Compression
    "PSLFE ?",      # poziom LFE
    "PSDIL ?",      # Dialog Level
    "PSSWL ?",      # poziom subwoofera
]

# --- konfiguracja głośników (to, co ustawiła autokalibracja) ----------
SPEAKER_QUERIES = [
    "SSLEV ?",      # poziomy wszystkich kanałów
    "SSSPC ?",      # rozmiary kolumn (SMA/LAR/NON)
    "SSFRQ ?",      # zwrotnice per kanał
    "SSSPCFRO ?",   # front speaker layout
    "SSPAAMOD ?",   # amp assign mode
    "SSAST ?",      # auto standby
]

# --- informacje o sygnale wejściowym ---------------------------------
SIGNAL_QUERIES = [
    "SSINFAISSIG ?",  # format sygnału (analog/PCM/DD/DTS...)
    "SSINFAISFSV ?",  # częstotliwość próbkowania
    "SSINFAISFIL ?",  # ?
]

# --- możliwości urządzenia -------------------------------------------
# SSSOD zwraca listę trybów dźwięku, które ten egzemplarz obsługuje
# wraz z flagą dostępności - kluczowe dla "pokaż mi, co hardware potrafi".
CAPABILITY_QUERIES = [
    "SSSOD ?",      # dostępne tryby surround
    "SSSMG ?",      # kategoria trybu (MOVIE/MUSIC/GAME)
    "SSFUN ?",      # lista i nazwy źródeł
    "SSVCTZMA ?",   # konfiguracja stref
    "SSHOSIFP ?",   # ?
    "OPSTS ?",      # status opcji
    "SYMO ?",       # model
    "VIALL ?",      # ustawienia video
]

ALL_QUERIES = (
    BASIC_QUERIES
    + AUDYSSEY_QUERIES
    + SPEAKER_QUERIES
    + SIGNAL_QUERIES
    + CAPABILITY_QUERIES
)

QUERY_GROUPS = {
    "basic": BASIC_QUERIES,
    "audyssey": AUDYSSEY_QUERIES,
    "speakers": SPEAKER_QUERIES,
    "signal": SIGNAL_QUERIES,
    "capabilities": CAPABILITY_QUERIES,
}

# --- setery, których będzie używać GUI -------------------------------
MULTEQ_MODES = {
    "AUDYSSEY": "Audyssey (Reference)",
    "BYP.LR":   "Bypass L/R",
    "FLAT":     "Flat",
    "MANUAL":   "Manual",
    "OFF":      "Wyłączony",
}

DYNVOL_MODES = {"OFF": "Wyłączony", "LIT": "Light", "MED": "Medium", "HEV": "Heavy"}

REFLEV_OFFSETS = {"0": "0 dB", "5": "5 dB", "10": "10 dB", "15": "15 dB"}


def set_multeq(mode: str) -> str:
    return f"PSMULTEQ:{mode}"


def set_dyneq(on: bool) -> str:
    return f"PSDYNEQ {'ON' if on else 'OFF'}"


def set_dynvol(mode: str) -> str:
    return f"PSDYNVOL {mode}"


def set_reflev(offset: str) -> str:
    return f"PSREFLEV {offset}"


def set_surround(mode: str) -> str:
    return f"MS{mode}"
