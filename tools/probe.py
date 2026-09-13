"""Zrzut pełnego stanu amplitunera - pierwszy kontakt i mapowanie protokołu.

Uruchomienie:
    python tools/probe.py 192.168.0.73
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# konsola Windows domyslnie cp1252 - wymuszamy UTF-8 na wyjsciu
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from avree.commands import QUERY_GROUPS          # noqa: E402
from avree.telnet import DenonTelnet             # noqa: E402


def main(host: str) -> int:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(__file__).resolve().parent.parent / "captures"
    out_dir.mkdir(exist_ok=True)

    result: dict[str, dict[str, list[str]]] = {}
    unanswered: list[str] = []

    print(f"Łączę z {host}:23 ...")
    with DenonTelnet(host) as avr:
        time.sleep(0.4)
        avr.drain()  # AVR często wypluwa stan powitalny

        for group, queries in QUERY_GROUPS.items():
            print(f"\n=== {group.upper()} " + "=" * (50 - len(group)))
            result[group] = {}
            for q in queries:
                lines = avr.ask(q, settle=0.45)
                result[group][q] = lines
                if lines:
                    for ln in lines:
                        print(f"  {q:<16} -> {ln}")
                else:
                    unanswered.append(q)
                    print(f"  {q:<16} -- brak odpowiedzi")

    raw_path = out_dir / f"probe-{stamp}.json"
    raw_path.write_text(
        json.dumps({"host": host, "groups": result, "unanswered": unanswered},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nZapisano: {raw_path}")
    if unanswered:
        print(f"Bez odpowiedzi ({len(unanswered)}): {', '.join(unanswered)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "192.168.0.73"))
