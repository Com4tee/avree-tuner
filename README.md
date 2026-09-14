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

Dwuklik w `AVREE Tuner.bat`. Amplituner zostaje znaleziony sam, interfejs
otwiera się w przeglądarce pod `http://localhost:8770/`.

Z wiersza poleceń:

```bash
python avree_tuner.py                 # sam znajdzie amplituner
python avree_tuner.py 192.168.1.50    # albo podaj adres wprost
python avree_tuner.py --port 8771 --no-browser
```

Z tabletu w tej samej sieci: `http://<adres-komputera>:8770/`.

Python 3.13+ (`telnetlib` zniknęło ze stdlib — klient jest na gołym sockecie).
**Bez zależności zewnętrznych** — sama biblioteka standardowa.

### Jak znajduje amplituner

1. Adres zapamiętany z poprzedniego uruchomienia.
2. SSDP M-SEARCH wysłany osobno z **każdego** interfejsu sieciowego.
3. Skan portów sterowania po każdej wykrytej podsieci /24.

Nic nie jest zaszyte na sztywno — podsieci biorą się z interfejsów komputera,
więc działa w dowolnej sieci. Potwierdzeniem jest odpowiedź na
`/goform/Deviceinfo.xml`, a nie otwarty port telnet: amplituner przyjmuje
tylko jedno połączenie telnet naraz, więc gdy trzyma je inna aplikacja,
port 23 wygląda na zamknięty.

Adres można też wpisać ręcznie w zakładce Konfiguracja.

### Narzędzia diagnostyczne

```bash
python avree/discovery.py            # co widać w sieci
python tools/probe.py 192.168.0.73   # zrzut pełnego stanu
python tools/http_probe.py <ip>      # rozpoznanie warstwy HTTP
python tools/mapper.py <ip>          # mapowanie nieudokumentowanych komend
```

## Plan

| Etap | Zakres |
|---|---|
| 0 | Diagnostyka: zrzut stanu + pomiar różnicowy Audyssey ON/OFF |
| 1 | Sterownik i GUI — pełna kontrola nad AVR ✔ |
| 2 | Odtwarzanie plików przez DLNA ✔ · pętla WASAPI dla przeglądarki |
| 3 | Silnik pomiarowy — sweep, dekonwolucja, analiza ✔ |
| 4 | Wejście audio i wizualizacja z mikrofonu ✔ |
| 5 | Własny optymalizator filtrów ✔ |
| 6 | Parser `.ady` i upload kalibracji do amplitunera |

## Ograniczenia ustalone empirycznie

- Odległości głośników **nie są czytelne** po telnecie — trzeba je wyliczyć z pomiaru.
- Renderer sieciowy jest **stereo**; AC3/DTS wymagają HDMI albo optyki.
- Amplituner przyjmuje **jedno połączenie telnet naraz**.
- X3300W (rocznik 2016) **nie ma** `Save & Load` na USB — obecnej kalibracji nie da się
  pobrać z urządzenia żadną drogą.


## Przeniesienie na inny komputer

Parowania i klucze **nie są w repozytorium** — leżą w
`%APPDATA%vree-tuner\`:

| Plik | Co trzyma |
|---|---|
| `webos-keys.json` | klucze klienta do rzutnika i telewizora LG |
| `androidtv-cert.pem`, `androidtv-key.pem` | certyfikat klienta do Google TV |
| `androidtv-paired.json` | które urządzenia Android TV są sparowane |
| `config.json` | adresy, nazwy, MAC-i, blokada auto-wyłączania |
| `eq.json` | projekt korekcji |

**Skopiowanie tego katalogu na inny komputer przenosi wszystkie parowania.**
Bez tego trzeba sparować od nowa: rzutnik, telewizor i Google TV — każde
z potwierdzeniem na ekranie.

Uwaga do certyfikatu Android TV: parowanie jest z nim związane. Wygenerowanie
nowego (czyli skasowanie plików `.pem`) unieważnia poprzednie parowanie.

Uwaga do webOS: klucz klienta jest wiązany z ADRESEM, nie z urządzeniem.
Nowy adres z DHCP wymaga ponownego parowania — warto zarezerwować adresy
na routerze.

## Do zweryfikowania w następnej sesji

Trzy piloty wysyłają komunikaty bez błędu i utrzymują połączenie, ale
**skutku wizualnego nie potwierdzono** — testy szły ze stacjonarnego
w innym pokoju niż ekrany.

- [ ] Rzutnik `192.168.0.75` — wysłane INFO i BACK
- [ ] Telewizor `192.168.0.17` — wysłane INFO, BACK i napis na ekranie
- [ ] Google TV `192.168.0.58` — wysłane HOME, strzałki w czterech kierunkach
- [ ] Blokada auto-wyłączania — potwierdzenia wymaga dopiero dłuższy seans

Jeśli któryś pilot nie rusza niczym na ekranie, do poprawy są numery pól
w komunikacie wstrzykującym klawisz.

## Jak wyznaczana jest górna granica korekcji

Nie przez fazę, tylko przez **rozrzut między pozycjami mikrofonu**. Tam gdzie
pomiary z różnych punktów strefy odsłuchu się zgadzają, korekcja przeniesie się
na całą strefę. Tam gdzie się rozjeżdżają, filtr poprawi jeden punkt i popsuje
pozostałe.

Optymalizator bierze tę granicę z pomiaru, o ile nie narzucisz własnej.
Z jednej pozycji nie da się orzec o powtarzalności, więc maska nie przepuszcza
wtedy niczego.

**Sprostowanie wcześniejszego założenia.** Twierdziłem, że rezonans modalny jest
minimalnofazowy, a odbicie nie — i że to pozwala je rozróżnić. To nieprawda.
Filtr grzebieniowy `1 + g·z^-d` ma zero wewnątrz okręgu jednostkowego dla
`|g| < 1`, więc odbicie słabsze od dźwięku bezpośredniego **jest**
minimalnofazowe. Sprawdzone: przy g = 0.3, 0.5 i 0.8 faza nadmiarowa wynosi
dokładnie zero, pojawia się dopiero od g ≈ 0.99.

`minimum_phase` i `excess_phase` zostały naprawione (metoda cepstralna, błąd
0.00° wobec prawdziwej fazy biquada) i służą teraz do tego, do czego nadają się
naprawdę: wykrywania pomiaru zrobionego w zapadzie interferencyjnym, gdzie suma
odbić przewyższa dźwięk bezpośredni.

## Znane ograniczenia

- Próg rozrzutu 3 dB, powyżej którego uznajemy pasmo za niekorygowalne, **nie
  jest skalibrowany** na prawdziwym pomieszczeniu. Mechanizm jest sprawdzony
  (wykryta granica trafia w miejsce rozbieżności z dokładnością kilku Hz), ale
  właściwą wartość progu pokażą dopiero pomiary w Twoim pokoju.
