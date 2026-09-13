"""Tryby dźwięku i opisy funkcji — wiedza o urządzeniu, nie o protokole.

Lista trybów NIE jest przepisana z instrukcji. Została ustalona empirycznie:
do amplitunera poszedł każdy kandydat `MS<nazwa>` i sprawdzono, co odesłał.
Wynik dla AVR-X3300W:

  przyjęte  : DOLBY SURROUND, NEURAL:X, STEREO, MCH STEREO, VIRTUAL, MATRIX,
              ROCK ARENA, JAZZ CLUB, MONO MOVIE, VIDEO GAME, DIRECT, PURE DIRECT
  odrzucone : DOLBY PRO LOGIC, AUTO, MULTI CH STEREO, DTS NEURAL:X,
              WIDE SCREEN, SUPER STADIUM, CLASSIC CONCERT

Aliasy, które amplituner tłumaczy na coś innego:
  MSDOLBY DIGITAL -> DOLBY SURROUND      MSSTANDARD -> NEURAL:X
  MSDTS SURROUND  -> NEURAL:X            MSMOVIE    -> ostatni tryb kategorii
"""

from __future__ import annotations

N = "\n\n"

SURROUND_MODES = [
    {
        "code": "DOLBY SURROUND", "label": "Dolby Surround",
        "tip": "Upmikser Dolby. Rozkłada materiał 2.0 i 5.1 na wszystkie podłączone "
               "kanały, dorabiając surroundy." + N +
               "To jest NASTĘPCA Dolby Pro Logic II/IIx. Wraz z Atmosem Dolby wycofało "
               "Pro Logic i zastąpiło go tym dekoderem. Sprawdziłem na Twoim egzemplarzu: "
               "komenda MSDOLBY PRO LOGIC jest odrzucana. Pro Logic w X3300W nie ma "
               "i nie będzie.",
    },
    {
        "code": "NEURAL:X", "label": "DTS Neural:X",
        "tip": "Upmikser DTS — to samo zadanie co Dolby Surround, tylko algorytm DTS. "
               "Następca Neo:6 i Neo:X." + N +
               "W praktyce Neural:X agresywniej rozrzuca dźwięk na boki, Dolby Surround "
               "trzyma scenę ciaśniej z przodu. Kwestia gustu — porównaj na tym samym "
               "materiale.",
    },
    {
        "code": "STEREO", "label": "Stereo",
        "tip": "Tylko przednie lewy i prawy, plus subwoofer jeśli włączony. Materiał "
               "wielokanałowy zostaje zmiksowany w dół do dwóch kanałów." + N +
               "Regulacja barwy i Audyssey działają normalnie.",
    },
    {
        "code": "MCH STEREO", "label": "Multi Ch Stereo",
        "tip": "Ten sam sygnał stereo leci do WSZYSTKICH głośników jednocześnie. "
               "Nie tworzy sceny — otacza dźwiękiem równomiernie." + N +
               "Do tła i na imprezę. Do odsłuchu nie, bo znosi lokalizację źródeł.",
    },
    {
        "code": "VIRTUAL", "label": "Virtual",
        "tip": "Wirtualny surround z dwóch kolumn przednich albo ze słuchawek. "
               "Symuluje otoczenie metodami psychoakustycznymi." + N +
               "Przy Twoim pełnym zestawie 5.2 nie ma zastosowania — to tryb dla ludzi "
               "bez tylnych głośników.",
    },
    {
        "code": "MATRIX", "label": "Matrix",
        "tip": "Autorski tryb Denona: dodaje przesunięte w fazie sygnały do kanałów "
               "tylnych, żeby poszerzyć stereo." + N +
               "Efekt prostszy i bardziej surowy niż Dolby Surround. Relikt sprzed ery "
               "porządnych upmikserów.",
    },
    {
        "code": "ROCK ARENA", "label": "Rock Arena",
        "tip": "Tryb DSP Denona z rodziny „original”. Dokłada sztuczny pogłos "
               "symulujący dużą halę koncertową." + N +
               "To efekt, nie wierność — zmienia nagranie, zamiast je odtwarzać.",
    },
    {
        "code": "JAZZ CLUB", "label": "Jazz Club",
        "tip": "Jak Rock Arena, tylko krótszy pogłos — symuluje mały klub. "
               "Też czysty efekt DSP.",
    },
    {
        "code": "MONO MOVIE", "label": "Mono Movie",
        "tip": "Do starych ścieżek monofonicznych. Rozprowadza sygnał mono na kanały "
               "i dokłada trochę przestrzeni, żeby nie brzmiało jak z jednego punktu.",
    },
    {
        "code": "VIDEO GAME", "label": "Video Game",
        "tip": "Tryb DSP nastawiony na efekty — podbija otoczenie i dynamikę. "
               "To właśnie tu ląduje przycisk GAME.",
    },
    {
        "code": "DIRECT", "label": "Direct",
        "tip": "Omija regulację barwy i układy wideo, skracając tor sygnału." + N +
               "Uwaga: zarządzanie basem, odległości i poziomy nadal działają. "
               "To nie jest pełny bypass.",
    },
    {
        "code": "PURE DIRECT", "label": "Pure Direct",
        "tip": "Jak Direct, dodatkowo wygasza wyświetlacz i wyłącza układy wideo, "
               "żeby ograniczyć zakłócenia." + N +
               "Najkrótszy możliwy tor sygnału w tym amplitunerze. Jeśli chcesz "
               "porównać brzmienie bez przetwarzania — to jest ten tryb.",
    },
]

