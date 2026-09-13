# AVREE Tuner

Sterowanie amplitunerem Denon AVR-X3300W i kalibracja Audyssey MultEQ XT32 z poziomu PC.

Dwa cele:

1. **Widzieć i zmieniać to, co amplituner naprawdę ma** — tryby przestrzenne, stan Audyssey,
   konfigurację głośników — bez przeklikiwania się przez logikę aplikacji Denona.
2. **Własna kalibracja** — pomiar mikrofonem pomiarowym, własny optymalizator z twardymi
   ograniczeniami (tylko cięcia, korekcja tylko w zakresie modalnym), wynik wgrany do DSP.

## Stan

Działa: wykrywanie amplitunera w sieci, klient telnet, odczyt pełnego stanu, rozpoznanie
warstw HTTP i UPnP. Ustalenia protokołu: [`docs/protokol-x3300w.md`](docs/protokol-x3300w.md).

Mockup interfejsu: `design/mockup.html` (pięć ekranów, otwórz w przeglądarce).

## Uruchomienie

```bash
python avree/discovery.py 192.168.0.0/24   # znajdź amplituner
python tools/probe.py 192.168.0.73         # zrzut pełnego stanu
python tools/http_probe.py 192.168.0.73    # rozpoznanie HTTP
python tools/mapper.py 192.168.0.73        # mapowanie nieudokumentowanych komend
```

Python 3.13+ (`telnetlib` zniknęło ze stdlib — klient jest na gołym sockecie).
Rdzeń nie ma zależności zewnętrznych.

## Plan

| Etap | Zakres |
|---|---|
| 0 | Diagnostyka: zrzut stanu + pomiar różnicowy Audyssey ON/OFF |
| 1 | Sterownik i GUI — pełna kontrola nad AVR |
| 2 | Odtwarzanie: foobar2000/DLNA, pętla WASAPI, monitor formatu wejściowego |
| 3 | Parser `.ady` — odczyt i wizualizacja kalibracji |
| 4 | Pipeline pomiarowy przez API Room EQ Wizard |
| 5 | Własny optymalizator filtrów |
| 6 | Upload kalibracji do amplitunera |

## Ograniczenia ustalone empirycznie

- Odległości głośników **nie są czytelne** po telnecie — trzeba je wyliczyć z pomiaru.
- Renderer sieciowy jest **stereo**; AC3/DTS wymagają HDMI albo optyki.
- Amplituner przyjmuje **jedno połączenie telnet naraz**.
- X3300W (rocznik 2016) **nie ma** `Save & Load` na USB — obecnej kalibracji nie da się
  pobrać z urządzenia żadną drogą.
