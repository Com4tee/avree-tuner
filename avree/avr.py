"""Model stanu amplitunera i fasada sterowania.

Jedno trwałe połączenie telnet trzyma stan aktualny: amplituner sam wypycha
każdą zmianę (pilot, pokrętło, aplikacja Denona), więc nie odpytujemy go
w kółko - słuchamy i parsujemy.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .telnet import DenonTelnet, DenonTelnetError

# Skala głośności Denona: wyświetlacz 0..98, gdzie 80 = 0 dB odniesienia.
# MV05 -> 5.0 na wyświetlaczu -> -75.0 dB.  MV505 -> 50.5 -> -29.5 dB.
VOLUME_REFERENCE = 80.0

MULTEQ_LABELS = {
    "AUDYSSEY": "Reference",
    "BYP.LR": "L/R Bypass",
    "FLAT": "Flat",
    "MANUAL": "Manual",
    "OFF": "Wyłączony",
}

DYNVOL_LABELS = {"OFF": "Wyłączony", "LIT": "Light", "MED": "Medium", "HEV": "Heavy"}

SPEAKER_POSITIONS = {
    "FRO": "Front L/R", "CEN": "Center", "SUA": "Surround L/R",
    "SBK": "Surround Back", "FRH": "Front Height", "TFR": "Top Front",
    "TPM": "Top Middle", "FRD": "Front Dolby", "SUD": "Surround Dolby",
    "SWF": "Subwoofer",
}

CHANNEL_LABELS = {
    "FL": "Front L", "FR": "Front R", "C": "Center",
    "SL": "Surround L", "SR": "Surround R",
    "SBL": "Surr. Back L", "SBR": "Surr. Back R", "SB": "Surround Back",
    "SW": "Subwoofer 1", "SW2": "Subwoofer 2",
}

# Tryby dźwięku, kategorie i opisy funkcji siedzą w modes.py - to wiedza
# o urządzeniu (ustalona pomiarowo na egzemplarzu), nie o protokole.
from .modes import MODE_CATEGORIES, SURROUND_MODES, TIPS  # noqa: E402,F401

# Rozmiary głośników i dopuszczalne zwrotnice - do menu konfiguracji.
SPEAKER_SIZES = [("LAR", "Large"), ("SMA", "Small"), ("NON", "Brak")]

CROSSOVER_FREQS = [40, 60, 80, 90, 100, 110, 120, 150, 200, 250]

# Źródła, które przyjmują przypisanie wejścia. Kolejność jak w menu.
INPUT_SOURCES = ["DVD", "BD", "TV", "SAT/CBL", "MPLAY", "GAME",
                 "AUX1", "AUX2", "CD"]

# Rodziny przypisań wejść - wszystkie odkryte przemiatem przestrzeni nazw,
# żadna nie jest w oficjalnej dokumentacji protokołu.
INPUT_ASSIGN = {
    "SSHDM": {"label": "HDMI", "values": ["OFF", "HD1", "HD2", "HD3", "HD4",
                                          "HD5", "HD6", "HD7", "HD8", "FRO"]},
    "SSDIN": {"label": "Cyfrowe", "values": ["OFF", "COA1", "COA2", "OPT1",
                                             "OPT2", "OPT3"]},
    "SSANA": {"label": "Analogowe", "values": ["OFF", "AN1", "AN2", "AN3",
                                               "AN4", "AN5", "AN6", "AN7"]},
    "SSVDO": {"label": "Wideo", "values": ["OFF", "VD1", "VD2", "VD3"]},
    "SSCMP": {"label": "Component", "values": ["OFF", "CP1", "CP2", "CP3"]},
}

# Zakres i format odległości. Krok bierzemy z urządzenia (SSSDESTP).
DISTANCE_CHANNELS = ["FL", "FR", "C", "SL", "SR", "SW", "SW2",
                     "SBL", "SBR", "SB", "FHL", "FHR"]

# Klawisze nawigacji menu ekranowego - odpowiedniki strzałek na pilocie.
OSD_KEYS = {
    "menu_on": "MNMEN ON", "menu_off": "MNMEN OFF",
    "up": "MNCUP", "down": "MNCDN", "left": "MNCLT", "right": "MNCRT",
    "enter": "MNENT", "back": "MNRTN",
    "info": "MNINF", "options": "MNOPT",
}

# Regulacje barwy i dynamiki. Każda pozycja: komenda, zakres, opis.
# Skala Denona dla wartości liczbowych: 50 = 0, krok 0.5 przy zapisie
# trzycyfrowym - ta sama co przy poziomach kanałów.
TONE_CONTROLS = {
    # `requires` - przełącznik, bez którego amplituner IGNORUJE komendę.
    # Ustalone pomiarowo: przy PSTONE CTRL OFF komenda PSBAS nie daje echa
    # ani skutku. To jest dokładnie to zachowanie, które w aplikacji Denona
    # wygląda jak zepsuty suwak.
    "bass":      {"cmd": "PSBAS",  "min": -6,  "max": 6,  "step": 0.5,
                  "label": "Bas", "unit": "dB", "scale": "level",
                  "requires": "tone_control"},
    "treble":    {"cmd": "PSTRE",  "min": -6,  "max": 6,  "step": 0.5,
                  "label": "Sopran", "unit": "dB", "scale": "level",
                  "requires": "tone_control"},
    "dialog":    {"cmd": "PSDIL",  "min": -12, "max": 12, "step": 0.5,
                  "label": "Poziom dialogu", "unit": "dB", "scale": "level"},
    "subwoofer": {"cmd": "PSSWL",  "min": -12, "max": 12, "step": 0.5,
                  "label": "Poziom subwoofera", "unit": "dB", "scale": "level"},
    "lfe":       {"cmd": "PSLFE",  "min": -10, "max": 0,  "step": 1,
                  "label": "Poziom LFE", "unit": "dB", "scale": "lfe"},
    "dialog_ctl":{"cmd": "PSDIC",  "min": 0,   "max": 6,  "step": 1,
                  "label": "Dialog Control", "unit": "", "scale": "int"},
    "effect":    {"cmd": "PSEFF",  "min": 1,   "max": 15, "step": 1,
                  "label": "Poziom efektu", "unit": "", "scale": "int"},
}

# Przełączniki dwustanowe i wyliczeniowe.
TONE_SWITCHES = {
    "tone_control": {"cmd": "PSTONE CTRL", "values": ["ON", "OFF"],
                     "label": "Regulacja barwy"},
    # Cinema EQ jest ignorowane w trybie Stereo - sprawdzone.
    "cinema_eq":    {"cmd": "PSCINEMA EQ.", "values": ["ON", "OFF"],
                     "label": "Cinema EQ",
                     "note": "niedostępne w trybie Stereo i Direct"},
    "loudness":     {"cmd": "PSLOM", "values": ["ON", "OFF"],
                     "label": "Loudness Management"},
    "neural":       {"cmd": "PSNEURAL", "values": ["ON", "OFF"],
                     "label": "DTS Neural:X"},
    "drc":          {"cmd": "PSDRC", "values": ["AUTO", "LOW", "MID", "HI", "OFF"],
                     "label": "Kompresja dynamiki"},
    "room_size":    {"cmd": "PSRSZ", "values": ["S", "MS", "M", "ML", "L"],
                     "label": "Rozmiar pomieszczenia"},
}

# Kod z SSINFAISSIG -> co faktycznie przyszło na wejście.
INPUT_SIGNAL = {
    "01": "Analogowy", "02": "PCM", "03": "Dolby Digital", "04": "DTS",
    "05": "DSD", "06": "Dolby TrueHD", "07": "DTS-HD", "08": "Dolby Atmos",
    "09": "DTS:X", "12": "brak sygnału / inne",
}


def display_to_db(display: float) -> float:
    return display - VOLUME_REFERENCE


def db_to_display(db: float) -> float:
    return db + VOLUME_REFERENCE


def parse_mv(digits: str) -> float | None:
    """'05' -> 5.0,  '505' -> 50.5,  '80' -> 80.0"""
    digits = digits.strip()
    if not digits.isdigit():
        return None
    if len(digits) == 3:
        return int(digits[:2]) + int(digits[2]) / 10.0
    if len(digits) in (1, 2):
        return float(int(digits))
    return None


def format_mv(display: float) -> str:
    """50.5 -> '505',  42.0 -> '42'  (amplituner wymaga takiego zapisu)"""
    whole = int(display)
    half = round((display - whole) * 10)
    if half >= 5:
        return f"{whole:02d}5"
    return f"{whole:02d}"


def parse_level(digits: str) -> float | None:
    """Poziom kanału: 50 = 0.0 dB, 385..620 w krokach 0.5 dB."""
    v = parse_mv(digits)
    return None if v is None else round(v - 50.0, 1)


class Avr:
    """Stan amplitunera + wysyłanie komend. Bezpieczne dla wielu wątków."""

    def __init__(self, host: str) -> None:
        self.host = host
        self._telnet: DenonTelnet | None = None
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {
            "connected": False,
            "error": None,
            "power": None, "zone": None,
            "volume_display": None, "volume_db": None, "volume_max": None,
            "mute": None, "source": None, "surround": None,
            "input_mode": None, "input_signal": None, "sample_rate": None,
            "multeq": None, "dynamic_eq": None, "dynamic_volume": None,
            "reference_level": None, "graphic_eq": None, "cinema_eq": None,
            "loudness_management": None, "dialog_control": None,
            "room_size": None, "neural": None, "effect_level": None,
            "bass": None, "treble": None, "dialog": None, "lfe": None,
            "tone_control": None, "drc_value": None,
            "channel_levels": {}, "setup_levels": {}, "sub_levels": {},
            "speakers": {}, "crossovers": {}, "distances": {},
            "distances_dolby": {}, "inputs": {}, "source_levels": {},
            "lipsync": {}, "osd": {},
            "distance_step_cm": 1,
            "subwoofer_mode": None, "lfe_lowpass": None, "crossover_mode": None,
            "amp_assign": None,
            "device": {}, "sources": [],
            "updated": 0.0,
        }
        self._log: list[dict[str, Any]] = []
        # Sufit głośności - twarda blokada po stronie serwera.
        self.volume_ceiling_db: float | None = -28.0
        self._stop = threading.Event()
        self._keeper = threading.Thread(target=self._keep_alive, daemon=True)

    # ---- połączenie --------------------------------------------------

    def start(self) -> None:
        self._keeper.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            if self._telnet:
                self._telnet.close()
                self._telnet = None

    def reconnect(self, host: str) -> None:
        """Przepina się na inny adres bez restartu aplikacji.

        Wątek podtrzymujący sam nawiąże połączenie od nowa, gdy zobaczy,
        że gniazdo zniknęło.
        """
        with self._lock:
            if self._telnet:
                self._telnet.close()
                self._telnet = None
            self.host = host
            self._state["connected"] = False
            self._state["error"] = None
            # Stan poprzedniego urządzenia byłby mylący przy nowym adresie.
            for key in ("power", "zone", "volume_db", "volume_display", "mute",
                        "source", "surround", "multeq", "dynamic_eq",
                        "dynamic_volume", "reference_level", "subwoofer_mode",
                        "lfe_lowpass", "crossover_mode", "amp_assign"):
                self._state[key] = None
            for key in ("channel_levels", "setup_levels", "sub_levels",
                        "speakers", "crossovers", "distances",
                        "distances_dolby", "inputs", "source_levels",
                        "lipsync", "osd", "device"):
                self._state[key] = {}
            self._state["sources"] = []

    def _keep_alive(self) -> None:
        """Łączy, a po zerwaniu połączenia próbuje ponownie co 5 s."""
        while not self._stop.is_set():
            if self._telnet is None:
                try:
                    t = DenonTelnet(self.host)
                    t.on_event(self._ingest)
                    t.connect()
                    with self._lock:
                        self._telnet = t
                        self._state["connected"] = True
                        self._state["error"] = None
                    time.sleep(0.4)
                    self.refresh_all()
                except DenonTelnetError as e:
                    with self._lock:
                        self._state["connected"] = False
                        self._state["error"] = str(e)
                    self._stop.wait(5.0)
                    continue
            self._stop.wait(2.0)

    # ---- parsowanie zdarzeń ------------------------------------------

    def _ingest(self, line: str) -> None:
        with self._lock:
            self._log.append({"t": time.time(), "dir": "rx", "line": line})
            del self._log[:-400]
            self._apply(line, self._state)
            self._state["updated"] = time.time()

    @staticmethod
    def _apply(line: str, s: dict[str, Any]) -> None:
        # --- zasilanie i strefa
        if line in ("PWON", "PWSTANDBY"):
            s["power"] = "on" if line == "PWON" else "standby"
        elif line in ("ZMON", "ZMOFF"):
            s["zone"] = line[2:].lower()
        elif line in ("MUON", "MUOFF"):
            s["mute"] = line == "MUON"

        # --- głośność (MVMAX musi iść przed MV, bo MV jest prefiksem)
        elif line.startswith("MVMAX "):
            v = parse_mv(line[6:])
            if v is not None:
                s["volume_max"] = v
        elif line.startswith("MV"):
            v = parse_mv(line[2:])
            if v is not None:
                s["volume_display"] = v
                s["volume_db"] = round(display_to_db(v), 1)

        # --- źródło i tryb
        elif line.startswith("SI"):
            s["source"] = line[2:]
        elif line.startswith("MS"):
            s["surround"] = line[2:].strip()
        elif line.startswith("SD"):
            s["input_mode"] = line[2:]

        # --- Audyssey
        elif line.startswith("PSMULTEQ:"):
            s["multeq"] = line.split(":", 1)[1].strip()
        elif line.startswith("PSDYNEQ "):
            s["dynamic_eq"] = line[8:].strip() == "ON"
        elif line.startswith("PSDYNVOL "):
            s["dynamic_volume"] = line[9:].strip()
        elif line.startswith("PSREFLEV "):
            s["reference_level"] = line[9:].strip()
        elif line.startswith("PSGEQ "):
            s["graphic_eq"] = line[6:].strip() == "ON"
        elif line.startswith("PSCINEMA EQ."):
            s["cinema_eq"] = line[12:].strip() == "ON"
        elif line.startswith("PSLOM "):
            s["loudness_management"] = line[6:].strip() == "ON"
        elif line.startswith("PSDIC "):
            s["dialog_control"] = line[6:].strip()
        elif line.startswith("PSRSZ "):
            s["room_size"] = line[6:].strip()
        elif line.startswith("PSNEURAL "):
            s["neural"] = line[9:].strip() == "ON"
        elif line.startswith("PSEFF "):
            s["effect_level"] = line[6:].strip()
        elif line.startswith("PSBAS "):
            s["bass"] = parse_level(line[6:])
        elif line.startswith("PSTRE "):
            s["treble"] = parse_level(line[6:])
        elif line.startswith("PSDIL "):
            v = parse_level(line[6:])
            if v is not None:
                s["dialog"] = v
        elif line.startswith("PSLFE "):
            raw = line[6:].strip()
            s["lfe"] = -int(raw) if raw.isdigit() else None
        elif line.startswith("PSTONE CTRL "):
            s["tone_control"] = line[12:].strip() == "ON"
        elif line.startswith("PSDRC "):
            # PSDRC niesie wartość wyliczeniową (AUTO/LOW/MID/HI/OFF),
            # a nie przełącznik - trzymamy ją osobno od starego pola.
            s["drc_value"] = line[6:].strip()

        # --- poziomy kanałów (CV = bieżące, SSLEV = z konfiguracji)
        elif line.startswith("CV") and line != "CVEND":
            parts = line[2:].split()
            if len(parts) == 2:
                lvl = parse_level(parts[1])
                if lvl is not None:
                    s["channel_levels"][parts[0]] = lvl
        elif line.startswith("PSSWL"):
            rest = line[5:]
            ch = "SW2" if rest.startswith("2") else "SW"
            value = rest[1:].strip() if rest.startswith("2") else rest.strip()
            # 'PSSWL OFF' to flaga regulacji, nie poziom - bierzemy tylko liczby
            lvl = parse_level(value) if value.isdigit() else None
            if lvl is not None:
                s["sub_levels"][ch] = lvl
        elif line.startswith("SSLEV"):
            rest = line[5:]
            ch, _, val = rest.partition(" ")
            lvl = parse_level(val)
            if ch and lvl is not None:
                s["setup_levels"][ch] = lvl

        # --- konfiguracja głośników
        elif line.startswith("SSSPC"):
            pos, _, val = line[5:].partition(" ")
            if pos and val:
                s["speakers"][pos] = val.strip()
        elif line.startswith("SSCFR"):
            pos, _, val = line[5:].partition(" ")
            if pos == "" and val:                    # 'SSCFR IDV'
                s["crossover_mode"] = val.strip()
            elif pos == "ALL":
                s["crossovers"]["ALL"] = val.strip()
            elif pos and val.strip().isdigit():
                s["crossovers"][pos] = int(val)
        # --- odległości głośników (SSSDE, w centymetrach)
        #
        # Uwaga historyczna: przez dłuższy czas w dokumentacji stało, że
        # odległości są po telnecie niedostępne. To była pomyłka — sprawdzony
        # był mnemonik SSDST zamiast SSSDE. Odczyt i ZAPIS działają, krok 1 cm.
        elif line.startswith("SSSDE"):
            ch, _, val = line[5:].partition(" ")
            val = val.strip().rstrip("M")
            if ch == "STP" and val.isdigit():
                s["distance_step_cm"] = int(val)
            elif ch and val.isdigit():
                s["distances"][ch] = int(val)

        # --- rodziny odkryte przemiatem przestrzeni nazw (SSHDM, SSANA...)
        #
        # Wszystkie mają ten sam kształt: PREFIKS + nazwa źródła + wartość.
        # Nazwa źródła bywa ze znakiem ukośnika (SAT/CBL), więc dzielimy
        # po OSTATNIej spacji, nie po pierwszej.
        elif line[:5] in INPUT_ASSIGN:
            family, rest = line[:5], line[5:]
            source, _, value = rest.rpartition(" ")
            if source and value:
                s["inputs"].setdefault(family, {})[source] = value.strip()
        elif line.startswith("SSSLD"):
            source, _, value = line[5:].rpartition(" ")
            if source and value.strip().isdigit():
                s["source_levels"][source] = int(value)
        elif line.startswith("SSALS"):
            key, _, value = line[5:].partition(" ")
            if key:
                s["lipsync"][key] = value.strip()
        elif line.startswith("SSOSD"):
            key, _, value = line[5:].partition(" ")
            if key:
                s["osd"][key] = value.strip()
        elif line.startswith("SSDSS"):
            key, _, value = line[5:].partition(" ")
            value = value.strip().rstrip("M")
            if key and value.isdigit():
                s["distances_dolby"][key] = int(value)

        elif line.startswith("SSSWM "):
            s["subwoofer_mode"] = line[6:].strip()
        elif line.startswith("SSLFL "):
            s["lfe_lowpass"] = int(line[6:]) if line[6:].strip().isdigit() else line[6:]
        elif line.startswith("SSPAAMOD "):
            s["amp_assign"] = line[9:].strip()

        # --- sygnał wejściowy
        elif line.startswith("SSINFAISSIG "):
            code = line[12:].strip()
            s["input_signal"] = INPUT_SIGNAL.get(code, f"kod {code}")
        elif line.startswith("SSINFAISFSV "):
            s["sample_rate"] = line[12:].strip()

        # --- identyfikacja urządzenia
        elif line.startswith("VIALL"):
            body = line[5:]
            if ":" in body:
                k, _, v = body.partition(":")
                s["device"][k] = v.strip()
            elif body.startswith("S/N"):
                # 'VIALLS/N.6083603015'
                s["device"]["SERIAL"] = body.lstrip("S/N.").strip()
            elif " " in body.strip():
                # Model z rewizją: 'VIALLAVRX3300W E2'. Pozostałe linie VIALL
                # mają dwukropek albo są numerem seryjnym, więc spacja
                # jednoznacznie wskazuje tę jedną.
                model, _, revision = body.strip().partition(" ")
                s["device"]["MODEL"] = model
                s["device"]["REVISION"] = revision.strip()
        elif line.startswith("SSINFFRMAVR "):
            s["device"]["FIRMWARE"] = line[12:].strip()
        elif line.startswith("SSINFFRMDTS "):
            s["device"]["DTS"] = line[12:].strip()
        elif line.startswith("NSFRN "):
            s["device"]["NAME"] = line[6:].strip()

        # --- lista dostępnych źródeł
        elif line.startswith("SSFUN"):
            code, _, label = line[5:].partition(" ")
            if code:
                entry = next((x for x in s["sources"] if x["code"] == code), None)
                if entry:
                    entry["label"] = label.strip() or code
                else:
                    s["sources"].append({"code": code, "label": label.strip() or code,
                                         "enabled": True})
        elif line.startswith("SSSOD"):
            code, _, flag = line[5:].partition(" ")
            if code:
                entry = next((x for x in s["sources"] if x["code"] == code), None)
                if entry is None:
                    entry = {"code": code, "label": code, "enabled": True}
                    s["sources"].append(entry)
                entry["enabled"] = flag.strip() == "USE"

    # ---- odczyt ------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            s = dict(self._state)
            s["channel_levels"] = dict(self._state["channel_levels"])
            s["setup_levels"] = dict(self._state["setup_levels"])
            s["sub_levels"] = dict(self._state["sub_levels"])
            s["speakers"] = dict(self._state["speakers"])
            s["crossovers"] = dict(self._state["crossovers"])
            s["distances"] = dict(self._state["distances"])
            for k in ("distances_dolby", "inputs", "source_levels",
                      "lipsync", "osd"):
                s[k] = {a: dict(b) if isinstance(b, dict) else b
                        for a, b in self._state[k].items()}
            s["device"] = dict(self._state["device"])
            s["sources"] = [dict(x) for x in self._state["sources"]]
            s["host"] = self.host
            s["volume_ceiling_db"] = self.volume_ceiling_db
            s["multeq_label"] = MULTEQ_LABELS.get(s.get("multeq") or "", s.get("multeq"))
            s["dynamic_volume_label"] = DYNVOL_LABELS.get(
                s.get("dynamic_volume") or "", s.get("dynamic_volume"))
            return s

    def log_tail(self, n: int = 120) -> list[dict[str, Any]]:
        with self._lock:
            return self._log[-n:]

    # ---- wysyłanie ---------------------------------------------------

    def ask(self, command: str, settle: float = 1.4) -> list[str]:
        """Wysyła zapytanie i zwraca odpowiedzi, które przyszły po nim.

        Potrzebne do zrzutu nastaw: idzie po istniejącym połączeniu, więc
        nie otwiera nowych gniazd i nie odpytuje aplikacji przez jej własne
        API. Zwraca wyłącznie linie przychodzące, bez echa własnej komendy.
        """
        with self._lock:
            t = self._telnet
        if t is None:
            raise DenonTelnetError("brak połączenia z amplitunerem")
        return [l for l in t.ask(command, settle=settle)
                if l.strip() != command.strip()]

    def send(self, command: str) -> None:
        with self._lock:
            t = self._telnet
            self._log.append({"t": time.time(), "dir": "tx", "line": command})
            del self._log[:-400]
        if t is None:
            raise DenonTelnetError("brak połączenia z amplitunerem")
        t.send(command)

    def refresh_all(self) -> None:
        """Pełne odpytanie - po połączeniu i na żądanie z interfejsu."""
        for q in ("PW?", "ZM?", "MV?", "MU?", "SI?", "MS?", "SD?",
                  "PSMULTEQ: ?", "PSDYNEQ ?", "PSDYNVOL ?", "PSREFLEV ?",
                  "PSGEQ ?", "PSCINEMA EQ. ?", "PSLOM ?", "PSDIC ?",
                  "PSRSZ ?", "PSNEURAL ?", "PSEFF ?", "PSDRC ?",
                  "CV?", "PSSWL ?", "SSLEV ?", "SSSDE ?", "SSDSS ?", "SSSPC ?",
                  "SSHDM ?", "SSDIN ?", "SSANA ?", "SSVDO ?", "SSCMP ?",
                  "SSSLD ?", "SSALS ?", "SSOSD ?", "SSCFR ?", "SSSWM ?", "SSLFL ?",
                  "SSPAA ?", "SSINFAISSIG ?", "SSINFAISFSV ?",
                  "SSINFFRM ?", "NSFRN ?", "VIALL?", "SSFUN ?", "SSSOD ?"):
            try:
                self.send(q)
            except DenonTelnetError:
                return
            time.sleep(0.13)

    # --- konkretne akcje ---

    def set_volume_db(self, db: float) -> float:
        """Ustawia głośność w dB. Sufit obcina wartość, nie odrzuca komendy."""
        if self.volume_ceiling_db is not None:
            db = min(db, self.volume_ceiling_db)
        display = max(0.0, min(db_to_display(db), self._state.get("volume_max") or 98.0))
        display = round(display * 2) / 2.0        # amplituner ma krok 0.5 dB
        self.send("MV" + format_mv(display))
        return round(display_to_db(display), 1)

    def nudge_volume(self, delta_db: float) -> float:
        current = self._state.get("volume_db")
        if current is None:
            raise DenonTelnetError("nie znam jeszcze aktualnej głośności")
        return self.set_volume_db(current + delta_db)

    def set_mute(self, on: bool) -> None:
        self.send("MUON" if on else "MUOFF")

    def set_source(self, code: str) -> None:
        self.send("SI" + code)

    def set_surround(self, mode: str) -> None:
        self.send("MS" + mode)

    def set_multeq(self, mode: str) -> None:
        self.send("PSMULTEQ:" + mode)

    def set_dynamic_eq(self, on: bool) -> None:
        self.send("PSDYNEQ " + ("ON" if on else "OFF"))

    def set_dynamic_volume(self, mode: str) -> None:
        self.send("PSDYNVOL " + mode)

    def set_reference_level(self, offset: str) -> None:
        self.send("PSREFLEV " + offset)

    def set_channel_level(self, channel: str, db: float) -> None:
        db = max(-12.0, min(12.0, db))
        code = format_mv(round((db + 50.0) * 2) / 2.0)
        if channel == "SW":
            self.send("PSSWL " + code)
        elif channel == "SW2":
            self.send("PSSWL2 " + code)
        else:
            self.send(f"CV{channel} {code}")

    # ---- konfiguracja głośników -------------------------------------
    #
    # Te komendy zmieniają ustawienia zapisane w amplitunerze, a nie chwilowy
    # stan odtwarzania. Dlatego każda kończy się ponownym odczytem - żeby
    # interfejs pokazywał to, co urządzenie faktycznie przyjęło, a nie to,
    # o co go poprosiliśmy.

    def set_speaker_size(self, position: str, size: str) -> None:
        """position: FRO/CEN/SUA/SWF...,  size: LAR/SMA/NON"""
        if size not in {"LAR", "SMA", "NON", "2SP", "1SP"}:
            raise ValueError(f"nieznany rozmiar: {size}")
        self.send(f"SSSPC{position} {size}")
        self._reread("SSSPC ?")

    # Zakres wg menu amplitunera: 0,00–18,00 m. Krok bierzemy z urządzenia
    # (SSSDESTP), a nie z założenia — na tym egzemplarzu to 1 cm, czyli
    # 29 µs przy 343 m/s. Zmiana odległości NIE unieważnia filtrów Audyssey:
    # to osobna warstwa nastaw, krzywe korekcyjne zostają.
    DISTANCE_MIN_CM = 0
    DISTANCE_MAX_CM = 1800

    def set_distance_cm(self, channel: str, centimetres: int) -> int:
        """Ustawia odległość kanału w centymetrach. Zwraca wartość wysłaną."""
        value = int(round(centimetres))
        if not self.DISTANCE_MIN_CM <= value <= self.DISTANCE_MAX_CM:
            raise ValueError(
                f"odległość {value} cm poza zakresem "
                f"{self.DISTANCE_MIN_CM}–{self.DISTANCE_MAX_CM} cm")
        self.send(f"SSSDE{channel} {value:04d}M")
        self._reread("SSSDE ?")
        return value

    def set_input_assign(self, family: str, source: str, value: str) -> None:
        """Przypisanie wejścia do źródła. Rodziny odkryte przemiatem."""
        if family not in INPUT_ASSIGN:
            raise ValueError(f"nieznana rodzina przypisań: {family}")
        self.send(f"{family}{source} {value}")
        self._reread(f"{family} ?")

    def set_source_level(self, source: str, raw: int) -> None:
        """Poziom źródła w skali Denona: 50 = 0,0 dB, krok 0,5 dB."""
        value = int(max(38, min(62, raw)))
        self.send(f"SSSLD{source} {value:02d}")
        self._reread("SSSLD ?")

    def set_lipsync(self, key: str, value: str) -> None:
        self.send(f"SSALS{key} {value}")
        self._reread("SSALS ?")

    def set_crossover(self, position: str, freq: int) -> None:
        self.send(f"SSCFR{position} {int(freq):03d}")
        self._reread("SSCFR ?")

    def set_crossover_all(self, freq: int) -> None:
        self.send(f"SSCFRALL {int(freq):03d}")
        self._reread("SSCFR ?")

    def set_subwoofer_mode(self, mode: str) -> None:
        """mode: 'LFE' albo 'L+M' (LFE + Main)"""
        if mode not in {"LFE", "L+M"}:
            raise ValueError(f"nieznany tryb subwoofera: {mode}")
        self.send(f"SSSWM {mode}")
        self._reread("SSSWM ?")

    def set_lfe_lowpass(self, freq: int) -> None:
        self.send(f"SSLFL {int(freq):03d}")
        self._reread("SSLFL ?")

    def set_subwoofer(self, on: bool) -> None:
        self.send("PSSWR " + ("ON" if on else "OFF"))

    def set_tone(self, name: str, value: float) -> dict[str, Any]:
        """Regulacja liczbowa. Kodowanie zależy od rodzaju parametru.

        Jeśli parametr wymaga włączonego przełącznika, włączamy go po drodze
        i mówimy o tym w wyniku. Inaczej suwak wyglądałby na zepsuty.
        """
        spec = TONE_CONTROLS.get(name)
        if spec is None:
            raise ValueError(f"nieznana regulacja: {name}")

        note = None
        needed = spec.get("requires")
        if needed and not self._state.get(needed):
            self.set_switch(needed, "ON")
            time.sleep(0.25)
            note = (f"włączono „{TONE_SWITCHES[needed]['label']}” — "
                    "bez tego amplituner ignoruje tę regulację")
        value = max(spec["min"], min(spec["max"], float(value)))
        if spec["scale"] == "level":
            code = format_mv(round((value + 50.0) * 2) / 2.0)
        elif spec["scale"] == "lfe":
            # LFE liczy się od zera w dół, dwucyfrowo: 00 to 0 dB, 10 to -10 dB.
            code = f"{abs(int(round(value))):02d}"
        else:
            code = f"{int(round(value)):02d}"
        self.send(f"{spec['cmd']} {code}")
        return {"ok": True, "note": note}

    def set_switch(self, name: str, value: str) -> dict[str, Any]:
        spec = TONE_SWITCHES.get(name)
        if spec is None:
            raise ValueError(f"nieznany przełącznik: {name}")
        value = str(value).upper()
        if value not in spec["values"]:
            raise ValueError(f"{name}: dozwolone {spec['values']}")
        self.send(f"{spec['cmd']} {value}")
        return {"ok": True, "note": spec.get("note")}

    def _reread(self, query: str) -> None:
        """Po zmianie ustawienia dopytuje urządzenie, nie zgaduje wyniku."""
        def later() -> None:
            time.sleep(0.45)
            try:
                self.send(query)
            except DenonTelnetError:
                pass
        threading.Thread(target=later, daemon=True).start()

    # ---- menu ekranowe ----------------------------------------------
    #
    # Denon nie udostępnia komendy "uruchom kalibrację Audyssey". Jedyna droga
    # to menu na ekranie - otwieramy je i nawigujemy tak, jak robi to pilot.
    # Menu wychodzi wyłącznie przez HDMI MONITOR, więc projektor musi działać.

    def osd(self, key: str) -> None:
        command = OSD_KEYS.get(key)
        if command is None:
            raise ValueError(f"nieznany klawisz menu: {key}")
        self.send(command)

    def set_power(self, on: bool) -> None:
        """Strefa główna. Całe urządzenie usypia się przez standby()."""
        self.send("ZMON" if on else "ZMOFF")

    def standby(self) -> None:
        self.send("PWSTANDBY")

    def wake(self) -> None:
        self.send("PWON")
