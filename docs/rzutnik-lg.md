# Rzutnik LG — rozpoznanie sieciowe

Skan przy urządzeniach włączonych. Wszystko zweryfikowane, nic nie jest założeniem.

## Sprostowanie

W pierwszym podejściu wskazałem `192.168.0.70` jako rzutnik, bo miał MAC z puli
LG i otwarty port 9741. **To był błędny wniosek.** Szukałem po producencie, a nie
po funkcji — a w tej sieci są trzy urządzenia LG. Skan całej podsieci pod kątem
portów webOS wykazał dwa inne hosty, i dopiero jeden z nich jest rzutnikiem.

## Rzutnik: `192.168.0.75`

| | |
|---|---|
| Nazwa | `[LG] lodownia` |
| Model | `DBF510P-GL` |
| System | webOS |
| MAC | `b0:37:95:2e:4e:05` |
| Otwarte porty | **3000, 3001**, 18181, 36866 |

Cztery opisy UPnP na własnych portach (1292, 1326, 1388, 1974), w tym
`LG WebOSTV DMRplus` — pełny stos webOS z renderowaniem mediów.

### SSAP jest otwarty

```
GET / HTTP/1.1  +  Upgrade: websocket   ->   HTTP/1.1 101 Switching Protocols
```

To zmienia plan na dużo lepszy. Protokół SSAP (`ws://ip:3000`, `wss://ip:3001`)
daje pełne sterowanie: wyłączanie, przełączanie wejść, głośność, uruchamianie
aplikacji, powiadomienia na ekranie, wskaźnik. Jest otwarty i udokumentowany —
nie trzeba keycode ani szyfrowanego IP Control.

Parowanie: przy pierwszym połączeniu urządzenie wyświetla pytanie na ekranie.
Po akceptacji dostajemy klucz klienta i używamy go bezterminowo.

**Ograniczenie:** SSAP potrafi wyłączyć, ale nie włączyć — w czuwaniu urządzenie
zwykle zwija interfejs sieciowy. Do włączania służy Wake-on-LAN na powyższy MAC,
o ile w menu włączone jest budzenie przez sieć.

## Drugie urządzenie webOS: `192.168.0.78`

Porty 3000, 3001, 18181, 36866 — ten sam podpis co rzutnik. `GET /` na porcie
3000 zwraca `Hello world`, czyli odpowiedź usługi SSAP.

Nie ogłasza własnego opisu UPnP, więc modelu nie ustaliłem. Z układu sieci
wynika, że to **telewizor LG** — ale tego nie potwierdziłem i nie należy tego
traktować jako faktu.

## Trzecie urządzenie LG: `192.168.0.70`

| | |
|---|---|
| Nazwa Cast | `Bedroom LG` |
| MAC | `98:93:CC:8D:32:76` |
| Otwarte porty | 8008, 8009, 8012, 8443, 9000, 9741, 10001 |
| Połączenie | Wi-Fi, SSID `GROM` (`ethernet_connected: False`) |

Ma **Chromecast built-in** — certyfikat z portu 8443 zawiera `LG Electronics`,
`Seoul`, jednostkę `Cast` i nazwę `"LG Electronics 2019LaunchWK7V"`.
Port 8008 oddaje pełne dane urządzenia bez żadnego uwierzytelnienia:

```
GET http://192.168.0.70:8008/setup/eureka_info?options=detail
```

Ma też otwarty port **9741** (LG IP Control, AES-128, wymaga keycode) — to on
mnie zmylił. Port 9000 wymaga certyfikatu klienta i jest zamknięty.

Rzutnik i telewizor **nie mają** Chromecasta — to czysty webOS.

## Pozostałe urządzenia Cast w sieci

| Adres | Nazwa | Uwaga |
|---|---|---|
| `.51` | Living room soundsystem | Chromecast Audio |
| `.58` | **Kino Lodownia** | build 3.72 — to jest Google TV od rzutnika |
| `.59` | Kitchen | Nest Audio |
| `.64` | Den Speaker | Google Home Mini |
| `.74` | Denon Bed | Chromecast Audio |
| `.73` | — | amplituner Denon AVR-X3300W |

## Plan

Sterowanie rzutnikiem przez **SSAP na `192.168.0.75`**. Jedno parowanie
z potwierdzeniem na ekranie, potem stały klucz klienta. Do włączania Wake-on-LAN.

Port 9741 na `.70` i szyfrowany IP Control przestają być potrzebne.


---

# Sterowanie — co udało się rozpracować

## Uścisk WebSocket: pułapka z nagłówkiem Origin

webOS weryfikuje `Origin` i zrywa połączenie kodem **1008 `invalid origin`**.
Przetestowane warianty:

| Origin | Wynik |
|---|---|
| brak nagłówka | CLOSE 1002 |
| pusty | 1008 invalid origin |
| `http://<host>` | 1008 invalid origin |
| `ws://<host>:3000` | 1008 invalid origin |
| `com.lge.test` | 1008 invalid origin |
| **`null`** | **przechodzi** |
| `file://` | przechodzi |

## Uprawnienia zależą od manifestu przy KAŻDYM połączeniu

Nie tylko przy pierwszym parowaniu. Zawężenie listy uprawnień w manifeście
odbiera dostęp mimo ważnego klucza klienta — przekonałem się o tym, gdy
rozszerzyłem manifest doraźnie w jednym skrypcie, a kolejny znów dostał 401.
Lista musi być kompletna na stałe w module.

