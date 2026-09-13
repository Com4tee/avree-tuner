"""AVREE Tuner - sterowanie Denon AVR i kalibracja Audyssey."""

import sys

__version__ = "0.2.0"

# Konsola Windows domyslnie cp1252 i wywraca sie na polskich znakach.
# Ustawiamy raz, przy imporcie pakietu, zeby kazdy punkt wejscia to mial.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
