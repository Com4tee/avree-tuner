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
| 6 | Parser `.ady` i upload kalibracji — **kanał znaleziony**, port 1256 |

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

2. **Korekcji AMPLITUDY drugiego subwoofera nie da się zrobić z komputera.**
   Z PC wychodzi jeden kanał LFE; rozdział na SW1 i SW2 robi wzmacniacz
   w środku. Osobne filtry dla każdego suba to plik `.ady`, czyli etap 6.

   **Ale ZESTROJENIE CZASOWE obu subów jest osiągalne po sieci** — patrz
   niżej. To osobna warstwa nastaw i działa niezależnie od `.ady`.

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

## Zestrojenie czasowe dwóch subwooferów

Zakładka **Pomiar**, karta „Zestrojenie czasowe dwóch subwooferów".

Okazało się, że **każdy subwoofer ma własną, ustawialną po sieci odległość**:

```
SSSDESW  0427M     subwoofer 1: 4,27 m
SSSDESW2 0886M     subwoofer 2: 8,86 m
SSSDESTP 01M       krok 1 cm
```

Różnica 4,59 m to **13,4 ms** — to nie odległości fizyczne, tylko opóźnienie
policzone przez Audyssey Sub EQ HT. Krok 1 cm = **29 µs**, czyli pół stopnia
fazy przy 50 Hz. Odczyt i zapis sprawdzone empirycznie na tym egzemplarzu.

**Sprostowanie.** Wcześniej stało tu, że odległości głośników są po telnecie
niedostępne. To była pomyłka: sprawdzony był mnemonik `SSDST` zamiast `SSSDE`.
Nieobecność w `Deviceinfo.xml` (`SubwooferNum 1`, zero tagów odległości)
też nie jest dowodem — ten manifest opisuje, czego używa aplikacja Denona,
a nie co przyjmuje telnet.

### Jak to działa

Oba suby dostają ten sam sygnał LFE i nie da się z zewnątrz wyciszyć jednego
(`CVSW2` schodzi do −12 dB, nie do ciszy). Dlatego zamiast mierzyć je osobno,
przemiatamy opóźnienie jednego i mierzymy mikrofonem sumę w miejscu odsłuchu.
Maksimum poziomu w paśmie = najlepsze sumowanie. Metoda nie wymaga
rozdzielania kanałów i mierzy od razu to, co słychać na kanapie.

Sygnałem jest krótki sweep 20–120 Hz, nie pojedynczy ton: jedna częstotliwość
potrafi mieć maksimum gdzie indziej niż całe pasmo i zestroiłaby 40 Hz
kosztem 70 Hz.

Wierzchołek jest doprecyzowywany parabolą przez trzy punkty wokół maksimum.
Sprawdzone na symulacji z wstawioną różnicą 137 cm i krokiem przemiatania
10 cm: znalezione 135 cm, czyli **błąd 2 cm (0,058 ms)** — lepiej niż krok.

Nastawa **wraca na miejsce po każdym przemiataniu, także po błędzie**.
Zapis na stałe to osobny przycisk.

### Ograniczenie metody

Maksimum znalezione dla jednej pozycji mikrofonu jest optymalne dla tej
pozycji. Przy szerokiej kanapie trzeba powtórzyć w kilku punktach i wziąć
nastawę dobrą wszędzie, zamiast idealnej w jednym miejscu.

## Drugi kanał: protokół Audyssey na porcie 1256

**Sprostowanie do wcześniejszych wniosków.** Twierdziłem tu, że z wzmacniacza
nie da się wyciągnąć danych pomiarowych i że komunikacja jest jednokierunkowa.
**To było błędne.** Amplituner nasłuchuje na TCP 1256 i odpowiada JSON-em:

```
GET_AVRINF -> {"EQType":"MultEQXT32","SWLvlMatch":true,"SysDelay":280,...}
GET_AVRSTS -> {"ChSetup":[{"FL":"L"},{"C":"L"},{"FR":"L"},{"SLA":"L"},
                          {"SRA":"L"},{"SWMIX1":"E"},{"SWMIX2":"E"}],...}
```