## Usługi SSAP na tym modelu

```
api  audio  config  externalpq  media.controls  media.viewer
pairing  settings  system  system.launcher  system.notifications
timer  tv  user  webapp
```

### Co odpowiada

| Endpoint | Efekt |
|---|---|
| `ssap://system/getSystemInfo` | model DBF510P-GL |
| `ssap://com.webos.service.tvpower/power/getPowerState` | Active / Suspend |
| `ssap://audio/getVolume`, `getStatus`, `setVolume`, `setMute` | głośność |
| `ssap://tv/getExternalInputList`, `switchInput` | HDMI_1/2/3 |
| `ssap://com.webos.applicationManager/listLaunchPoints` | 4 aplikacje |
| `ssap://system.launcher/launch` | uruchamianie |
| `ssap://system/turnOff` | wyłączenie |
| `ssap://system.notifications/createToast` | napis na ekranie |
| **`ssap://com.webos.service.networkinput/getPointerInputSocket`** | **gniazdo pilota** |

### Co nie odpowiada

`ssap://timer/*` — usługa figuruje na liście, ale wszystkie metody zwracają
404. `ssap://config/getConfigs` — 401 nawet z pełnym manifestem.
`ssap://system.launcher/getAppState` — 403. `getCurrentSWInformation` — 401.

### Ustawienia systemowe

`getSystemSettings` wymaga jawnej listy kluczy; sama kategoria albo pusta
lista dają `500 Application error`. Jeden nieistniejący klucz wywala całe
zapytanie, więc trzeba pytać pojedynczo.

Istnieją na tym modelu:

```
network : deviceName = [LG] lodownia,  wolwowlOnOff = true
picture : backlight, brightness, color, contrast
option  : audioGuidance, country, zipcode
```

**Kluczy timerów nie ma.** Sprawdziłem 34 nazwy w 8 kategoriach
(`autoPowerOff`, `sleepTime`, `autoStandbyMode`, `noSignalPowerOff`,
`powerOffBySignal`, `screenOff`, `idlePowerOff` i dalsze) — zero trafień.
Licznika auto-wyłączania po prostu nie da się ustawić po sieci.

## Gniazdo pilota

```
ssap://com.webos.service.networkinput/getPointerInputSocket
  -> ws://<host>:3000/resources/<token>/netinput.pointer.sock
```

Drugie połączenie WebSocket pod tę ścieżkę, protokół tekstowy:

```
type:button
name:HOME
<pusta linia>
```

Dostępne też `type:move` z `dx`/`dy`, `type:click`, `type:scroll`.
42 nazwy przycisków — pełny pilot bez podczerwieni.

## Obejście auto-wyłączania

Skoro ustawienia nie ma, zerujemy licznik u źródła: `type:move` z `dx:0 dy:0`.
Dla urządzenia to zdarzenie wejściowe, na ekranie nie dzieje się nic.
Aplikacja wysyła je w regulowanym odstępie (domyślnie 30 min).

To obejście oparte na mechanizmie działania licznika — potwierdzenia
w praktyce wymaga dopiero dłuższy seans.


---

# Android TV Remote v2 — Google TV

Sparowane z `192.168.0.58` („Kino Lodownia").

## Protokół

Dwa porty, oba TLS z **certyfikatem klienta** (samopodpisanym, generowanym raz
i zapamiętywanym — jego utrata oznacza parowanie od nowa):

| Port | Rola |
|---|---|
| 6467 | parowanie, jednorazowo, kodem z ekranu |
| 6466 | pilot, połączenie trwałe |

Ramki: długość jako **varint** (nie cztery bajty, jak w Cast), potem protobuf.

## Bajt kontrolny — jak uniknąć zgadywania

Sekret parowania to SHA-256 z modulusa i wykładnika obu kluczy publicznych
plus kodu z ekranu. Problem: oryginał jest w Javie i używa
`BigInteger.toByteArray()`, które dokleja wiodące zero dla liczb dodatnich
z ustawionym najstarszym bitem. Porty na inne języki robią to różnie i łatwo
trafić w zły wariant.

Ratunek: **pierwszy bajt skrótu musi równać się pierwszemu bajtowi kodu**.
Dzięki temu poprawność obliczeń sprawdza się LOKALNIE, zanim cokolwiek poleci
do urządzenia. Liczymy więc skrót dla wszystkich wariantów kodowania liczb
i wybieramy ten, który przechodzi test — zamiast próbować kolejnych wersji
na cudzym ekranie.

Zadziałało za pierwszym razem, kod `DC0B1C`.

## Podtrzymywanie połączenia

Urządzenie wysyła okresowe pingi i **rozłącza, gdy zostaną bez odpowiedzi**.
Samo wysyłanie klawiszy nie wystarcza — potrzebny jest wątek, który cały czas
czyta ramki i odbija pingi. Bez niego połączenie padało po dwóch naciśnięciach.

Nawet z wątkiem urządzenie zamyka bezczynne połączenie po ok. 30 sekundach.
Nie jest to problem: `press()` odtwarza połączenie samo, co zostało sprawdzone
(klawisz, 30 s przerwy, kolejne dwa klawisze — wszystkie doszły).

## Klawisze

37 kodów systemowych Androida: nawigacja, Home, Back, Menu, Szukaj, Asystent,
przełącznik aplikacji, sterowanie odtwarzaniem, głośność, wyciszenie,
zasilanie, cyfry, kanały, przewodnik.
