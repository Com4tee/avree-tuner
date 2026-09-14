"""Enumeracja WSZYSTKICH ustawień, jakie amplituner przyjmuje z zewnątrz.

Nie dotyczy krzywej kalibracji — ta siedzi w DSP i nie wychodzi żadnym
kanałem. Chodzi o parametry: co da się odczytać i ustawić po sieci.

Sonda idzie przez działającą aplikację (amplituner przyjmuje tylko jedno
połączenie telnet), a odpowiedzi rozpoznaje po znaczniku czasu — nie po
długości bufora, bo ten jest zapętlony i porównywanie długości daje
fałszywe „cisza" nawet dla komend, które odpowiadają.

    python tools/audyssey_probe.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = "http://localhost:8770"

# Kandydaci pogrupowani tematycznie. Wszystko w formie zapytań — żadnych
# seterów, żeby sonda nie zmieniała ustawień użytkownika.
GROUPS = {
    "Audyssey — rdzeń": [
        "PSMULTEQ: ?", "PSDYNEQ ?", "PSREFLEV ?", "PSDYNVOL ?",
        "PSLFC ?", "PSCNTAMT ?",
    ],
    "Audyssey — dodatki historyczne": [
        "PSDSX ?", "PSSTW ?", "PSSTH ?", "PSDEH ?",
    ],
    "Parametry przestrzenne": [
        "PSCINEMA EQ. ?", "PSCES ?", "PSLOM ?", "PSDRC ?", "PSDCO ?",
        "PSEFF ?", "PSDEL ?", "PSRSZ ?", "PSNEURAL ?", "PSSP: ?",
        "PSPHG ?", "PSMDAX ?", "PSATT ?",
    ],
    "Poziomy i barwa": [
        "PSBAS ?", "PSTRE ?", "PSTONE CTRL ?", "PSLFE ?", "PSDIL ?",
        "PSDIC ?", "PSSWL ?", "PSSWR ?", "PSCLV ?", "PSVOL ?",
    ],
    "Konfiguracja głośników": [
        "SSSPC ?", "SSCFR ?", "SSSWM ?", "SSLFL ?", "SSLEV ?", "CV?",
        "SSPAA ?", "SSDST ?", "SSSPDIF ?", "SSBAS ?",
    ],
    "Equalizer graficzny": [
        "PSGEQ ?", "SSGEQ ?", "PSEQ ?", "SSEQ ?", "PSGRAPHICEQ ?",
        "SSAEQ ?", "PSMANUALEQ ?", "SSMEQ ?",
    ],
    "Ustawienia systemowe": [
        "SSAST ?", "SSLAN ?", "SSLOC ?", "SSECO ?", "SSHOS ?",
        "SSSMG ?", "SSQSNZMA ?", "SSTPD ?", "SSTRG ?",
    ],
    "Sygnał i informacje": [
        "SSINFAISSIG ?", "SSINFAISFSV ?", "SSINFFRM ?", "VIALL?", "NSFRN ?",
    ],
}


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


def log_since(mark: float) -> list[str]:
    with urllib.request.urlopen(BASE + "/api/log?n=400", timeout=10) as r:
        lines = json.loads(r.read().decode())["lines"]
    return [x["line"] for x in lines if x["dir"] == "rx" and x["t"] > mark]


def probe(command: str, settle: float = 0.55) -> list[str]:
    mark = time.time()
    time.sleep(0.05)                  # odstęp, żeby znacznik był rozstrzygający
    post("/api/command", {"action": "raw", "value": command})
    time.sleep(settle)
    return log_since(mark)


def main() -> int:
    try:
        urllib.request.urlopen(BASE + "/api/state", timeout=5)
    except Exception:
        print("Aplikacja nie działa. Uruchom najpierw AVREE Tuner.")
        return 1

    answered: dict[str, list[str]] = {}
    silent: list[str] = []

    for group, commands in GROUPS.items():
        print(f"\n=== {group} " + "=" * max(0, 46 - len(group)))
        for c in commands:
            lines = probe(c)
            if lines:
                answered[c] = lines
                shown = lines if len(lines) <= 4 else lines[:4] + [f"... +{len(lines)-4}"]
                print(f"  ODPOWIADA  {c:<18} {shown}")
            else:
                silent.append(c)
                print(f"  cisza      {c}")

    out = Path(__file__).resolve().parent.parent / "captures" / \
        f"audyssey-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"answered": answered, "silent": silent},
                              indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'='*58}")
    print(f"Odpowiada: {len(answered)} / {len(answered) + len(silent)}")
    print(f"Zapisano : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