To ten sam kanał, którym płatna aplikacja MultEQ Editor czyta pomiary
i wgrywa korekcję. Pełny opis: [docs/protokol-audyssey-1256.md](docs/protokol-audyssey-1256.md).

Kodek ramek w [avree/audyssey.py](avree/audyssey.py) daje bajty identyczne
z sześcioma opublikowanymi wzorcami i czyta z urządzenia na żywo.

**Czego nadal nie da się odczytać:** gotowych krzywych korekcyjnych.
`SET_COEFDT` jest tylko do zapisu. Ale pętla domyka się inaczej — wzmacniacz
mierzy (`START_CHNL`), my odbieramy odpowiedzi impulsowe (`GET_RESPON`),
liczymy własne filtry i wgrywamy z powrotem.

**Ryzyko:** `ENTER_AUDY` rozpoczyna nową kalibrację i może nadpisać obecne
krzywe Audyssey. Powrót to przejście całej procedury od nowa. Nie wchodzić
w ten tryb bez świadomej decyzji.

## Punkt podziału i krzywa Audyssey — liczone, nie zgadywane

Zakładka **Pomiar**, karta „Co wynika z pomiaru".

**Punkt podziału** bierze się z opadania zmierzonego kanału, nie z okrągłej
liczby: szukamy −3 dB względem poziomu w paśmie 200–800 Hz i stawiamy podział
**1,5× wyżej**. Zapas jest konieczny, bo przy własnym opadaniu głośnik ma już
duże zniekształcenia i mały zapas wysterowania, choć poziom jeszcze nie spadł.
Wynik jest zaokrąglany w górę do wartości, które X3300W przyjmuje
(40, 60, 80, 90, 100, 110, 120, 150, 200, 250 Hz).

Sprawdzone na filtrach o znanym F3 — 35, 45, 65 i 95 Hz: wykryte **co do 0,0 Hz**.

Ma to znaczenie przy dwóch różnych subwooferach (tubowy i bass-reflex): każdy
ma inne opadanie i inny punkt podziału, a różnicy nie da się zgadnąć.

**Krzywa korekcji Audyssey.** Gotowych filtrów **nie da się odczytać**
z procesora — przetestowałem około 600 nazw komend, `GET_RESPON` milczy poza
sesją kalibracji, a `SET_COEFDT` jest tylko do zapisu.

Da się jednak zmierzyć to samo: różnica dwóch pomiarów tego samego kanału,
raz z MultEQ włączonym i raz wyłączonym, **jest** krzywą korekcji. Akustycznie
jest to nawet więcej niż odczyt filtru — pokazuje, co faktycznie dociera do
ucha, razem z wpływem głośnika i pomieszczenia.

Umowa pozycji: **1..N** z Audyssey ON, **101..100+N** z OFF. Pary są oczywiste
(1 i 101 to ten sam punkt), a jedno i drugie mieści się w istniejącej strukturze.

Oba pomiary są wyrównywane poziomem w paśmie 200–500 Hz, bo Audyssey zmienia
też trym kanału — bez tego cała krzywa byłaby przesunięta o stałą.

Sprawdzone na wstawionym podbiciu +5 dB powyżej 4 kHz, cięciu −8 dB przy 45 Hz
i przesunięciu trymu +2 dB: odtworzone wszystkie trzy.

## Podgląd ekranu amplitunera

Zakładka **Odtwarzanie**, karta „Ekran amplitunera". Dziewięć linii treści
ekranu przeglądarki źródeł sieciowych, ze strzałkami sterującymi kursorem.

Czytane z **portu 5000** — drugiego kanału sterowania, znalezionego przy
skanowaniu portów. Mówi tym samym protokołem ASCII co telnet (`PW?` → `PWON`),
ale jest osobnym gniazdem, więc działa **równolegle** z portem 23, który
przyjmuje tylko jedno połączenie i trzyma je reszta aplikacji.

Format: `NSE0`–`NSE8`, po sto znaków. Linia 0 to nagłówek, 1–7 pozycje menu,
8 stopka ze stronicowaniem. Przed tekstem jeden bajt ikony i kursora.

