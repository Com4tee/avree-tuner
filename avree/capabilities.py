"""Model możliwości urządzenia — co dany amplituner FAKTYCZNIE umie.

Pierwszy krok uniwersalizacji (Faza 1 z planu). Dziś interfejs zakłada, że
istnieje Audyssey, dwa suby, `SSSDE` — bo tak jest na AVR-X3300W. Docelowo
**to, co pokazujemy, ma wynikać z tego, co urządzenie o sobie mówi**, a nie
z założeń o jednym egzemplarzu.

Źródłem prawdy jest `Deviceinfo.xml` — manifest, który każdy Denon/Marantz
wystawia pod `/goform/Deviceinfo.xml`. Deklaruje listę funkcji (`FuncName`)
z flagą sterowalności (`Control`), źródła, tryby dźwięku, komplet kanałów
z zakresami, liczbę stref i wersję API. Inny model wystawia inny manifest —
bez Audyssey nie ma tam `Audyssey`/`MultEq`, z Auro-3D dochodzi `Auro`, itd.

Ten moduł jest CZYSTO ODCZYTOWY i defensywny: brak sekcji → pusto, nigdy
wyjątek. Nie zmienia niczego w urządzeniu.

Uwaga o rozbieżności, którą już znamy: manifest podaje `SubwooferNum 1`, choć
telnet (`SSSPCSWF 2SP`) mówi o dwóch subach. Manifest opisuje to, czego używa
aplikacja Denona; realną konfigurację subów bierzemy z telnetu. Dlatego
`subwoofer_num` z manifestu trzymamy jako wskazówkę, nie jako wyrocznię.
"""

from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# Nazwy funkcji z manifestu → czytelne flagi, których używa interfejs.
# Klucz to FuncName z Deviceinfo.xml, wartość to nasza nazwa cechy.
FEATURE_FLAGS = {
    "Audyssey": "audyssey",
    "MultEq": "multeq",
    "DynamicEq": "dynamic_eq",
    "DynamicVolume": "dynamic_volume",
    "RefLevOffset": "reference_level",
    "GraphicEQ": "graphic_eq",
    "ToneControl": "tone_control",
    "CinemaEq": "cinema_eq",
    "Loudness": "loudness",
    "DynamicCompression": "dynamic_compression",
    "DialogControl": "dialog_control",
    "DialogLevel": "dialog_level",
    "LFE": "lfe",
    "CenterSpread": "center_spread",
    "DTSNeuralX": "dts_neural_x",
    "Restorer": "restorer",
    "AudioDelay": "audio_delay",
    "AutoLipSync": "auto_lip_sync",
    "Subwoofer": "subwoofer",
    "SubwooferLevel": "subwoofer_level",
    "ChannelLevel": "channel_level",
    "Bass": "bass",
    "Treble": "treble",
    "SpeakerAB": "speaker_ab",
    "AllZoneStereo": "all_zone_stereo",
    "SleepTimer": "sleep_timer",
    "WakeupTimer": "wakeup_timer",
    "FirmwareUpdate": "firmware_update",
    "EQBand": "eq_band",
    "Auro": "auro_3d",
    "Lfc": "lfc",
}


@dataclass
class Capabilities:
    """Streszczenie tego, co urządzenie o sobie deklaruje."""

    model: str = ""
    brand_code: str = ""
    category: str = ""
    api_vers: str = ""
    zones: int = 1
    subwoofer_num: int = 0
    functions: dict[str, bool] = field(default_factory=dict)   # FuncName -> sterowalne
    sources: list[str] = field(default_factory=list)
    channels: list[dict] = field(default_factory=list)         # {name, min, max, step}
    error: str = ""

    def has(self, func: str) -> bool:
        """Czy urządzenie deklaruje daną funkcję (po FuncName)."""
        return func in self.functions

    def flags(self) -> dict[str, bool]:
        """Czytelne flagi cech dla interfejsu."""
        return {flag: self.has(func) for func, flag in FEATURE_FLAGS.items()}

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "brand_code": self.brand_code,
            "category": self.category,
            "api_vers": self.api_vers,
            "zones": self.zones,
            "subwoofer_num": self.subwoofer_num,
            "functions": self.functions,
            "sources": self.sources,
            "channels": self.channels,
            "flags": self.flags(),
            "error": self.error,
        }


