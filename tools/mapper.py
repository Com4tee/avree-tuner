"""Mapowanie nieudokumentowanych zapytań protokołu.

Wysyła kandydatów w formie zapytań (sufiks ' ?' / '?') i notuje, które
odpowiadają. Świadomie WYŁĄCZNIE zapytania - żadnych seterów.

    python tools/mapper.py 192.168.0.73
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from avree.telnet import DenonTelnet  # noqa: E402

# Kandydaci zebrani z dokumentacji protokołu i z bibliotek społecznościowych.
CANDIDATES = [
    # poziomy i opóźnienia kanałów
    "CV?", "SSDST ?", "SSDSTUNI ?", "SSCFR ?", "SSSPDFRQ ?", "SSSWM ?",
    "SSLFL ?", "PSDEL ?", "PSSWR ?", "PSSP:?", "PSSTW ?",
    # konfiguracja wzmacniacza / przypisania
    "SSPAA ?", "SSSPCAMP ?", "SSAMP ?", "SSSPCBIA ?",
    # informacje o urządzeniu
    "SSINFFRM ?", "SSINFAIS ?", "SSINFSIG ?", "SSLAN ?", "SSMAC ?",
    "NSFRN ?", "VIALL?", "SYMO?",
    # tryby dźwięku - szukamy listy możliwości
    "SSSMS ?", "SSSDM ?", "MSSMART ?", "SSMOD ?", "SSSUR ?",
    # HDMI / audio routing
    "SSHAS ?", "SSALSSET ?", "SSALSDSP ?", "SSSDX ?",
    # quick select / nazwy
    "SSQSN ?", "SSQSNZMA ?", "SSFUNZMA ?",
    # eco / standby / trigger
    "SSECO ?", "SSTPD ?", "SSTRG ?", "SSLOC ?",
    # Audyssey - próby dotarcia głębiej
    "PSAUDYSSEY ?", "SSAUD ?", "SSMEQ ?", "SSAUDY ?", "SSCAL ?",
    "PSMULTEQ:?", "PSDYNEQ?", "PSREFLEV?",
]


def main(host: str) -> int:
    hits: dict[str, list[str]] = {}
    misses: list[str] = []

    print(f"Mapowanie protokołu na {host} - {len(CANDIDATES)} kandydatów\n")
    with DenonTelnet(host) as avr:
        time.sleep(0.4)
        avr.drain()
        for cmd in CANDIDATES:
            lines = avr.ask(cmd, settle=0.40)
            if lines:
                hits[cmd] = lines
                print(f"  [OK ] {cmd:<18} -> {lines}")
            else:
                misses.append(cmd)
                print(f"  [   ] {cmd}")

    out = Path(__file__).resolve().parent.parent / "captures" / \
        f"mapper-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"hits": hits, "misses": misses}, indent=2,
                              ensure_ascii=False), encoding="utf-8")
    print(f"\nTrafienia: {len(hits)}/{len(CANDIDATES)}   ->  {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "192.168.0.73"))
