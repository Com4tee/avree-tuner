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

## Komendy, które NIE odpowiadają na tym modelu

`DC?`, `PSLFC ?`, `PSCNTAMT ?`, `PSTONECTRL ?`, `SSFRQ ?`, `SSSPCFRO ?`,
`SSPAAMOD ?` (działa `SSPAA ?`), `SSINFAISFIL ?`, `SSHOSIFP ?`, `SYMO ?`,
`SSDST ?` (odległości głośników **niedostępne** po telnecie).

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
