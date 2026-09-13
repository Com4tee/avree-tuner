#!/usr/bin/env python3
"""AVREE Tuner - punkt wejścia.

    python avree_tuner.py                 # sam znajdzie amplituner w sieci
    python avree_tuner.py 192.168.0.73    # albo podaj adres wprost
    python avree_tuner.py --port 8770 --no-browser
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from avree import discovery                      # noqa: E402
from avree.avr import Avr                        # noqa: E402
from avree.server import serve                   # noqa: E402

BANNER = r"""
  ___  _   _____ ___ ___   _____
 / _ \| | / / _ \ __| __| |_   _|  _ _ _  ___ _ _
| (_) | |/ /   / _|| _|    | || || | ' \/ -_) '_|
 \___/|___/_|_\___|___|    |_| \_,_|_||_\___|_|
"""


def find_receiver() -> str | None:
    print("Szukam amplitunera w sieci lokalnej...")
    found = discovery.discover("192.168.0.0/24")
    named = [d for d in found if d.model]
    if named:
        for d in named:
            print(f"  znaleziono: {d}")
        return named[0].host
    if found:
        print(f"  najlepszy kandydat: {found[0]}")
        return found[0].host
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="AVREE Tuner")
    ap.add_argument("host", nargs="?", help="adres IP amplitunera")
    ap.add_argument("--port", type=int, default=8770, help="port interfejsu (domyślnie 8770)")
    ap.add_argument("--no-browser", action="store_true", help="nie otwieraj przeglądarki")
    args = ap.parse_args()

    print(BANNER)

    host = args.host or find_receiver()
    if not host:
        print("\nNie znalazłem amplitunera. Podaj adres wprost:")
        print("   python avree_tuner.py 192.168.0.73")
        return 1

    avr = Avr(host)
    avr.start()

    try:
        httpd = serve(avr, args.port)
    except OSError as e:
        print(f"\nNie mogę zająć portu {args.port}: {e}")
        print("Uruchom z innym portem:  python avree_tuner.py --port 8771")
        avr.stop()
        return 1

    url = f"http://localhost:{args.port}/"
    print(f"Amplituner : {host}")
    print(f"Interfejs  : {url}")
    print(f"Z tabletu  : http://<adres-tego-komputera>:{args.port}/")
    print("\nCtrl+C kończy.\n")

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    # Krótki raport w konsoli, gdy stan już spłynie.
    def report() -> None:
        time.sleep(4.0)
        s = avr.snapshot()
        if not s["connected"]:
            print(f"!  {s['error']}")
            return
        print(f"   {s['device'].get('NAME', host)}  ·  {s.get('surround') or '?'}"
              f"  ·  {s.get('volume_db')} dB")
        if s.get("dynamic_eq"):
            print("!  Dynamic EQ jest WŁĄCZONY - podbija górę i dół pasma.")

    threading.Thread(target=report, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nZamykam...")
    finally:
        httpd.shutdown()
        avr.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
