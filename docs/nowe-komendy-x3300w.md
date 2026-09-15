# Szesnaście nieudokumentowanych komend AVR-X3300W

Wynik systematycznego przemiatu przestrzeni nazw komend, przeprowadzonego
**dwoma niezależnymi metodami**, które dały zgodny wynik. Wszystko zmierzone
na własnym egzemplarzu, nie przepisane z cudzych źródeł.

Publikujemy to, bo sami zaczęliśmy od wiedzy udostępnionej przez innych
(ratbuddyssey, A1 Evo, OCA). To jest oddanie długu.

## Metoda

Przemiot obejmował **pełną przestrzeń `SS` + 3 litery i `PS` + 3 litery** —
po 17 576 kombinacji każda. Wysyłano wyłącznie **zapytania** (`<nazwa> ?`),
nigdy nastaw.

Dwa niezależne tory:

1. **Port 5000** — drugi kanał sterowania, paczkami po 30 komend.
2. **Port 23** — przez własną aplikację, paczkami po 22.

Oba dały **identyczny zestaw 15 komend `SS`**. Zgodność dwóch niezależnych
metod jest tu jedynym sensownym dowodem poprawności.

### Kontrola, bez której wynik jest bezwartościowy

Pierwsza wersja przemiatu na porcie 1256 **była zepsuta i tego nie widać było
po wyniku**: potokowała ramki na jednym połączeniu, a wzmacniacz odpowiadał
tylko na pierwszą rozpoznaną komendę i po cichu gubił resztę. Zwracała
„zero trafień" — wynik wyglądający jak rzetelny negatyw.

Wykryła to dopiero **kontrola**: wśród śmieciowych nazw wstawiono znane
komendy i sprawdzono, czy zostaną wykryte. Nie zostały.

Od tego czasu każdy przemiat:
- zaczyna się od kontroli znaną komendą i przerywa, jeśli nie przejdzie,
- powtarza kontrolę co 150 nazw,
- wypisuje trafienia **natychmiast**, a nie na końcu.

Przemiat `PS` przerwał się sam na 13 200/17 554, bo kontrola padła. Zamiast
oddać niepełny wynik jako pełny, zatrzymał się — brakujący zakres przemierzono
osobno po restarcie.

**Przemiat, który nic nie znalazł, a nie miał kontroli, nie dowodzi niczego.**

## Komendy wejść i źródeł

Wszystkie przyjmują nazwę źródła: `DVD`, `BD`, `TV`, `SAT/CBL`, `MPLAY`,
`GAME`, `AUX1`, `AUX2`, `CD`, a `SSSLD` dodatkowo `TUNER`, `NET`, `BT`.

| Komenda | Znaczenie | Przykład z urządzenia |
|---|---|---|
| `SSHDM` | przypisanie wejścia **HDMI** | `SSHDMBD HD3`, `SSHDMDVD HD2`, `SSHDMMPLAY HD5`, `SSHDMAUX2 HD6`, `SSHDMAUX1 FRO` |
| `SSANA` | przypisanie wejścia **analogowego** | `SSANABD AN3`, `SSANACD AN5`, `SSANASAT/CBL AN1` |
| `SSDIN` | przypisanie wejścia **cyfrowego** | `SSDINDVD OFF` |
| `SSVDO` | przypisanie wejścia **wideo** | `SSVDOGAME VD3` |
| `SSCMP` | przypisanie wejścia **component** | `SSCMPBD OFF` |
| `SSCNV` | **konwersja wideo** per źródło | `SSCNVBD ON` |
| `SSSLD` | **poziom źródła** (trym wejścia) | `SSSLDDVD 50` — skala Denona, 50 = 0,0 dB |

`SSSLD` jest z nich najciekawsza praktycznie: pozwala wyrównać głośność
między źródłami bez dotykania poziomów kanałów.

## Odległości głośników wysokościowych

| Komenda | Znaczenie |
|---|---|
| `SSDSS` | odległość głośników **Dolby-enabled** — `SSDSSFRD 0180M`, `SSDSSSUD 0180M` |

Ten sam format co `SSSDE` (centymetry z sufiksem `M`), osobna rodzina dla
głośników odbijających. `FRD` = front Dolby, `SUD` = surround Dolby.

## Synchronizacja obrazu i dźwięku

| Komenda | Znaczenie |
|---|---|
| `SSALS` | **Auto Lip Sync**: `SSALSSET ON` (włączony), `SSALSDSP OFF` (podgląd), `SSALSVAL 000` (wartość w ms) |

## Menu ekranowe

| Komenda | Znaczenie |
|---|---|
| `SSOSD` | `SSOSDVOL BOT` (gdzie głośność), `SSOSDTXT ON` (komunikaty), `SSOSDFMT PAL` (format), `SSOSDPBS ALW` (pasek odtwarzania) |

## Pozostałe — znaczenie nieustalone

Odpowiadają stabilnie, ale znaczenia **nie potwierdziliśmy**. Podajemy je
takimi, jakie są, zamiast zgadywać:

