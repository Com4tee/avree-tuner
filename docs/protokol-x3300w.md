# Protokół AVR-X3300W — ustalenia empiryczne

Wszystko poniżej zweryfikowane na egzemplarzu pod `192.168.0.73`, 2026-09-14.

## Warstwy komunikacji

| Warstwa | Port | Uwagi |
|---|---|---|
| Sterowanie ASCII (telnet) | **23** | jedno połączenie naraz, push zmian stanu w czasie rzeczywistym |
| HTTP `/goform/*` | **80** | **nie 8080** — na tym modelu 8080 zwraca 404 dla `/goform` |
| UPnP MediaRenderer | **8080** | `/description.xml`, `/AVTransport/ctrl`, `/RenderingControl/ctrl`, `/ConnectionManager/ctrl` |
| HEOS CLI | 1255 | **zamknięty** — X3300W nie ma HEOS built-in |

`CommApiVers 0300`. `POST /goform/AppCommand.xml` działa na porcie 80.

## Identyfikacja (`VIALL?`)

```
VIALLAVRX3300W E2        VIALLDSP:02.67
VIALLMAIN:02040085       VIALLAPLD:51.08
VIALLMAINFBL:00.15       VIALLVPLD:52.01
VIALLAUDYIF:00.00        VIALLHWID:0x000000bd
```

`VIALLAUDYIF` to wersja interfejsu Audyssey — trop do kanału uploadu kalibracji.

Firmware: `SSINFFRM ?` → `SSINFFRMAVR 8700-4058-9103`, `SSINFFRMDTS 3.90.50.00`.

## Stan zastany

```
PSMULTEQ:AUDYSSEY     Reference
PSDYNEQ ON            <- podbija górę i dół; główny podejrzany o limitery
PSDYNVOL OFF
PSREFLEV 0
MSDOLBY SURROUND      SIMPLAY, SDHDMI
MV05  MVMAX 80
```

## Konfiguracja głośników

- `CV?` → FL, FR, C, SL, SR — **5 kanałów**, wszystkie 50 (0.0 dB)
- `SSSPC ?` → FRO/CEN/SUA = `LAR` (Large), SWF = `2SP` (dwa suby)
- `SSCFR ?` → FRO/CEN/SUA 060, SBK 080, ALL 100, tryb `IDV`
- `SSSWM L+M` — tryb subwoofera LFE+Main
- `SSLFL 080` — filtr LFE 80 Hz
- `SSPAAMOD ZO2` — dwie końcówki oddane do strefy 2

Wszystkie kanały jako Large + LFE+Main oznacza, że pełne pasmo idzie do kolumn PA
równolegle z subami.

## Odległości głośników — `SSSDE`

**Działa w obie strony: odczyt i zapis.** Sprawdzone na tym egzemplarzu.

`SSSDE ?` zwraca 21 linii — wszystkie pozycje, także te nieużywane w tym
systemie. Wartość to centymetry z sufiksem `M`, czyli `0427M` = 4,27 m.

```
SSSDEFL 0498M   SSSDEFR 0582M   SSSDEC  0403M
SSSDESL 0339M   SSSDESR 0474M
SSSDESW 0427M   ← subwoofer 1
SSSDESW2 0886M  ← subwoofer 2
SSSDESTP 01M    ← krok nastawy: 1 cm
```

**Każdy subwoofer ma własną odległość.** Różnica SW ↔ SW2 wynosi tu 4,59 m,
czyli **13,4 ms** — to nie są odległości fizyczne, tylko opóźnienie policzone
przez Audyssey Sub EQ HT przy kalibracji.

Krok 1 cm to **29 µs** przy prędkości dźwięku 343 m/s. Przy 50 Hz (długość
fali 6,86 m) jeden krok odpowiada przesunięciu fazy o **0,5°**. Rozdzielczość
jest więc o rząd wielkości drobniejsza, niż potrzeba do zestrojenia subów.

Zapis sprawdzony empirycznie:

```
> SSSDESW2 0890M
< SSSDESW2 0890M          echo
> SSSDE ?
< SSSDESW2 0890M          odczyt potwierdza
> SSSDESW2 0886M          przywrócenie
< SSSDESW2 0886M
```

Zmiana odległości **nie unieważnia filtrów Audyssey** — to osobna warstwa
nastaw. Krzywe korekcyjne zostają, zmienia się tylko opóźnienie kanału.

### Poziomy subwooferów — osobne, ale zależne od trybu

`CV?` daje `CVSW 50` i `CVSW2 50` — poziom każdego suba z osobna.
`PSSWL ?` daje `PSSWL 50` i `PSSWL2 50`.

Uwaga na pułapkę: `CV?` listuje **tylko kanały aktywne w bieżącym trybie
dźwięku**. Wcześniejszy pomiar dał 5 kanałów bez subwooferów, bo wzmacniacz
stał wtedy w trybie stereo. To nie był brak funkcji, tylko brak kontekstu.

### Czego Deviceinfo.xml nie mówi

