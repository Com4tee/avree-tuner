"""Warstwa aplikacyjna nad klientem SSAP — stan rzutnika dla interfejsu.

Połączenie SSAP bywa zrywane (uśpienie, zmiana wejścia, restart usługi),
więc trzymamy je leniwie i odtwarzamy przy pierwszym niepowodzeniu.
Stan buforujemy, bo odpytywanie urządzenia przy każdym odświeżeniu
interfejsu byłoby marnotrawstwem — a listy wejść i aplikacji i tak
zmieniają się rzadko.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from . import webos, webos_discovery
from .discovery import CONFIG_PATH

# Ile sekund ufamy zbuforowanym danym, zanim spytamy urządzenie ponownie.
FRESH_FAST = 3.0        # zasilanie, głośność, aktywna aplikacja
FRESH_SLOW = 120.0      # listy wejść i aplikacji


def load_settings() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_setting(key: str, value: Any) -> None:
    cfg = load_settings()
    cfg[key] = value
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                               encoding="utf-8")
    except OSError:
        pass


class Projector:
    """Jedno urządzenie webOS plus bufor jego stanu."""

    def __init__(self, host: str | None = None, mac: str | None = None) -> None:
        cfg = load_settings()
        self.host = host or cfg.get("projector_host")
        self.mac = mac or cfg.get("projector_mac")
        self.name = cfg.get("projector_name", "")
        self.model = cfg.get("projector_model", "")
        self._dev: webos.WebOsDevice | None = None
        self._lock = threading.RLock()
        self._cache: dict[str, Any] = {}
        self._stamps: dict[str, float] = {}
        self.last_error: str | None = None
        self.pairing = False
        # Podtrzymywanie aktywności - patrz keep_awake().
        self.keep_awake_on = bool(cfg.get("projector_keep_awake", False))
        self.keep_awake_minutes = int(cfg.get("projector_keep_awake_minutes", 30))
        self.keep_awake_last: float | None = None
        self._awake_stop = threading.Event()
        self._awake_thread: threading.Thread | None = None
        if self.keep_awake_on:
            self._start_keep_awake()

    # ---- połączenie --------------------------------------------------

    def _device(self) -> webos.WebOsDevice:
        if not self.host:
            raise webos.WebOsError("nie wskazano rzutnika — użyj wyszukiwania")
        if self._dev is None or not self._dev.connected:
            dev = webos.WebOsDevice(self.host, name=self.name)
            # Klucz z poprzedniego parowania wczytuje się sam; jeśli go nie ma,
            # urządzenie pokaże pytanie na ekranie.
            self.pairing = webos.load_keys().get(self.host) is None
            dev.connect(prompt_timeout=90.0 if self.pairing else 15.0)
            self.pairing = False
            self._dev = dev
        return self._dev

    def disconnect(self) -> None:
        with self._lock:
            if self._dev:
                self._dev.close()
            self._dev = None

    def _call(self, name: str, fn, fresh: float):
        """Wywołuje `fn` i buforuje wynik; przy zerwanym łączu próbuje raz ponownie."""
        now = time.time()
        if name in self._cache and now - self._stamps.get(name, 0) < fresh:
            return self._cache[name]
        for attempt in (1, 2):
            try:
                value = fn(self._device())
                self._cache[name] = value
                self._stamps[name] = now
                self.last_error = None
                return value
            except webos.WebOsError as e:
                self.disconnect()
                if attempt == 2:
                    self.last_error = str(e)
                    raise
        return None

    # ---- odczyt ------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Pełny stan dla interfejsu. Nigdy nie rzuca — braki oznacza jako None."""
        with self._lock:
            out: dict[str, Any] = {
                "host": self.host, "mac": self.mac,
                "name": self.name, "model": self.model,
                "connected": False, "error": None,
                "keep_awake": self.keep_awake_on,
                "keep_awake_minutes": self.keep_awake_minutes,
                "keep_awake_last": self.keep_awake_last,
                "buttons": webos.PointerInput.BUTTONS,
                "power": None, "volume": None, "muted": None,
                "foreground": None, "inputs": [], "apps": [],
            }
            if not self.host:
                out["error"] = "nie wskazano rzutnika"
                return out
            try:
                out["power"] = self._call(
                    "power", lambda d: d.power_state().get("state"), FRESH_FAST)
                vol = self._call("volume", lambda d: d.volume(), FRESH_FAST) or {}
                out["volume"] = vol.get("volume")
                out["muted"] = vol.get("muted")
                out["foreground"] = self._call(
                    "fg", lambda d: d.foreground_app().get("appId"), FRESH_FAST)
                out["inputs"] = self._call("inputs", lambda d: d.inputs(), FRESH_SLOW) or []
                out["apps"] = self._call("apps", lambda d: d.apps(), FRESH_SLOW) or []
                out["connected"] = True
            except webos.WebOsError as e:
                out["error"] = str(e)
            return out

    # ---- akcje -------------------------------------------------------

    def act(self, action: str, value: Any = None) -> dict[str, Any]:
        with self._lock:
            # Wake-on-LAN jako jedyne nie wymaga połączenia — urządzenie śpi.
            if action == "wake":
                if not self.mac:
                    raise webos.WebOsError(
                        "nie znam adresu MAC rzutnika — uruchom wyszukiwanie "
                        "przy włączonym urządzeniu")
                webos.wake_on_lan(self.mac)
                return {"ok": True, "note": "wysłano magiczny pakiet"}

            dev = self._device()
            if action == "power_off":
                dev.power_off()
                self.disconnect()               # urządzenie i tak zerwie łącze
                self._cache.clear()
                return {"ok": True}
            if action == "input":
                dev.switch_input(str(value))
            elif action == "volume":
                dev.set_volume(int(value))
            elif action == "volume_step":
                current = (dev.volume() or {}).get("volume", 0)
                dev.set_volume(int(current) + int(value))
            elif action == "mute":
                dev.set_mute(bool(value))
            elif action == "launch":
                dev.launch(str(value))
            elif action == "toast":
                dev.toast(str(value or "AVREE Tuner"))
            elif action == "press":
                dev.press(str(value))
            elif action == "pointer_move":
                dev.pointer().move(int(value.get("dx", 0)), int(value.get("dy", 0)))
            elif action == "pointer_click":
                dev.pointer().click()
            elif action == "pointer_scroll":
                dev.pointer().scroll(int(value))
            else:
                raise webos.WebOsError(f"nieznana akcja: {action}")

            # Po każdej zmianie unieważniamy szybki bufor, żeby interfejs
            # pokazał skutek, a nie stan sprzed komendy.
            for key in ("power", "volume", "fg"):
                self._stamps.pop(key, None)
            return {"ok": True}

    # ---- podtrzymywanie aktywności -----------------------------------
    #
    # Rzutnik gasi się po kilku godzinach bez sygnału od pilota. Ustawienia
    # tego licznika NIE MA w SSAP - sprawdziłem wszystkie kategorie
    # `getSystemSettings` i żaden klucz timera na tym modelu nie istnieje.
    #
    # Zamiast zmieniać ustawienie, zerujemy licznik u źródła: wysyłamy
    # przesunięcie wskaźnika o zero pikseli. Dla urządzenia to zdarzenie
    # wejściowe, dla oglądającego - nic. Żadnego przycisku, żadnej reakcji
    # na ekranie.

    def _start_keep_awake(self) -> None:
        if self._awake_thread and self._awake_thread.is_alive():
            return
        self._awake_stop.clear()

        def loop() -> None:
            while not self._awake_stop.is_set():
                if self._awake_stop.wait(self.keep_awake_minutes * 60):
                    return
                try:
                    with self._lock:
                        self._device().pointer().move(0, 0)
                        self.keep_awake_last = time.time()
                except Exception:
                    # Rzutnik mógł zostać wyłączony ręcznie - to nie błąd.
                    self.disconnect()

        self._awake_thread = threading.Thread(target=loop, daemon=True)
        self._awake_thread.start()

    def set_keep_awake(self, on: bool, minutes: int | None = None) -> dict:
        with self._lock:
            if minutes:
                self.keep_awake_minutes = max(5, min(120, int(minutes)))
                save_setting("projector_keep_awake_minutes", self.keep_awake_minutes)
            self.keep_awake_on = bool(on)
            save_setting("projector_keep_awake", self.keep_awake_on)
            if on:
                self._start_keep_awake()
            else:
                self._awake_stop.set()
                self._awake_thread = None
            return {"ok": True, "on": self.keep_awake_on,
                    "minutes": self.keep_awake_minutes}

    # ---- wybór urządzenia --------------------------------------------

    def use(self, host: str, name: str = "", model: str = "",
            mac: str | None = None) -> dict[str, Any]:
        with self._lock:
            self.disconnect()
            self._cache.clear()
            self._stamps.clear()
            self.host, self.name, self.model = host, name, model
            if mac:
                self.mac = mac
            save_setting("projector_host", host)
            save_setting("projector_name", name)
            save_setting("projector_model", model)
            if self.mac:
                save_setting("projector_mac", self.mac)
            return {"ok": True, "host": host}

    @staticmethod
    def scan() -> list[dict]:
        return webos_discovery.find()

    def learn_mac(self) -> str | None:
        """Wyciąga MAC rzutnika z tablicy ARP — potrzebny do Wake-on-LAN."""
        if not self.host:
            return None
        import re
        import subprocess
        try:
            out = subprocess.run(["arp", "-a", self.host],
                                 capture_output=True, text=True, timeout=6).stdout
        except Exception:
            return None
        m = re.search(rf"{re.escape(self.host)}\s+([0-9a-fA-F]{{2}}(?:[-:][0-9a-fA-F]{{2}}){{5}})",
                      out)
        if m:
            self.mac = m.group(1).lower().replace("-", ":")
            save_setting("projector_mac", self.mac)
            return self.mac
        return None
