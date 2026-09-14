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
| 2 | Odtwarzanie plików przez DLNA ✔ · pętla WASAPI ze splotem ✔ |
| 3 | Silnik pomiarowy — sweep, dekonwolucja, analiza ✔ |
| 4 | Wejście audio i wizualizacja z mikrofonu ✔ |
| 5 | Własny optymalizator filtrów ✔ |
| 6 | Parser `.ady` i upload kalibracji do amplitunera |

## Splot w torze PC

Zakładka **Odtwarzanie**, karta „Dźwięk z komputera". Pętla WASAPI przechwytuje
wszystko, co gra Windows, przepuszcza przez filtry z zakładki **Equalizer**
(kanały FL i FR) i wypuszcza dalej. Nie wymaga wtyczek do foobara ani niczego
innego — działa też dla przeglądarki i gier.

Dwie drogi wyjścia:

| Droga | Opóźnienie | Kanały | Do czego |
|---|---|---|---|
| Nieskończony WAV po HTTP → UPnP amplitunera | sekundy (renderer buforuje) | **tylko stereo** | muzyka |
| Inne lokalne wyjście (optyka, HDMI) | dziesiątki ms | tyle, ile daje urządzenie | film, 5.1 |

### Co z 5.1 i dwoma subwooferami

Splot filtruje **każdy kanał osobno** — sprawdzone na sześciu kanałach naraz,
każdy dostał własne pasma z dokładnością do 0,00 dB. Ale o liczbie kanałów
decyduje Windows, nie aplikacja: pętla WASAPI dostaje dokładnie tyle, ile
wyjście ma ustawione w *Panel sterowania → Dźwięk → Konfiguruj*. Wyjście
ustawione na stereo daje dwa kanały i żadne ustawienie w aplikacji tego
nie zmieni.

Dwa ograniczenia są twarde i wynikają ze sprzętu:

1. **Droga przez UPnP nigdy nie poniesie 5.1.** Renderer sieciowy X3300W jest
   stereo — jego lista formatów kończy się na `audio/L16;rate=48000;channels=2`,
   nie ma tam AC3, E-AC3 ani DTS. Materiał wielokanałowy jest przed wysłaniem
   zsumowany do stereo (ITU-R BS.775: środek i surroundy po −3 dB, LFE pominięty).
   Pełne 5.1 przechodzi **wyłącznie** przez lokalne wyjście HDMI.

2. **Drugiego subwoofera nie da się skorygować z komputera.** Z PC wychodzi
   jeden kanał LFE; rozdział na SW1 i SW2 robi wzmacniacz w środku. Różnicę
   między dwoma subami wyrówna tylko Audyssey Sub EQ HT albo plik `.ady` —
   czyli etap 6, jeszcze niezbudowany.

Kolejność kanałów w pętli przyjęta jest wg standardu WAVE (FL, FR, środek,
LFE, tylne). **Ta kolejność nie została sprawdzona na docelowym sprzęcie** —
stacjonarny ma tylko wyjście stereo, więc nie było czego mierzyć. Dlatego
przypisanie kanałów do pasm jest w interfejsie edytowalne: da się je poprawić
na słuch, także w trakcie grania.

Zmierzone na tym komputerze i na **Denon AVR-X3300W**:

- Odpowiedź filtrów zgodna z projektem co do **0,0000 dB** w paśmie 20 Hz – 16 kHz.
- Przetwarzanie blokowe identyczne z przetworzeniem całości: różnica **0,00e+00**.
- **0,091 ms** na blok 1024 próbek przy budżecie 21,3 ms — zapas **234×**.
- Strumień HTTP dostarczył **2,01 s dźwięku w 2,00 s**, zero zgubionych bloków
  przez 87 sekund z amplitunerem jako odbiorcą.
- Amplituner raportuje `PLAYING` i liczy czas — w jego liście formatów są
  `audio/wav` i `audio/L16;rate=48000;channels=2`.

Zmiana pasm w equalizerze wchodzi na żywo: filtry są podmieniane bez zerowania
pamięci, więc nie ma stuknięcia. Zerowanie następuje tylko wtedy, gdy zmieni
się LICZBA filtrów — wtedy starej pamięci nie ma dokąd przenieść.

**Głośność systemowa musi stać na maksimum.** Pętla WASAPI słyszy dźwięk *po*
suwaku Windows: ściszony system to cichszy strumień i gorszy stosunek do szumu
po konwersji na 16 bitów. Regulować należy amplitunerem.

### Dlaczego dwie biblioteki dźwiękowe

`sounddevice` **nie umie pętli WASAPI** w wersji 0.5.6 — jego `WasapiSettings`
ma tylko `exclusive`, `auto_convert` i `explicit_sample_format`, a otwarcie
wyjścia jako wejścia kończy się błędem `Invalid number of channels`. Sprawdzone.
Dlatego splot używa `soundcard`, a tor pomiarowy zostaje przy `sounddevice`,
gdzie potrzebne jest granie i nagrywanie na wspólnym zegarze (`playrec`).

`soundcard` inicjuje COM tylko na wątku, który go zaimportował. Serwer WWW
obsługuje każde żądanie na nowym wątku, więc `avree/stream.py` wchodzi do COM
jawnie na każdym wątku — bez tego pierwsze wejście w zakładkę kończy się
błędem `0x800401f0`.

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
- [ ] Splot w torze PC **na ucho** — poprawność liczbowa i transport są
      zmierzone, ale nikt jeszcze nie słuchał wyniku przez głośniki
- [ ] Wyjście lokalne splotu — na stacjonarnym jest tylko jedna karta,
      więc drogi „inne wyjście" nie dało się sprawdzić (źródło i cel
      muszą być osobnymi urządzeniami)
- [ ] Kolejność kanałów w pętli 5.1 — przyjęta wg standardu WAVE, ale
      niezmierzona. Sprawdzić na słuch: puścić materiał z rozpoznawalnym
      kanałem i zobaczyć, czy filtr trafia tam, gdzie powinien
- [ ] Czy Windows w ogóle odda 5.1 na HDMI do amplitunera — to ta sama
      walka z downmixem, która skończyła się porażką przy poprzednim podejściu

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