def fetch_manifest(host: str, timeout: float = 5.0) -> bytes:
    """Pobiera Deviceinfo.xml. Port 80 albo 8080 — jak w discovery."""
    last = None
    for port in (80, 8080):
        try:
            with urllib.request.urlopen(
                    f"http://{host}:{port}/goform/Deviceinfo.xml",
                    timeout=timeout) as r:
                return r.read()
        except Exception as e:                       # noqa: BLE001
            last = e
    raise RuntimeError(f"nie udało się pobrać Deviceinfo.xml z {host}: {last}")


def _parent_map(root: ET.Element) -> dict:
    return {child: parent for parent in root.iter() for child in parent}


def _in_section(el: ET.Element, parents: dict, needle: str) -> bool:
    """Czy któryś przodek elementu ma tag zawierający `needle`."""
    cur = parents.get(el)
    while cur is not None:
        if needle.lower() in cur.tag.lower():
            return True
        cur = parents.get(cur)
    return False


def parse(xml: bytes) -> Capabilities:
    """Rozbiera manifest na model możliwości. Defensywnie — nigdy nie rzuca."""
    cap = Capabilities()
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        cap.error = f"manifest nie jest poprawnym XML: {e}"
        return cap

    def text(tag: str, default: str = "") -> str:
        el = root.find(tag)
        return (el.text or "").strip() if el is not None else default

    cap.model = text("ModelName").lstrip("*")
    cap.brand_code = text("BrandCode")
    cap.category = text("CategoryName") or text("ProductCategory")
    cap.api_vers = text("CommApiVers")
    try:
        cap.zones = int(text("DeviceZones") or "1")
    except ValueError:
        cap.zones = 1
    # SubwooferNum bywa zagnieżdżony (pod SubwooferLevel/Setup), nie na
    # najwyższym poziomie — szukamy w całym drzewie. To i tak tylko
    # wskazówka: telnet (SSSPCSWF) jest wyrocznią co do liczby subów.
    for el in root.iter():
        if el.tag == "SubwooferNum" and (el.text or "").strip().isdigit():
            cap.subwoofer_num = int(el.text.strip())
            break

    parents = _parent_map(root)

    # Funkcje: każdy element z <FuncName>. Control=1 → sterowalne z sieci.
    for el in root.iter():
        fn = el.find("FuncName")
        if fn is None or not (fn.text or "").strip():
            continue
        name = fn.text.strip()
        ctrl = el.find("Control")
        controllable = (ctrl is not None and (ctrl.text or "").strip() == "1")
        # Nie nadpisuj True przez False, gdy nazwa powtarza się w kilku sekcjach.
        cap.functions[name] = cap.functions.get(name, False) or controllable

    # Źródła: elementy z SourcePath.
    seen = set()
    for el in root.iter():
        if el.find("SourcePath") is None:
            continue
        name = (el.findtext("DefaultName") or el.findtext("FuncName") or "").strip()
        if name and name not in seen:
            seen.add(name)
            cap.sources.append(name)

    # Trybów dźwięku świadomie tu NIE zbieramy. W manifeście siedzą
    # w liście skrótów wymieszane ze źródłami — brudne źródło. Zweryfikowaną
    # empirycznie listę trybów surround trzyma modes.py i to jest wyrocznia.

    # Kanały: elementy z zakresem i nazwą (ChannelLevel).
    for el in root.iter():
        lo = el.find("MinRange")
        hi = el.find("MaxRange")
        if lo is None or hi is None:
            continue
        name = (el.findtext("DispName") or el.findtext("FuncName") or "").strip()
        if not name or not _in_section(el, parents, "channel"):
            continue
        cap.channels.append({
            "name": name,
            "min": (lo.text or "").strip(),
            "max": (hi.text or "").strip(),
            "step": (el.findtext("Step") or "").strip(),
        })

    return cap


def read(host: str, timeout: float = 5.0) -> Capabilities:
    """Pobiera i rozbiera manifest jednym wywołaniem."""
    try:
        return parse(fetch_manifest(host, timeout))
    except Exception as e:                           # noqa: BLE001
        cap = Capabilities()
        cap.error = str(e)
        return cap
