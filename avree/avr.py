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

# Tryby dźwięku wysyłane jako MS<nazwa>. Dostępność zależy od formatu
# wejściowego - amplituner odrzuci nieodpowiedni bez komunikatu błędu.
SURROUND_MODES = [
    ("DOLBY SURROUND", "Dolby Surround"), ("DTS NEURAL:X", "DTS Neural:X"),
    ("DOLBY DIGITAL", "Dolby Digital"), ("DTS SURROUND", "DTS Surround"),
    ("MOVIE", "Movie"), ("MUSIC", "Music"), ("GAME", "Game"),
    ("MCH STEREO", "Multi Ch Stereo"), ("STEREO", "Stereo"),
    ("AUTO", "Auto"), ("DIRECT", "Direct"), ("PURE DIRECT", "Pure Direct"),
]

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
            "reference_level": None,
            "channel_levels": {}, "setup_levels": {}, "sub_levels": {},
            "speakers": {}, "crossovers": {},
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
                  "CV?", "PSSWL ?", "SSLEV ?", "SSSPC ?", "SSCFR ?", "SSSWM ?", "SSLFL ?",
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

    def set_power(self, on: bool) -> None:
        self.send("ZMON" if on else "ZMOFF")

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
