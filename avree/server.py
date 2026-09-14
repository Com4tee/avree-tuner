"""Lokalny serwer aplikacji: API JSON + interfejs w przeglądarce.

Świadomie na samej bibliotece standardowej - żeby uruchomienie sprowadzało
się do dwukliku w plik .bat, bez venva i bez pip install.
"""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import cast, discovery, eq, projector as projector_mod, upnp, webos
from .avr import (
    CROSSOVER_FREQS,
    OSD_KEYS,
    TONE_CONTROLS,
    TONE_SWITCHES,
    MODE_CATEGORIES,
    SPEAKER_POSITIONS,
    SPEAKER_SIZES,
    SURROUND_MODES,
    TIPS,
    Avr,
)
from .telnet import DenonTelnetError

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
CHUNK = 64 * 1024


class MediaRegistry:
    """Pliki udostępnione amplitunerowi pod jednorazowymi adresami."""

    def __init__(self) -> None:
        self._items: dict[str, Path] = {}
        self._lock = threading.Lock()

    def publish(self, path: Path) -> str:
        token = secrets.token_urlsafe(9)
        with self._lock:
            self._items[token] = path
            if len(self._items) > 64:                # nie rośniemy w nieskończoność
                self._items.pop(next(iter(self._items)))
        return token

    def resolve(self, token: str) -> Path | None:
        with self._lock:
            return self._items.get(token)


class App:
    """Wspólny stan współdzielony przez wątki obsługujące żądania."""

    def __init__(self, avr: Avr) -> None:
        self.avr = avr
        self.media = MediaRegistry()
        self.renderer: upnp.Renderer | None = None
        self.renderer_error: str | None = None
        self.now_playing: dict[str, Any] | None = None
        self.port = 0
        # Wynik ostatniego szukania w sieci - interfejs pyta o niego osobno,
        # bo skan podsieci potrafi trwać kilkanaście sekund.
        self.scan: dict[str, Any] = {"running": False, "found": [], "note": ""}
        self.eq = eq.load()
        self.projector = projector_mod.Projector()
        self.webos = projector_mod.WebOsHub()
        self.projector_scan = {"running": False, "found": [], "note": ""}
        self.cast = cast.CastHub()

    def ensure_renderer(self) -> upnp.Renderer | None:
        if self.renderer is None and self.renderer_error is None:
            try:
                r = upnp.describe(self.avr.host)
                upnp.protocol_info(r)
                self.renderer = r
            except upnp.UpnpError as e:
                self.renderer_error = str(e)
        return self.renderer