# Przyciski kategorii. To NIE są tryby: przywołują ostatnio używany tryb z danej
# grupy dla bieżącego formatu wejściowego. Sprawdzone na Twoim egzemplarzu:
# MSMOVIE przywołało MCH STEREO, MSGAME przywołało VIDEO GAME.
MODE_CATEGORIES = [
    {
        "code": "MOVIE", "label": "Movie",
        "tip": "To nie tryb, tylko KATEGORIA. Przywołuje ostatnio używany tryb "
               "z grupy „film” dla bieżącego formatu wejściowego." + N +
               "Amplituner pamięta osobny wybór dla Movie, Music i Game — dlatego ten "
               "sam przycisk daje różne rezultaty zależnie od tego, co ustawiłeś wcześniej.",
    },
    {
        "code": "MUSIC", "label": "Music",
        "tip": "Kategoria „muzyka” — przywołuje ostatnio używany tryb z tej grupy. "
               "Jeśli po kliknięciu nic się nie zmienia, zapamiętany tryb jest już aktywny.",
    },
    {
        "code": "GAME", "label": "Game",
        "tip": "Kategoria „gra”. Na Twoim egzemplarzu przywołuje Video Game — "
               "tryb DSP z podbitymi efektami otoczenia.",
    },
]

# --- opisy pozostałych funkcji, serwowane do interfejsu ------------------

