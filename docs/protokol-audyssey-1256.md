# Protokół Audyssey MultEQ Editor — port 1256

Drugi kanał sterowania, niezależny od telnetu. Telnet daje **nastawy**,
ten daje **dane kalibracji**: odpowiedzi impulsowe i wgrywanie własnych
współczynników filtrów.

## Sprostowanie

Wcześniej twierdziłem w tym projekcie, że z wzmacniacza nie da się wyciągnąć
danych pomiarowych i że komunikacja jest jednokierunkowa. **To było błędne.**
Kanał jest dwukierunkowy i odpowiada JSON-em. Poniżej wszystko zweryfikowane
na AVR-X3300W.

## Otwarte porty

Skan 10 009 portów na `192.168.0.73` dał osiem otwartych:

```
80    HTTP — /goform/*.xml, Deviceinfo.xml
443   HTTPS
1024
1256  ← protokół Audyssey MultEQ Editor
5000
5001  (wita bajtem ">")
6666
8080  UPnP / DLNA MediaRenderer
```

Telnetu (23) w tym skanie nie ma, bo trzymała go własna instancja aplikacji —
amplituner przyjmuje **jedno** połączenie telnet naraz.

## Format ramki

```
54 | 00 13 | 00 00 | "GET_AVRINF" | 00 00 00 | <ładunek> | 6c
'T'  dł.=19  rezerwa   komenda 10 B   dł.=0       JSON/bin   suma
```

| Bajty | Znaczenie |
|---|---|
| 0 | marker: `0x54` ('T') w żądaniu, `0x52` ('R') w odpowiedzi |
| 1–2 | długość **całej** ramki, big-endian |
| 3–4 | zera |
| 5–14 | nazwa komendy, 10 bajtów, dopełniona spacjami |
| 15–17 | długość ładunku, 3 bajty big-endian |
| … | ładunek: JSON albo float32 |
| ostatni | suma wszystkich poprzednich bajtów **mod 256** |

Kontrola na `GET_AVRINF`: 0x54+0x13+0x47+0x45+0x54+0x5f+0x41+0x56+0x52+0x49+
0x4e+0x46 = 876; 876 mod 256 = 108 = `0x6c` ✓

## Dwie pułapki

**1. Wyrocznia nazw działa mimo złej sumy kontrolnej.** Wzmacniacz odbija
nazwę komendy, jeśli ją zna, a wpisuje `ERROR`, jeśli nie zna — niezależnie
od tego, czy suma się zgadza. Odpowiedź i tak brzmi `{"Comm":"NACK"}`.
Można tym zmapować cały zestaw komend bez ryzyka, ale łatwo pomylić
rozpoznanie nazwy z sukcesem wywołania.

**2. Pole komendy ma 10 bajtów i obcina dłuższe nazwy.** `GET_RESPON2`
i `GET_RESPONS` „działają" wyłącznie dlatego, że obcinają się do
`GET_RESPON`. To ta sama komenda, nie trzy różne.

**3. Port nie znosi zrównoleglenia.** Przy dwunastu wątkach 452 zapytania
z 544 przepadły bez odpowiedzi. Szeregowo — zero strat.

## Komendy

### Odczyt — bezpieczne

| Komenda | Zwraca |
|---|---|
| `GET_AVRINF` | typ korekcji, czasy, opóźnienie systemowe |
| `GET_AVRSTS` | przypisanie kanałów, stan mikrofonu, końcówki |

### Sesja kalibracji — zmieniają stan urządzenia

| Komenda | Rola |
|---|---|
| `ENTER_AUDY` | wejście w tryb kalibracji |
| `SET_POSNUM` | numer pozycji mikrofonu |
| `START_CHNL` | wyzwolenie sweepu kanału → `{Distance, Level, Freq, PG}` |
| `GET_RESPON` | odpowiedź impulsowa, float32, wiele pakietów |
| `EXIT_AUDMD` | wyjście z trybu kalibracji |

### Zapis współczynników

| Komenda | Rola |
|---|---|
| `INIT_COEFS` | start wgrywania |
| `SET_COEFDT` | 126 liczb float32 na pakiet (531 bajtów) |
| `FINZ_COEFS` | zamknięcie |
| `SET_SETDAT` | nastawy: odległości, poziomy, podziały |
| `SET_AUDYFINFLG` | flaga zakończenia kalibracji |

## Odczytane z AVR-X3300W

```json
GET_AVRINF
{
  "Ifver": "00.08",  "DType": "FixedA",
  "CoefWaitTime": { "Init": 3000, "Final": 0 },
  "ADC": 2.115,      "SysDelay": 280,
  "EQType": "MultEQXT32",
  "SWLvlMatch": true,
  "LFC": false, "Auro": false, "Upgrade": "None"
}

GET_AVRSTS
{
  "HPPlug": false, "Mic": false, "AmpAssign": "Zone2",
  "ChSetup": [ {"FL":"L"}, {"C":"L"}, {"FR":"L"},
               {"SLA":"L"}, {"SRA":"L"},
               {"SWMIX1":"E"}, {"SWMIX2":"E"} ]
}
```