| Komenda | Odpowiedź | Podejrzenie |
|---|---|---|
| `SSFRS` | `SSFRSDST SPA` | przeznaczenie kolumn przednich |
| `SSGCF` | `SSGCFDVD 24`, `SSGCFDVE 18`, `SSGCFDVM 10` | konfiguracja wideo / gamma |
| `SSINA` | `SSINA YES` | flaga obecności wejścia |
| `SSSIM` | `SSSIM 6HM` | kod układu głośników |
| `SSSUD` | `SSSUD NO` | obecność głośników surround Dolby |
| `PSHEQ` | `PSHEQ OFF` | korekcja dla słuchawek |
| `SSINFCON` | `SSINFCON NON` | informacja o połączeniu |

## Pułapka druga: echo to nie odpowiedź

Rodzina `SY` dała **26 „trafień", z których wszystkie były fałszywe**.
„Odpowiedzią" była dosłownie wysłana komenda: na `SYCBF ?` wracało `SYCBF ?`.

To nie jest odpowiedź na zapytanie — to potwierdzenie **zapisu**. Komendy
`SYCB` + litera przyjmują parametr, a znak `?` został potraktowany jako
wartość, nie jako pytanie. Dla porównania `SYZZZ ?` i `SYQQQ ?` milczą
całkowicie, więc echo nie jest zachowaniem ogólnym całej rodziny.

Dwa wnioski:

1. **Detekcja trafień musi odrzucać echo.** Odpowiedź identyczna z wysłaną
   komendą nie jest odpowiedzią.
2. **Przemiatu `SY` nie dokończono świadomie.** Ta rodzina zachowuje się jak
   zbiór setterów, a przemiatanie setterów oznacza wysyłanie przypadkowych
   wartości do cudzego urządzenia. Po zatrzymaniu sprawdzono wszystkie
   istotne nastawy (odległości, poziomy, konfiguracja, podziały, tryby
   Audyssey, tryb subwoofera) — **wszystkie nienaruszone**.

## Czego NIE ma

Przemiat objął łącznie około **72 000 nazw komend**:

| Przestrzeń | Liczba | Nowych |
|---|---|---|
| `SS` + 3 litery | 17 576 | 15 |
| `PS` + 3 litery | 17 576 | 1 (`PSHEQ`) |
| `MN` + 3 litery | 17 576 | 0 |
| `SSINF` + 3 litery | 17 576 | 1 (`SSINFCON`) |
| protokół 1256, nazwy odczytowe | ~2 100 | 0 |
| `SY` + 3 litery | przerwane | — |

Do tego 10 009 portów TCP, 2 000 portów UDP i 1 090 ścieżek HTTP.

Nie istnieje żadna komenda odczytująca:

- współczynniki filtrów korekcyjnych,
- krzywe MultEQ zapisane w procesorze,
- surowe dane pomiarowe z przeprowadzonej kalibracji.

Przestrzeń `MN` przemierzono w całości — zero trafień poza dziewięcioma
znanymi komendami nawigacji.

## Porty

Skan 10 009 portów TCP oraz 2 000 portów UDP:

| Port | Co tam jest |
|---|---|
| 80 | HTTP, `/goform/*.xml`, `Deviceinfo.xml` |
| 443 | otwarty, ale **nie jest to działający TLS** (zrywa połączenie) |
| 1024 | AirPlay (`AirTunes/190.9`) |
| 1256 | protokół Audyssey MultEQ Editor |
| 5000 | **drugi kanał sterowania** — ten sam protokół ASCII co telnet 23, ale osobne gniazdo; wystawia też ekran komendą `NSE` |
| 5001 | konsola z promptem `>`, odpowiada `error: unknown command`; nie zna żadnego z 49 przetestowanych słów |
| 6666 | otwarty, milczy na wszystko |
| 8080 | UPnP / DLNA MediaRenderer |

**UDP: cisza na całej linii.** Ani SSDP (1900), ani mDNS (5353), ani SNMP
(161), ani NTP, ani TFTP. Przemiat 1–2000 bez jednej odpowiedzi.

Port 5000 jest praktycznie cenny: port 23 przyjmuje **jedno** połączenie
naraz, więc aplikacja sterująca go blokuje. Port 5000 pozwala czytać stan
równolegle, bez odbierania nikomu sterowania.

## Do sprawdzenia przez innych

- Czy `SSGCF`, `SSSIM`, `SSINA`, `SSSUD`, `SSFRS` znaczą to, co podejrzewamy.
- Czy te komendy odpowiadają na innych modelach z tej generacji.
- Rodzina `SY`, a zwłaszcza `SYCB` + litera — co ustawia i czy da się
  ją odczytać bezpieczną składnią. My nie kontynuowaliśmy, bo to settery
  na cudzym urządzeniu.
- Czy `SSSLD` faktycznie zmienia głośność źródła (u nas tylko odczytane).