TIPS = {
    "multeq": "Audyssey MultEQ XT32 mierzy odpowiedź pomieszczenia i koryguje ją filtrami. "
              "XT32 to najwyższa wersja: setki punktów korekcji na kanał i niezależna "
              "korekcja dwóch subwooferów (Sub EQ HT) — dlatego Twoje suby dostały "
              "poprawnie wyrównane fazy.",

    "multeq.AUDYSSEY":
        "REFERENCE — pełna korekcja z dwiema dodatkowymi rzeczami: roll-offem góry pasma "
        "(łagodne ściszenie powyżej ~10 kHz) i kompensacją średnicy (delikatne obniżenie "
        "okolic 2 kHz)." + N +
        "Po to, żeby ścieżka filmowa zmiksowana w dużym studiu brzmiała w małym "
        "pomieszczeniu tak, jak zamierzono. Ustawienie domyślne.",

    "multeq.FLAT":
        "FLAT — ta sama korekcja, ale BEZ roll-offu góry i bez kompensacji średnicy. "
        "Celuje w płaską odpowiedź do 20 kHz." + N +
        "Brzmi wyraźnie jaśniej niż Reference. Przeznaczone do małych, wytłumionych "
        "pomieszczeń i odsłuchu z bliska." + N +
        "Przy Twoich aktywnych PA z limiterem to najgorszy możliwy wybór — "
        "dokłada energii dokładnie tam, gdzie limiter się zapala.",

    "multeq.BYP.LR":
        "L/R BYPASS — korekcja działa na wszystkich kanałach OPRÓCZ przedniego lewego "
        "i prawego." + N +
        "Dla ludzi, którzy ufają swoim frontom i nie chcą, żeby DSP ich dotykał, "
        "ale chcą korekcji centralnego, surroundów i subwooferów." + N +
        "W Twoim przypadku wart rozważenia: zostawia zrobioną przez Audyssey robotę "
        "na subwooferach, a zdejmuje korekcję z kolumn PA.",

    "multeq.OFF":
        "OFF — korekcja częstotliwościowa wyłączona całkowicie." + N +
        "Poziomy kanałów, odległości i zwrotnice ustawione przez Audyssey ZOSTAJĄ. "
        "Wyłącza się tylko equalizacja.",

    "dyneq":
        "DYNAMIC EQ — kompensacja głośnościowa oparta na krzywych równej głośności "
        "(Fletcher-Munson). To NIE jest część korekcji pomieszczenia." + N +
        "Ucho przy cichym słuchaniu gorzej słyszy skrajne pasma, więc Dynamic EQ "
        "dokłada basu i góry — tym mocniej, im niżej grasz od poziomu referencyjnego." + N +
        "Przy głośności -75 dB podbicie jest maksymalne. To najbardziej prawdopodobna "
        "przyczyna tego, że limitery Twoich kolumn zapalają się w połowie skali.",

    "reflev":
        "REFERENCE LEVEL OFFSET — mówi Dynamic EQ, o ile ciszej niż kinowy standard "
        "zmiksowany jest materiał, którego słuchasz." + N +
        "0 dB — film. Miks kinowy pod szczyt 105 dB. Domyślne.\n"
        "+5 dB — materiał zmiksowany nieco ciszej.\n"
        "+10 dB — muzyka. Typowy miks muzyczny jest znacznie gorętszy od filmowego.\n"
        "+15 dB — materiał bardzo mocno skompresowany." + N +
        "Im wyższy offset, tym MNIEJ Dynamic EQ dokłada. Działa wyłącznie przy "
        "włączonym Dynamic EQ.",

    "dynvol":
        "DYNAMIC VOLUME — kompresor zakresu dynamiki działający w czasie rzeczywistym. "
        "Ścisza głośne fragmenty, podgłaśnia ciche." + N +
        "Light / Medium / Heavy to siła działania. Do oglądania w nocy, żeby wybuchy "
        "nie budziły domu, a dialogi były słyszalne." + N +
        "Zmienia balans tonalny i wymusza działanie Dynamic EQ. Do odsłuchu muzyki "
        "trzymaj wyłączony.",

    "volume":
        "Skala Denona: 0 dB to poziom odniesienia (ok. 75 dB SPL dla szumu "
        "kalibracyjnego). Wyświetlacz amplitunera pokazuje tę samą liczbę powiększoną "
        "o 80." + N +
        "Twój egzemplarz ma górny limit ustawiony na 80 na wyświetlaczu, czyli 0 dB.",

    "ceiling":
        "SUFIT GŁOŚNOŚCI — blokada po stronie aplikacji, nie amplitunera." + N +
        "Każda komenda głośności powyżej tej wartości zostaje obcięta zanim poleci "
        "do urządzenia. Chroni kolumny aktywne PA przed wejściem w limiter." + N +
        "Ustaw ją tuż poniżej poziomu, przy którym zapalają się diody limitera. "
        "Puste pole wyłącza blokadę.",

    "speaker_size":
        "LARGE — kanał dostaje pełne pasmo, łącznie z najniższym basem. Zwrotnica "
        "jest wtedy ignorowana.\n"
        "SMALL — bas poniżej zwrotnicy zostaje odcięty i przekierowany do subwooferów.\n"
        "NONE — kanał nieużywany." + N +
        "„Large” nie znaczy „duża kolumna”, tylko „poradzi sobie z basem bez pomocy”. "
        "Przy aktywnych PA i dwóch subwooferach ustawienie Small ze zwrotnicą "
        "80-100 Hz zdejmuje dół z końcówek i daje im realny zapas przed limiterem.",

    "crossover":
        "ZWROTNICA — częstotliwość, poniżej której bas przechodzi z kanału do "
        "subwoofera. Działa tylko dla kanałów ustawionych jako Small." + N +
        "Reguła kciuka: ustaw około oktawę powyżej punktu, w którym kolumna zaczyna "
        "opadać. Dla typowej PA-ki z 12-calowym głośnikiem 80 Hz, dla mniejszych 100-120 Hz.",

    "subwoofer_mode":
        "LFE — subwoofer dostaje wyłącznie ścieżkę efektów niskotonowych (kanał .1) "
        "plus bas odcięty z kanałów ustawionych jako Small.\n"
        "LFE+MAIN — subwoofer dostaje dodatkowo bas z kanałów ustawionych jako LARGE, "
        "grając równolegle z nimi." + N +
        "Twoje ustawienie to LFE+Main przy wszystkich kanałach Large — bas leci "
        "jednocześnie do subwooferów I do kolumn PA. Daje to więcej dołu, ale kosztem "
        "zapasu mocy kolumn i ryzyka interferencji między subem a kolumną.",

    "lfe_lowpass":
        "Filtr dolnoprzepustowy dla kanału LFE (ścieżki .1 z płyty). Ustala, do jakiej "
        "częstotliwości subwoofer odtwarza materiał z tego kanału." + N +
        "80 Hz to wartość zgodna ze standardem kinowym. 120 Hz przepuszcza więcej, "
        "ale może uczynić subwoofer słyszalnym jako osobne źródło.",

    "power":
        "ZMON/ZMOFF włącza i wyłącza strefę główną, PWSTANDBY usypia całe urządzenie." + N +
        "Wybudzenie ze stanu czuwania działa po sieci tylko wtedy, gdy w menu "
        "amplitunera włączone jest sterowanie sieciowe w trybie czuwania "
        "(Network Control / Always On). Inaczej amplituner odcina kartę sieciową "
        "i nie ma go czym obudzić.",

    "input_signal":
        "Co amplituner FAKTYCZNIE dostaje na wejściu — odczyt z SSINFAISSIG." + N +
        "Przydatne do weryfikacji łańcucha: jeśli myślisz, że wysyłasz 5.1, "
        "a tu widnieje PCM stereo, to znaczy, że coś po drodze zmiksowało sygnał w dół. "
        "Klasyczny błąd przy HDMI z komputera.",

    "amp_assign":
        "Przypisanie końcówek mocy. Twój X3300W ma 7 wzmacniaczy; w trybie ZONE2 "
        "dwa z nich obsługują drugą strefę, zostawiając 5 kanałów w głównej." + N +
        "Zmiana tego ustawienia wymaga menu ekranowego — nie ma bezpiecznej komendy "
        "sieciowej, a błędne przypisanie potrafi wyciszyć kanały.",

    "audyssey_run":
        "Uruchomienia kalibracji Audyssey nie da się wywołać jedną komendą — Denon "
        "takiej nie udostępnia." + N +
        "Aplikacja otwiera menu ekranowe amplitunera i pozwala po nim nawigować "
        "strzałkami, tak jak pilotem. Do Audyssey docierasz przez "
        "Setup → Speakers → Audyssey Setup." + N +
        "Potrzebujesz włączonego projektora albo telewizora, bo menu jest tylko na HDMI.",

    "osd":
        "Sterowanie menu ekranowym amplitunera — dokładnie to, co robią strzałki "
        "na pilocie. Menu wyświetla się wyłącznie przez HDMI, więc musi być włączony "
        "wyświetlacz podpięty do wyjścia HDMI MONITOR.",
}