`Deviceinfo.xml` podaje `SubwooferNum 1` i nie ma w nim ŻADNEGO tagu
odległości — tylko `AudioDelay` i `DelayTime`, czyli lip-sync. Ten manifest
opisuje, czego używa aplikacja Denona, a **nie** pełne możliwości telnetu.
Wniosek: nieobecność w Deviceinfo.xml nie jest dowodem na brak funkcji.

## Komendy, które NIE odpowiadają na tym modelu

`DC?`, `PSLFC ?`, `PSCNTAMT ?`, `PSTONECTRL ?`, `SSFRQ ?`, `SSSPCFRO ?`,
`SSPAAMOD ?` (działa `SSPAA ?`), `SSINFAISFIL ?`, `SSHOSIFP ?`, `SYMO ?`,
`SSDST ?` — ale to **zły mnemonik**, nie brak funkcji. Odległości czyta i ustawia
`SSSDE` (patrz niżej). Wcześniejszy wpis mówiący, że odległości są niedostępne
po telnecie, był **błędny**.

`SSSOD ?` to lista **źródeł** (USE/DEL), nie trybów dźwięku.

## UPnP — co renderer przyjmuje

`ConnectionManager#GetProtocolInfo` → 28 pozycji w `Sink`:

```
audio/flac  audio/x-flac  audio/wav  audio/x-wav  audio/aiff  audio/x-aiff
audio/mpeg  audio/mp4  audio/x-m4a  audio/x-mp4  audio/vnd.dlna.adts
audio/x-ms-wma  audio/dsd  audio/x-dsd  audio/3gpp
audio/L16;rate=44100;channels=1|2   audio/L16;rate=48000;channels=1|2
image/jpeg
```

**Brak AC3, E-AC3, DTS.** Renderer sieciowy jest stereo; L16 maksymalnie 48 kHz / 2 kanały.
Materiał wielokanałowy wymaga HDMI (bitstream) albo optyki.

## Deviceinfo.xml

`GET http://<ip>/goform/Deviceinfo.xml` — 64 kB manifestu możliwości: `DeviceCapabilities`,
`ChannelLevel/ChLists` (zakresy i kroki per kanał), `SubwooferLevel`, `Audyssey`
(z `MultEq`/`DynamicEq`/`RefLevOffset`/`DynamicVolume` i kodami `CmdNo`), `SurroundParameter`.
Potwierdza `MultEQ XT32`.

To jest samoopisujący się model urządzenia — GUI powinno budować się z niego,
a nie z zaszytych na sztywno list.

## Equalizer graficzny — ustalenia

`PSGEQ ON/OFF` **działa**, ale wyłącznie przy `PSMULTEQ:OFF`. Wysłanie `PSGEQ ON`
przy włączonym Audyssey nie daje żadnego efektu — oba equalizery wykluczają się
wzajemnie. Kolejność, która przechodzi:

```
PSMULTEQ:OFF     ->  PSMULTEQ:OFF
PSGEQ ON         ->  PSGEQ ON
```

**Wartości dziewięciu pasm nie są adresowalne po sieci.** Przetestowane i milczące:
`PSGEQFL63`, `SSGEQFL63`, `PSGEQ FL 63`, `SSGEQFL 63`, `PSGEQ6355`, a także zapytania
`SSGEQ ?`, `PSGEQFL ?`, `SSEQ ?`, `PSEQ ?`, `SSAEQ ?`, `PSGEQ:?`. Suwaki istnieją
wyłącznie w menu ekranowym.

Trybu `PSMULTEQ:MANUAL` ten model nie ma — Deviceinfo.xml wymienia tylko Reference,
L/R Bypass, Flat i Off, a komenda jest odrzucana.

## Pełna enumeracja ustawień (65 kandydatów, 40 odpowiada)

Odpowiadają i są sterowalne:

```
PSMULTEQ:  PSDYNEQ  PSDYNVOL  PSREFLEV      Audyssey
PSGEQ                                       equalizer graficzny (ON tylko przy MultEQ OFF)
PSCINEMA EQ.  PSCES  PSLOM  PSNEURAL        parametry przestrzenne
PSDRC  PSDCO  PSEFF  PSRSZ  PSDEL           dynamika, efekt, rozmiar pomieszczenia
PSBAS  PSTRE  PSTONE CTRL                   barwa
PSLFE  PSDIL  PSDIC  PSSWL  PSSWR  PSCLV    poziomy
SSSPC  SSCFR  SSSWM  SSLFL  SSLEV  CV  SSPAA  konfiguracja głośników
SSAST  SSLAN  SSLOC  SSHOS  SSSMG  SSQSNZMA   system
SSINFAISSIG  SSINFAISFSV  SSINFFRM  VIALL  NSFRN   informacje
```

Milczą — tych funkcji X3300W nie ma:

```
PSLFC  PSCNTAMT           Audyssey LFC i Containment Amount (wyższe modele)
PSDSX  PSSTW  PSSTH  PSDEH   Audyssey DSX (wycofane wraz z Atmosem)
PSMDAX  PSATT  PSPHG  PSSP:  PSVOL
SSGEQ i pochodne          pasma equalizera graficznego
SSSPDIF  SSBAS  SSECO  SSTPD  SSTRG
```
