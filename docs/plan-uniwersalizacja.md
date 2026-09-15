# Plan uniwersalizacji — od „mojego kina" do centrum sprzętu sieciowego RTV

Cel: przestać być aplikacją pod jeden egzemplarz Denon AVR-X3300W i stać się
uniwersalnym centrum zarządzania sieciowym sprzętem RTV — dowolny Denon/Marantz
z linii, rzutniki po standardzie PJLink, telewizory i rzutniki LG, urządzenia
Cast/Google Home, Android TV. Z automatycznym wyszukiwaniem w LAN, wyzwalaniem
parowania i listą kompatybilności rozszerzalną przez społeczność.

Ten dokument jest mapą refaktoru, nie jego wykonaniem. Dobra wiadomość, która
za nim stoi: **80% pracy protokołowej już jest zrobione i z natury jest
generyczne** — trudność leży w abstrakcji, nie w pisaniu protokołów od nowa.

## 1. Co już mamy i co z tego jest generyczne

| Moduł | Stan | Jak bardzo generyczny |
|---|---|---|
| `discovery.py` | SSDP, skan podsieci, identyfikacja przez `Deviceinfo.xml` | **Fundament auto-searchu.** `Discovered` już trzyma model/nazwę/host |
| `telnet.py` + `avr.py` | sterowanie Denon ASCII | Protokół ASCII jest **wspólny dla całej linii Denon/Marantz** od ~2010 |
| `audyssey.py` | protokół 1256 (MultEQ Editor) | Wspólny dla wszystkich modeli z MultEQ |
| `upnp.py` | renderer DLNA | Standard — działa z dowolnym MediaRenderer |
| `cast.py` | Cast v2 (`CastHub`) | **Głośniki i grupy Google Home to urządzenia Cast** |
| `webos.py`, `webos_discovery.py`, `projector.py` | LG webOS (TV + rzutnik) | Generyczne dla webOS, ale LG-specyficzne |
| `androidtv.py` | pilot Android TV v2 | Standard Google — dowolny Android/Google TV |
| `measure.py`, `session.py`, `optimize.py`, `dsp.py`, `stream.py`, `subalign.py`, `analiza.py` | tor pomiarowy i korekcja | Niezależne od modelu — operują na sygnale |
| `eq.py`, `modes.py`, `backup.py`, `display.py`, `commands.py` | model EQ, tryby, kopia, ekran, tabela komend | Częściowo Denon-specyficzne |
| `server.py` + `web/` | serwer stdlib + UI | Trasy i UI **zakładają jedno urządzenie** — do przebudowy |

Wniosek: protokoły są gotowe i w większości generyczne. Zakładanie konkretnego
urządzenia siedzi w `server.py`, w UI i w twardo zakodowanych tabelach `avr.py`.

## 2. Docelowa architektura: sterownik + możliwości + rejestr

Przejście z „moduły pod urządzenia" na **rejestr sterowników z modelem
możliwości**. Cztery filary.

### 2.1. Interfejs sterownika (`Driver`)

Każdy sterownik deklaruje ten sam kontrakt — reszta aplikacji nie wie, czy
rozmawia z Denonem, rzutnikiem PJLink czy głośnikiem Cast:

```
class Driver:
    kind: str                      # "avr", "projector", "tv", "speaker", "player"
    vendor: str                    # "Denon", "LG", "Epson", "Google"...

    @classmethod
    def probes(cls) -> list[Probe]         # jak mnie wykryć (porty, mDNS, SSDP)
    @classmethod
    def identify(cls, host) -> DeviceId?   # czy to ja, jaki model
    def capabilities(self) -> Capabilities # co potrafię (z urządzenia, nie z założeń)
    def pair(self) -> PairFlow?            # jak się sparować (jeśli trzeba)
    def state(self) -> dict                # aktualny stan
    def command(self, action, value, **kw) # wykonaj
```

Istniejące moduły stają się implementacjami: `avr.py` → `DenonMarantzDriver`,
`projector.py`/`webos.py` → `LgWebosDriver`, `cast.py` → `CastDriver`,
`androidtv.py` → `AndroidTvDriver`, `upnp.py` → `DlnaRendererDriver`.

### 2.2. Model możliwości (`Capabilities`) — UI z danych, nie z założeń

Sedno uniwersalizacji. Dziś UI zakłada, że istnieje `PSMULTEQ`, dwa suby,
`SSSDE`. Docelowo **to, co pokazujemy, wynika z możliwości urządzenia**:

- Denon/Marantz: możliwości czytamy z `Deviceinfo.xml` (już to robimy w
  `discovery.identify`) plus sondowanie kluczowych komend przy pierwszym
  połączeniu. Model bez Audyssey nie pokazuje zakładki Audyssey. Model z jednym
  subem nie pokazuje zestrajania dwóch.
- Zasada: **degradacja z wdziękiem**. Nasze „sprawdzone na tym egzemplarzu"
  fakty nie przenoszą się w całości — inny model, inne dziury. Zamiast twardo
  kodować, sondujemy per urządzenie i chowamy to, czego nie ma.

### 2.3. Rejestr i wykrywanie (`Registry` + fan-out)

- **Rejestr sterowników**: lista wszystkich `Driver`. Discovery odpytuje
  `probes()` każdego z nich.
- **Discovery rozgałęzione**: SSDP (Denon/DLNA) + mDNS `_googlecast._tcp`
  (Cast/Google Home) + mDNS `_androidtvremote2._tcp` + PJLink (TCP 4352) +
  webOS + skan podsieci. `discovery.py` rozszerzamy z „szukaj amplitunera" na
  „szukaj wszystkiego, co znają sterowniki".
