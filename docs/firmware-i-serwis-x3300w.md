# Firmware i tryby serwisowe — co się da, a czego nie

Wynik analizy oryginalnych obrazów firmware (rodzina AVR-X2000/X3000, ten sam
kontener co X3300W) oraz oficjalnego dokumentu serwisowego Denon/Marantz.
Cel był jeden: dojść do krzywych korekcji Audyssey inną drogą niż pomiar.
**Nie udało się** — poniżej dokładnie dlaczego, żeby nikt nie tracił na to
czasu drugi raz.

## Kontener firmware: `host` + ECB, blok 8 bajtów

Każdy plik aktualizacji ma ten sam kształt:

```
"host" | 4 bajty (0x00000400) | ciało zaszyfrowane
 magic   parametr bloku          ECB, blok 8 B
```

Pliki w paczce: `MAIN.bin`, `DSP.bin`, `APLD.bin`, `SUB.bin`, `GUI.bin`,
`IMG.bcd`, `SBL.bcd`, `enc_update.xml`.

### Dowody, że to prawdziwy szyfr blokowy w ECB

1. **Blok ośmiu zer szyfruje się zawsze tak samo.** `f8c5fca0b8c11d7b`
   pojawia się identycznie w `MAIN/DSP/GUI/SUB` — w `GUI.bin` aż 803 957 razy.
   To podpis trybu ECB: każdy blok szyfrowany osobno, bez wektora IV.
2. **Dwa klucze.** `MAIN/DSP/GUI/SUB` mają szyfr zer `f8c5fca0b8c11d7b`,
   a `IMG.bcd/SBL.bcd` inny — `e6f02b21fbb1ca92`. Osobny klucz na kod
   i osobny na obrazy systemu plików.
3. **To NIE jest XOR ze stałym kluczem.** Odszyfrowanie XOR-em szyfru zer
   dało 36% ASCII, zero mnemoników, a każda z ośmiu kolumn bajtów ma pełny
   rozkład 256 wartości z maksimum 10,4%. XOR na kodzie zostawiłby wyraźną
   strukturę kolumnową — nie ma jej.
4. Blok 8-bajtowy wskazuje rodzinę **DES / 3DES / Blowfish**, nie AES
   (ten ma 16 B).

### Wniosek

Bez klucza nie da się odszyfrować, a klucza nie ma w obrazie ani publicznie
(sprawdzone: żaden znany deszyfrator nie obsługuje tego kontenera). Atak
brute-force na DES/3DES jest niewykonalny. **To ślepa uliczka — ale pewna,
nie zgadnięta.** Sam kontener jest tu udokumentowany, żeby oszczędzić pracy
następnym.

## Aktualizacja przez USB

Z instrukcji `AVR-X3000ALL - USB.pdf`:

- Nośnik FAT16/FAT32, folder `firmwares/<ProductID>/` w katalogu głównym.
- **Odłączyć kabel LAN na czas aktualizacji.**
- Wejście: w standby przytrzymać **`STATUS` + `TUNER PRESET CH -`** i włączyć.
- Na wyświetlaczu: `USB Update Start` → `ENTER` → `Update File Check` →
  `Updating Complete`. Około godziny.
- Aktualizacja **może zresetować ustawienia GUI** — instrukcja sama każe
  spisać nastawy przed nią.

### Product ID według regionu (rodzina X3000)

| Region | Kod | Product ID |
|---|---|---|
| Ameryka Płn. | E3 | `000100650100` |
| Europa | E2 | `000100650200` |
| Chiny | E1C | `000100650500` |

Firmware jest **wiązane z regionem** przez Product ID — to samo urządzenie
w różnych regionach dostaje inny obraz.

## Tryby serwisowe AVR-X3300W

Z oficjalnego arkusza Denon/Marantz „Resets & Special Modes" (marzec 2020).
Wszystkie **z wyłączonych stref, w standby**: przytrzymać przyciski i włączyć.

| Funkcja | Kombinacja | Uwaga |
|---|---|---|
| **Reset mikroprocesora** | `TUNER PRESET CH +` / `TUNER PRESET CH -` | miękki reset, NIE czyści kalibracji |
| **Reset fabryczny** | `ZONE 2 SOURCE` / `DIMMER` | **CZYŚCI WSZYSTKO — unikać** |
| Reinicjalizacja sieci | Power On → źródło Online Music → `DIMMER`+`CURSOR RIGHT` aż „Initialized" | usuwa dane logowania |
| Historia zabezpieczeń / **Service Mode** | przytrzymać przyciski przy włączaniu → strzałką w dół do „2.Protection" → ENTER | tylko wyświetlacz FL |
| Wersja firmware | `CURSOR LEFT` / `CURSOR RIGHT` | |
| Kopia / odtworzenie pamięci | „Use Web Control" | patrz niżej |

### Dlaczego Service Mode nie pomaga z EQ

Tryb serwisowy X3300W to **funkcja wyświetlacza czołowego** — pokazuje kody
zabezpieczeń (Therm/ASO/DC) i historię, nawiguje się go przyciskami na
obudowie. Nie jest dostępny po sieci i nie wystawia danych kalibracji.

### „Memory Backup: Use Web Control" — sprawdzone, ślepe

Dokument podaje dla kopii i odtworzenia pamięci „Use Web Control". Sprawdziłem
`formMemoryBackup.xml`, `formBackup.xml`, `AVR_backup` i pochodne, GET i POST,
porty 80 i 8080 — **wszystkie zwracają tę samą stronę „Document Error" co
ścieżka nieistniejąca**. Nie ma lokalnego endpointu zrzutu pamięci. „Web
Control" oznacza tu synchronizację przez konto HEOS, która i tak nie zawiera
surowych filtrów Audyssey.

## Podsumowanie: krzywych EQ nie da się wyciągnąć

Trzy niezależne drogi, wszystkie zamknięte:

1. **Telnet / protokół 1256** — nie ma komendy odczytu współczynników
   (przemiat ~72 000 nazw, potwierdzone).
2. **Firmware** — zaszyfrowany ECB, klucz nieznany i niepubliczny.
3. **Tryb serwisowy / Web Control** — front-panel albo chmura HEOS, żadne
   nie wystawia EQ po sieci.

Jedyna realna droga do zobaczenia, co Audyssey zrobiło z pasmem, pozostaje
**pomiar różnicowy ON/OFF** — już zbudowany w zakładce Pomiar. Mierzy skutek
akustyczny korekcji, co jest odpowiedzią na pytanie „skąd górka", nawet jeśli
nie jest odczytem samych filtrów.

## Źródła

- Oryginalne obrazy firmware X2000E2/X3000E2/X3000E3 (paczki USB Denona)
  oraz `AVR-X3000ALL - USB.pdf` — dostarczone przez właściciela urządzenia.
- Denon/Marantz „Resets & Special Modes", marzec 2020 — dokument oficjalny,
  hostowany na marantz.com.

Obrazów firmware ani dokumentu Denona **nie ma w tym repozytorium** — to
materiały producenta. Powyżej są wyłącznie ustalenia z ich analizy.