Ograniczenie: `NSE` pokazuje **przeglądarkę źródeł sieciowych**, nie pełne
menu konfiguracji z telewizora. Przy innym wejściu bywa pusty.

Pozostałe otwarte porty, sprawdzone: 1024 to AirPlay (`AirTunes/190.9`),
5001 to konsola z promptem `>`, która nie zna żadnego z 49 przetestowanych
słów, 6666 milczy na wszystko.

## Szesnaście nieudokumentowanych komend

Systematyczny przemiat **pełnej przestrzeni `SS`+3 i `PS`+3 litery** (po 17 576
kombinacji) dwoma niezależnymi torami — port 23 i port 5000 — dał zgodny wynik:
**15 nieudokumentowanych komend `SS` plus `PSHEQ`**.

Najciekawsze: `SSHDM`/`SSANA`/`SSDIN`/`SSVDO` (przypisanie wejść per źródło),
`SSSLD` (poziom każdego źródła osobno), `SSDSS` (odległości głośników
Dolby-enabled), `SSALS` (Auto Lip Sync), `SSOSD` (menu ekranowe).

Pełny opis wraz z metodą i odczytami: [docs/nowe-komendy-x3300w.md](docs/nowe-komendy-x3300w.md).

**Lekcja metodologiczna.** Pierwsza wersja przemiatu na porcie 1256 była
zepsuta i zwracała „zero trafień" wyglądające jak rzetelny negatyw:
potokowała ramki, a wzmacniacz odpowiadał tylko na pierwszą rozpoznaną
komendę. Wykryła to dopiero kontrola — znane komendy wstawione między
śmieciowe nazwy nie zostały wykryte. Od tego czasu każdy przemiat zaczyna
się kontrolą, powtarza ją co 150 nazw i przerywa, gdy padnie.
**Przemiat bez kontroli nie dowodzi niczego.**

## Firmware i tryby serwisowe

Analiza oryginalnych obrazów firmware i oficjalnego dokumentu serwisowego —
pełny opis w [docs/firmware-i-serwis-x3300w.md](docs/firmware-i-serwis-x3300w.md).

Skrót: **firmware jest zaszyfrowane** (kontener `host` + ECB, blok 8 bajtów,
dwa klucze — osobny na kod, osobny na system plików). Udowodnione empirycznie,
że to prawdziwy szyfr blokowy, nie XOR. Bez klucza, którego nie ma publicznie,
nie da się go odczytać. To zamyka trzecią i ostatnią drogę do krzywych EQ.

Przy okazji z oficjalnego arkusza Denona wyłuskane **tryby serwisowe X3300W**:
reset mikroprocesora (`TUNER PRESET CH +`/`-`, nie czyści kalibracji), reset
fabryczny (`ZONE 2 SOURCE`/`DIMMER` — czyści wszystko), Service Mode (tylko
wyświetlacz czołowy). Oraz procedura aktualizacji USB i Product ID regionów.

**Wniosek zbiorczy — krzywych Audyssey nie da się wyciągnąć żadną drogą:**
telnet i protokół 1256 nie mają komendy odczytu, firmware jest zaszyfrowane,
a tryb serwisowy jest front-panel. Odpowiedź na „skąd górka" daje wyłącznie
pomiar różnicowy ON/OFF z zakładki Pomiar.

## Ograniczenia ustalone empirycznie

- Odległości głośników **czyta i ustawia `SSSDE`**, krok 1 cm, każdy sub osobno.
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
- [ ] Zestrojenie subwooferów **akustycznie** — sterowanie odległością
      sprawdzone na sprzęcie, silnik na symulacji, ale przemiatania
      z mikrofonem jeszcze nikt nie uruchomił
- [ ] `ENTER_AUDY` / `EXIT_AUDMD` — komendy potwierdzone jako istniejące,
      ale NIEURUCHOMIONE. Wejście w tryb kalibracji ryzykuje nadpisanie
      obecnych krzywych, więc czeka na moment planowanej rekalibracji
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