- **Onboarding**: wykryte → zidentyfikowane → dopasowane do sterownika →
  „znaleziono: Denon AVR-X4400H, rzutnik Epson (PJLink), 2 głośniki Google" →
  użytkownik dodaje i (jeśli trzeba) wyzwala parowanie.
- **Urządzenia zapisane** w `config.json` jako lista, nie pojedyncze pola.

### 2.4. Lista kompatybilności (dane, nie kod)

Plik danych `compat.json` / `drivers/*.json`: vendor + model + rodzina →
sterownik + notatki + status (potwierdzone / prawdopodobne / zgłoszone). To
jest dokładnie to, co chcesz oddać społeczności — ludzie dopisują swoje modele
przez pull request, bez dotykania kodu.

## 3. Sterowniki: co dodać

| Sterownik | Podstawa | Praca |
|---|---|---|
| **DenonMarantzDriver** | `avr.py` gotowe | wydzielić interfejs, capabilities z Deviceinfo.xml, usunąć założenia X3300W |
| **PjlinkDriver** (NOWY) | — | **standard PJLink, TCP 4352** — jeden sterownik = Epson, Sony, Panasonic, NEC, BenQ, Optoma… Klasa 1: zasilanie, wejście, mute, status lampy. Uwierzytelnianie MD5 opcjonalne |
| **LgWebosDriver** | `webos.py`, `projector.py` gotowe | wydzielić interfejs |
| **CastDriver** + Google Home | `cast.py` gotowe | rozszerzyć wykrywanie o grupy/głośniki `_googlecast._tcp`; sterowanie play/głośność/grupa |
| **AndroidTvDriver** | `androidtv.py` gotowe | wydzielić interfejs, wyzwalanie parowania z UI |
| **DlnaRendererDriver** | `upnp.py` gotowe | wydzielić interfejs |

PJLink i grupy Cast to jedyne realnie nowe protokoły. Reszta to opakowanie
tego, co działa.

## 4. Ścieżka migracji — fazami, bez psucia działającej aplikacji

Krytyczne: aplikacja ma **cały czas działać na Twoim kinie**. Refaktor idzie
warstwami, każda faza jest samodzielnie użyteczna.

- **Faza 0 — szkielet (bez zmian zachowania).** Zdefiniować `Driver`,
  `Capabilities`, `Registry`. Owinąć istniejący `avr.py` w
  `DenonMarantzDriver` tak, że `server.py` woła przez interfejs, ale efekt
  identyczny. Nic nie znika.
- **Faza 1 — capabilities Denona.** UI amplitunera renderuje z możliwości
  czytanych z `Deviceinfo.xml` + sondowania. Twój X3300W wygląda tak samo,
  ale inny model już się nie wysypie.
- **Faza 2 — wiele urządzeń.** `config.json` jako lista; onboarding z
  discovery; UI wybiera aktywne urządzenie. Rejestr sterowników wpięty.
- **Faza 3 — PJLink.** Pierwszy nowy sterownik. Dowód, że architektura
  przyjmuje obce urządzenie bez dotykania rdzenia.
- **Faza 4 — Google Home / grupy Cast.** Rozszerzenie wykrywania i sterowania.
- **Faza 5 — lista kompatybilności + strona.** `compat.json`, mechanizm
  zgłaszania modeli, publiczna strona projektu.

## 5. MVP uniwersalizacji

Najmniejsza rzecz, która udowadnia tezę i daje wartość obcym użytkownikom:

**Faza 0 + 1 + 3.** Czyli: interfejs sterownika, capabilities Denona z
Deviceinfo.xml (dowolny Denon/Marantz przyjęty i poprawnie okrojony do tego,
co umie) oraz PJLink jako pierwszy obcy sterownik. Po tym aplikacja obsługuje
**większość amplitunerów Denon/Marantz i większość rzutników na rynku** —
i to jest moment, w którym warto założyć stronę.

## 6. Ryzyka i granice — uczciwie

- **„Sprawdzone na moim egzemplarzu" nie skaluje się w całości.** Rozwiązanie:
  capabilities per urządzenie + degradacja, nigdy twarde założenia.
- **Google Home ma ogromną powierzchnię.** Zakres: sterowanie przez Cast
  (play/głośność/grupy), nie cały graf Home ani konta.
- **PJLink Klasa 1 to podstawy** (zasilanie/wejście/mute/lampa). Głębsze
  funkcje bywają zależne od producenta — degradacja z wdziękiem jak wszędzie.
- **To jest refaktor, nie weekend.** Ale refaktor abstrakcji, nie protokołów —
  najlepsza wersja tej roboty. Fazowanie chroni działającą aplikację.
- **Prywatność przy publikacji.** Konfiguracje użytkowników (adresy, MAC-i,
  numery seryjne) nigdy do repozytorium ani na stronę — jak dziś `kopie-nastaw/`
  i `captures/` w `.gitignore`.

## 7. Strona i społeczność

Gdy MVP stoi: publiczna strona z listą kompatybilności, instrukcją, mechanizmem
zgłaszania modeli (PR do `compat.json` albo prosty formularz). Projekt już
teraz spłaca dług społeczności (protokół 1256, nieudokumentowane komendy
X3300W) — uniwersalizacja zamienia to w narzędzie, z którego korzystają inni.

## 8. Następny krok

Wejść w **Fazę 0**: zdefiniować `Driver`/`Capabilities`/`Registry` i owinąć
`avr.py` bez zmiany zachowania. Mały, bezpieczny, odwracalny krok, po którym
architektura jest już na miejscu, a aplikacja działa jak działała.