class Handler(BaseHTTPRequestHandler):
    app: App = None                                  # wstrzykiwane w serve()
    server_version = "AvreeTuner"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # cisza w konsoli
        pass

    # ---- pomocnicze ---------------------------------------------------

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, rel: str) -> None:
        path = (WEB_ROOT / rel).resolve()
        if not str(path).startswith(str(WEB_ROOT)) or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8"
                         if ctype.startswith("text/") or "javascript" in ctype
                         else ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # ---- GET ----------------------------------------------------------

    def do_GET(self) -> None:                        # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path

        if route == "/":
            self._static("index.html")
        elif route in ("/app.js", "/app.css"):
            self._static(route.lstrip("/"))
        elif route == "/api/state":
            self._json(self._state_payload())
        elif route == "/api/log":
            n = int(urllib.parse.parse_qs(parsed.query).get("n", ["120"])[0])
            self._json({"lines": self.app.avr.log_tail(n)})
        elif route == "/api/renderer":
            self._json(self._renderer_payload())
        elif route == "/api/scan":
            self._json(self.app.scan)
        elif route == "/api/eq":
            self._json(self._eq_payload())
        elif route == "/api/projector":
            self._json(self._projector_payload())
        elif route == "/api/projector/scan":
            self._json(self.app.projector_scan)
        elif route == "/api/cast":
            self._json(self._cast_payload())
        elif route == "/api/webos":
            self._json({"devices": self.app.webos.overview(),
                        "note": self.app.webos.scan_note,
                        "scanning": self.app.webos.scanning,
                        "buttons": webos.PointerInput.BUTTONS})
        elif route.startswith("/media/"):
            self._serve_media(route[len("/media/"):])
        else:
            self.send_error(404)

    def _state_payload(self) -> dict[str, Any]:
        state = self.app.avr.snapshot()
        state["surround_modes"] = SURROUND_MODES
        state["mode_categories"] = MODE_CATEGORIES
        state["speaker_sizes"] = [{"code": c, "label": l} for c, l in SPEAKER_SIZES]
        state["crossover_freqs"] = CROSSOVER_FREQS
        state["speaker_positions"] = SPEAKER_POSITIONS
        state["tips"] = TIPS
        state["tone_controls"] = TONE_CONTROLS
        state["tone_switches"] = TONE_SWITCHES
        state["osd_keys"] = sorted(OSD_KEYS)
        state["now_playing"] = self.app.now_playing
        return state

    def _renderer_payload(self) -> dict[str, Any]:
        r = self.app.ensure_renderer()
        if r is None:
            return {"available": False, "error": self.app.renderer_error}
        out: dict[str, Any] = {
            "available": True, "name": r.name, "model": r.model,
            "formats": r.sink_formats,
            "services": sorted(k.rsplit(":", 2)[-2] for k in r.controls),
        }
        try:
            out["transport"] = upnp.transport_info(r)
            out["position"] = upnp.position_info(r)
        except upnp.UpnpError as e:
            out["transport_error"] = str(e)
        return out

    def _serve_media(self, token: str) -> None:
        path = self.app.media.resolve(token)
        if path is None or not path.is_file():
            self.send_error(404)
            return
        size = path.stat().st_size
        ctype = upnp.MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")

        start, end = 0, size - 1
        status = 200
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            first, _, last = rng[6:].partition("-")
            if first.strip().isdigit():
                start = int(first)
            if last.strip().isdigit():
                end = min(int(last), size - 1)
            if start <= end < size:
                status = 206

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        # Renderery DLNA lubią ten nagłówek; bez niego część z nich nie startuje.
        self.send_header("transferMode.dlna.org", "Streaming")
        self.end_headers()

        with path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                data = fh.read(min(CHUNK, remaining))
                if not data:
                    break
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(data)

    # ---- POST ---------------------------------------------------------

    def do_POST(self) -> None:                       # noqa: N802
        route = urllib.parse.urlparse(self.path).path
        body = self._body()
        try:
            if route == "/api/command":
                self._json(self._command(body))
            elif route == "/api/play":
                self._json(self._play(body))
            elif route == "/api/transport":
                self._json(self._transport(body))
            elif route == "/api/scan":
                self._json(self._start_scan())
            elif route == "/api/connect":
                self._json(self._connect(body))
            elif route == "/api/eq":
                self._json(self._eq_save(body))
            elif route == "/api/projector":
                self._json(self._projector_action(body))
            elif route == "/api/projector/scan":
                self._json(self._projector_scan())
            elif route == "/api/cast":
                self._json(self._cast_action(body))
            elif route == "/api/webos":
                self._json(self._webos_action(body))
            else:
                self.send_error(404)
        except (DenonTelnetError, upnp.UpnpError, ValueError) as e:
            self._json({"ok": False, "error": str(e)}, status=400)

    def _command(self, body: dict[str, Any]) -> dict[str, Any]:
        avr = self.app.avr
        action = body.get("action")
        value = body.get("value")

        if action == "refresh":
            threading.Thread(target=avr.refresh_all, daemon=True).start()
        elif action == "raw":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("pusta komenda")
            avr.send(value.strip())
        elif action == "volume_db":
            return {"ok": True, "volume_db": avr.set_volume_db(float(value))}
        elif action == "volume_step":
            return {"ok": True, "volume_db": avr.nudge_volume(float(value))}
        elif action == "volume_ceiling":
            avr.volume_ceiling_db = None if value is None else float(value)
        elif action == "mute":
            avr.set_mute(bool(value))
        elif action == "power":
            avr.set_power(bool(value))
        elif action == "source":
            avr.set_source(str(value))
        elif action == "surround":
            avr.set_surround(str(value))
        elif action == "multeq":
            avr.set_multeq(str(value))
        elif action == "dynamic_eq":
            avr.set_dynamic_eq(bool(value))
        elif action == "dynamic_volume":
            avr.set_dynamic_volume(str(value))
        elif action == "reference_level":
            avr.set_reference_level(str(value))
        elif action == "channel_level":
            avr.set_channel_level(str(body.get("channel")), float(value))

        # --- zasilanie
        elif action == "standby":
            avr.standby()
        elif action == "wake":
            avr.wake()

        # --- konfiguracja głośników
        elif action == "speaker_size":
            avr.set_speaker_size(str(body.get("position")), str(value))
        elif action == "crossover":
            avr.set_crossover(str(body.get("position")), int(value))
        elif action == "crossover_all":
            avr.set_crossover_all(int(value))
        elif action == "subwoofer_mode":
            avr.set_subwoofer_mode(str(value))
        elif action == "lfe_lowpass":
            avr.set_lfe_lowpass(int(value))
        elif action == "subwoofer":
            avr.set_subwoofer(bool(value))

        # --- equalizer graficzny amplitunera
        #
        # Ustalone pomiarowo: PSGEQ przyjmuje ON tylko przy PSMULTEQ:OFF.
        # Wysyłamy więc obie komendy, żeby przełącznik w interfejsie
        # nie wyglądał na zepsuty.
        elif action == "graphic_eq":
            if value:
                avr.set_multeq("OFF")
                time.sleep(0.25)
                avr.send("PSGEQ ON")
            else:
                avr.send("PSGEQ OFF")

        # --- barwa i parametry dźwięku
        elif action == "tone":
            return avr.set_tone(str(body.get("control")), float(value))
        elif action == "switch":
            return avr.set_switch(str(body.get("control")), str(value))

        # --- menu ekranowe (jedyna droga do uruchomienia kalibracji Audyssey)
        elif action == "osd":
            avr.osd(str(value))

        else:
            raise ValueError(f"nieznana akcja: {action}")
        return {"ok": True}

    def _play(self, body: dict[str, Any]) -> dict[str, Any]:
        raw = (body.get("path") or "").strip().strip('"')
        if not raw:
            raise ValueError("podaj ścieżkę do pliku")
        path = Path(os.path.expandvars(raw)).expanduser()

        # Format sprawdzamy przed istnieniem pliku: komunikat "AC3 nie przejdzie
        # przez sieć" jest dla użytkownika ważniejszy niż literówka w ścieżce.
        ext = path.suffix.lower()
        if ext in upnp.MULTICHANNEL_EXT:
            raise ValueError(
                f"{upnp.MULTICHANNEL_EXT[ext]} ({ext}) nie przejdzie przez sieć — "
                "renderer amplitunera jest stereo. Ten materiał wymaga HDMI "
                "z bitstreamem albo optyki."
            )
        if ext in upnp.NO_CODEC_EXT:
            raise ValueError(
                f"{upnp.NO_CODEC_EXT[ext]} ({ext}) — amplituner nie ma tego dekodera. "
                "Przekonwertuj na FLAC albo odtwórz przez pętlę systemową."
            )
        mime = upnp.MIME_BY_EXT.get(ext)
        if mime is None:
            raise ValueError(f"nieobsługiwane rozszerzenie {ext}")

        if not path.is_file():
            raise ValueError(f"nie ma takiego pliku: {path}")

        rend = self.app.ensure_renderer()
        if rend is None:
            raise ValueError(self.app.renderer_error or "renderer niedostępny")

        token = self.app.media.publish(path)
        host_ip = upnp.local_ip_towards(self.app.avr.host)
        url = f"http://{host_ip}:{self.app.port}/media/{token}"
        upnp.play_url(rend, url, path.stem, mime)

        self.app.now_playing = {
            "title": path.stem, "file": str(path), "mime": mime,
            "size": path.stat().st_size, "url": url,
        }
        return {"ok": True, "now_playing": self.app.now_playing}

    # ---- urządzenia webOS (rzutnik i telewizor) ------------------------

    def _webos_action(self, body: dict[str, Any]) -> dict[str, Any]:
        hub = self.app.webos
        action = str(body.get("action") or "")

        if action == "scan":
            if hub.scanning:
                return {"ok": True, "already": True}
            threading.Thread(target=hub.scan, daemon=True).start()
            return {"ok": True}
        if action == "adopt":
            hub.adopt(str(body.get("host") or ""), str(body.get("name") or ""),
                      str(body.get("model") or ""))
            return {"ok": True}
        if action == "forget":
            hub.forget(str(body.get("host") or ""))
            return {"ok": True}

        host = str(body.get("host") or "")
        try:
            if action == "keep_awake":
                device = hub.devices.get(host)
                if device is None:
                    raise webos.WebOsError(f"nie znam urządzenia {host}")
                return device.set_keep_awake(bool(body.get("value")),
                                             body.get("minutes"))
            return hub.act(host, action, body.get("value"))
        except webos.WebOsError as e:
            raise ValueError(str(e)) from e

    # ---- urządzenia Google Cast ----------------------------------------

    def _cast_payload(self) -> dict[str, Any]:
        hub = self.app.cast
        return {
            "devices": hub.overview(),
            "note": hub.scan_note,
            "scanning": hub.scanning,
        }

    def _cast_action(self, body: dict[str, Any]) -> dict[str, Any]:
        hub = self.app.cast
        action = str(body.get("action") or "")

        if action == "scan":
            if hub.scanning:
                return {"ok": True, "already": True}
            threading.Thread(target=hub.scan, daemon=True).start()
            return {"ok": True}

        host = str(body.get("host") or "")
        if not host:
            raise ValueError("nie wskazano urządzenia")

        try:
            if action == "play_file":
                return self._cast_play_file(host, body)
            return hub.act(host, action, body.get("value"))
        except cast.CastError as e:
            raise ValueError(str(e)) from e

    def _cast_play_file(self, host: str, body: dict[str, Any]) -> dict[str, Any]:
        """Udostępnia lokalny plik i podaje urządzeniu jego adres.

        Ta sama droga co przy amplitunerze: plik serwujemy z aplikacji pod
        jednorazowym adresem, więc nic nie jest przekodowywane ani kopiowane.
        """
        raw = (body.get("path") or "").strip().strip('"')
        if not raw:
            raise ValueError("podaj ścieżkę do pliku")
        path = Path(os.path.expandvars(raw)).expanduser()
        ext = path.suffix.lower()
        # Cast ma własny zestaw kodeków, szerszy niż renderer amplitunera.
        types = dict(upnp.MIME_BY_EXT)
        types.update({".ogg": "audio/ogg", ".opus": "audio/ogg",
                      ".mp4": "video/mp4", ".mkv": "video/mp4",
                      ".webm": "video/webm"})
        mime = types.get(ext)
        if mime is None:
            raise ValueError(f"nieobsługiwane rozszerzenie {ext}")
        if not path.is_file():
            raise ValueError(f"nie ma takiego pliku: {path}")

        token = self.app.media.publish(path)
        url = f"http://{upnp.local_ip_towards(host)}:{self.app.port}/media/{token}"
        self.app.cast.act(host, "play_url", {
            "url": url, "title": path.stem, "content_type": mime})
        return {"ok": True, "url": url, "title": path.stem}

    # ---- rzutnik LG webOS ----------------------------------------------

    def _projector_payload(self) -> dict[str, Any]:
        state = self.app.projector.status()
        state["scan"] = self.app.projector_scan
        state["paired"] = bool(webos.load_keys().get(state.get("host") or ""))
        return state

    def _projector_action(self, body: dict[str, Any]) -> dict[str, Any]:
        action = body.get("action")
        proj = self.app.projector
        if action == "use":
            result = proj.use(str(body.get("host") or ""),
                              str(body.get("name") or ""),
                              str(body.get("model") or ""))
            proj.learn_mac()
            return result
        if action == "forget":
            proj.disconnect()
            return {"ok": True}
        if action == "keep_awake":
            return proj.set_keep_awake(bool(body.get("value")),
                                       body.get("minutes"))
        try:
            return proj.act(str(action), body.get("value"))
        except webos.WebOsError as e:
            raise ValueError(str(e)) from e

    def _projector_scan(self) -> dict[str, Any]:
        if self.app.projector_scan.get("running"):
            return {"ok": True, "already": True}
        self.app.projector_scan = {"running": True, "found": [], "note": "szukam…"}

        def work() -> None:
            try:
                found = projector_mod.Projector.scan()
                self.app.projector_scan = {
                    "running": False, "found": found,
                    "note": (f"znaleziono {len(found)}" if found
                             else "brak urządzeń webOS w tej sieci"),
                }
            except Exception as e:                       # noqa: BLE001
                self.app.projector_scan = {"running": False, "found": [],
                                           "note": f"błąd: {e}"}

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    # ---- equalizer parametryczny ---------------------------------------

    def _eq_payload(self) -> dict[str, Any]:
        design = self.app.eq
        freqs = eq.log_freqs()
        curves = {
            name: eq.channel_response(ch, freqs)
            for name, ch in design.channels.items()
        }
        return {
            "design": design.to_dict(),
            "curves": curves,
            "filter_types": eq.FILTER_TYPES,
            "channels": eq.EQ_CHANNELS,
        }

    def _eq_save(self, body: dict[str, Any]) -> dict[str, Any]:
        design = eq.EqDesign.from_dict(body.get("design") or {})
        self.app.eq = design
        eq.save(design)
        payload = self._eq_payload()
        payload["ok"] = True
        return payload

    # ---- wyszukiwanie i przepinanie amplitunera ------------------------

    def _start_scan(self) -> dict[str, Any]:
        """Uruchamia szukanie w tle. Skan podsieci trwa, więc nie blokujemy."""
        if self.app.scan.get("running"):
            return {"ok": True, "already": True}
        self.app.scan = {"running": True, "found": [], "note": "szukam…"}

        def work() -> None:
            try:
                def progress(done: int, total: int, net: str | None = None) -> None:
                    if net:
                        self.app.scan["note"] = f"skanuję {net}…"
                    elif total:
                        self.app.scan["note"] = f"sprawdzono {done} z {total} adresów"

                found = discovery.discover(progress=progress)
                self.app.scan = {
                    "running": False,
                    "found": [d.as_dict() for d in found],
                    "note": (f"znaleziono {len(found)}" if found
                             else "nic nie znalazłem w tej sieci"),
                }
            except Exception as e:                       # noqa: BLE001
                self.app.scan = {"running": False, "found": [], "note": f"błąd: {e}"}

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def _connect(self, body: dict[str, Any]) -> dict[str, Any]:
        host = (body.get("host") or "").strip()
        if not host:
            raise ValueError("podaj adres IP amplitunera")
        # Sprawdzamy zanim się przepniemy - inaczej użytkownik traci działające
        # połączenie za literówkę w adresie.
        entry = discovery.identify(host)
        if entry is None and not discovery._port_open(host, discovery.PORT_TELNET):
            raise ValueError(f"pod {host} nie ma amplitunera (ani HTTP, ani telnetu)")
        self.app.avr.reconnect(host)
        discovery.save_host(host)
        self.app.renderer = None
        self.app.renderer_error = None
        return {"ok": True, "host": host,
                "model": entry.model if entry else None}

    def _transport(self, body: dict[str, Any]) -> dict[str, Any]:
        rend = self.app.ensure_renderer()
        if rend is None:
            raise ValueError(self.app.renderer_error or "renderer niedostępny")
        action = body.get("action")
        if action == "pause":
            upnp.pause(rend)
        elif action == "resume":
            upnp.resume(rend)
        elif action == "stop":
            upnp.stop(rend)
            self.app.now_playing = None
        else:
            raise ValueError(f"nieznana akcja transportu: {action}")
        return {"ok": True}


def serve(avr: Avr, port: int = 8770) -> ThreadingHTTPServer:
    app = App(avr)
    app.port = port
    Handler.app = app
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    httpd.daemon_threads = True
    return httpd
