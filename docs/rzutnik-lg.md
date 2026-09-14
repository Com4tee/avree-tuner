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