`SWMIX1` i `SWMIX2` — oba subwoofery widziane osobno, zgodnie z
`SSSPCSWF 2SP` po telnecie. `SWLvlMatch: true` potwierdza działające
dopasowanie poziomu subwooferów (Sub EQ HT).

`Mic: false` — mikrofon Denona nie jest wpięty. Pomiar sterowany przez
wzmacniacz (`START_CHNL`) wymaga jego podłączenia, bo to wzmacniacz
nagrywa, nie my.

## Czego NIE da się odczytać

**Gotowych krzywych korekcyjnych.** `SET_COEFDT` jest tylko do zapisu —
nie ma komendy czytającej aktualnie wgrane współczynniki. `GET_RESPON`
zwraca odpowiedzi impulsowe **świeżo zmierzone w sesji kalibracji**,
a nie filtry, które już siedzą w procesorze.

To jednak wystarcza do zamknięcia pełnej pętli: wzmacniacz mierzy, my
odbieramy odpowiedzi impulsowe, liczymy własne filtry i wgrywamy je z
powrotem. Dokładnie tak działa A1 Evo.

## Ryzyko

`ENTER_AUDY` rozpoczyna **nową** kalibrację. Istniejące krzywe Audyssey
mogą zostać nadpisane, a powrót oznacza przejście całej procedury od nowa,
z mikrofonem i wszystkimi pozycjami. Nie wchodzić w ten tryb bez świadomej
decyzji — najlepiej wtedy, gdy i tak planuje się rekalibrację.

Wyjście to `EXIT_AUDMD`. Zostało potwierdzone jako istniejąca komenda,
ale **nie zostało przetestowane w działaniu**.

## Dlaczego płatna aplikacja NIE odczytuje krzywych

Naturalne podejrzenie brzmi: skoro MultEQ Editor pokazuje krzywe do edycji,
to musi je skądś pobierać. **Nie pobiera.**

Model danych pliku `.ady` (klasa `DetectedChannel` w ratbuddyssey) zawiera:

| Pole | Co trzyma |
|---|---|
| `ResponseData` | **zmierzone odpowiedzi impulsowe**, po jednej na pozycję |
| `CustomTargetCurvePoints` | **krzywa docelowa** jako lista punktów |
| `CustomDistance`, `CustomLevel`, `CustomCrossover`, `CustomSpeakerType` | nastawy kanału |
| `MidrangeCompensation`, `FrequencyRangeRolloff` | opcje korekcji |

**Nie ma tam ani jednego pola na współczynniki filtru** — żadnej
częstotliwości, dobroci ani wzmocnienia. Filtry są **wyliczane** z pomiaru
i krzywej docelowej, a nie przechowywane.

Aplikacja rysuje krzywe, bo ma `ResponseData` z sesji pomiarowej, którą sama
przeprowadziła (`ENTER_AUDY` → `START_CHNL` → `GET_RESPON`). Uruchomiona
przeciw amplitunerowi skalibrowanemu wcześniej z menu ekranowego **nie pokaże
tamtych krzywych** — musi zmierzyć od nowa albo wczytać zapisany `.ady`.

To domyka sprawę: nie ma czego odczytywać, bo filtry w postaci edytowalnej
nie istnieją po stronie amplitunera.

## O podsłuchiwaniu ruchu

Pomysł jest słuszny i **został już zrealizowany**: ratbuddyssey zawiera plik
`AudysseyMultEQTcpSniffer.cs` — wbudowany sniffer TCP, którym autorzy
rozłożyli ten protokół. Opisany wyżej format ramki i lista komend to właśnie
wynik tamtej pracy. Kupienie aplikacji i powtórzenie podsłuchu odtworzyłoby
wiedzę już opublikowaną.

## Źródło

Format ramki i lista komend: publiczne repozytorium
[srinivas486/audyssey-rew-tuner](https://github.com/srinivas486/audyssey-rew-tuner),
plik `COMMAND_INVENTORY.md`, opisujące działanie otwartych narzędzi
A1 Evo / OCA. Sąsiednie projekty:
[A1EvoAcoustica](https://github.com/cepage/A1EvoAcoustica),
[ratbuddyssey](https://github.com/VioletGiraffe/ratbuddyssey),
[audyssey_one](https://github.com/BRNKR/audyssey_one).

Płatna aplikacja MultEQ Editor **nie była pobierana ani dekompilowana** —
to zamknięty, komercyjny produkt. Wszystko powyżej pochodzi z otwartych
źródeł i z pomiarów na własnym urządzeniu.
