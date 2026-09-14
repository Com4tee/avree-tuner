"""Klient Google Cast v2 — głośniki, Chromecasty i Google TV.

Protokół: TLS na porcie 8009, ramka to 4-bajtowa długość big-endian plus
komunikat protobuf `CastMessage`. Struktura jest na tyle prosta, że kodujemy
i dekodujemy ją ręcznie — wciąganie biblioteki protobuf dla sześciu pól
byłoby nieproporcjonalne, a reszta projektu też chodzi na samym stdlib.

    CastMessage {
      1 protocol_version : varint (0 = CASTV2_1_0)
      2 source_id        : string
      3 destination_id   : string
      4 namespace        : string
      5 payload_type     : varint (0 = STRING)
      6 payload_utf8     : string
    }

Uwierzytelnianie urządzenia (`tp.deviceauth`) służy do tego, żeby nadawca
mógł zweryfikować odbiornik — nie odwrotnie. Do sterowania nie jest potrzebne,
co potwierdza otwarty port 8008, który oddaje dane urządzenia bez żadnych
poświadczeń.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import socket
import ssl
import struct
import threading
import time
import urllib.request
from dataclasses import dataclass, field

from .discovery import _port_open, local_subnets

CAST_PORT = 8009
SETUP_PORT = 8008

NS_CONNECTION = "urn:x-cast:com.google.cast.tp.connection"
NS_HEARTBEAT = "urn:x-cast:com.google.cast.tp.heartbeat"
NS_RECEIVER = "urn:x-cast:com.google.cast.receiver"
NS_MEDIA = "urn:x-cast:com.google.cast.media"

SOURCE_ID = "sender-avree"
RECEIVER_ID = "receiver-0"

# Domyślny odbiornik multimediów Google — odtwarza dowolny adres URL.
DEFAULT_MEDIA_APP = "CC1AD845"

def device_kind(model: str, name: str, build: str = "") -> str:
    """Rodzaj urządzenia z modelu, nazwy i wersji oprogramowania Cast.

    Wersja rozstrzyga tam, gdzie model milczy: linia 1.x to klasyczne
    Chromecasty i głośniki, linia 3.x to Android TV i Google TV.
    """
    text = f"{model} {name}".lower()
    if "group" in text or "grupa" in text:
        return "grupa"

    # Model rozstrzyga pierwszy. Nazwa nadana przez użytkownika bywa myląca
    # ("Den Speaker" to Home Mini, "Bedroom LG" to głośnik XBOOM), więc
    # dopasowujemy po modelu, a nazwę bierzemy pod uwagę dopiero gdy go brak.
    m = model.lower()
    if any(k in m for k in ("audio", "speaker", "home", "nest", "mini",
                            "hub", "xboom", "soundbar", "max")):
        return "głośnik"
    if any(k in m for k in ("tv", "android", "ultra", "streamer", "display")):
        return "telewizor"

    if not model:
        # Bez modelu zostaje wersja oprogramowania: linia 3.x to Android TV
        # i Google TV, 1.x to klasyczne Chromecasty i głośniki.
        # Uwaga: sam build nie wystarcza — nowsze Nest Audio też są na 3.x,
        # dlatego ta gałąź działa wyłącznie przy nieznanym modelu.
        if build.startswith("3."):
            return "telewizor"
        if any(k in name.lower() for k in ("speaker", "audio", "głośnik")):
            return "głośnik"
    return "cast"


class CastError(RuntimeError):
    pass


# --------------------------------------------------------------------
# minimalny protobuf
# --------------------------------------------------------------------

def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _field_bytes(number: int, data: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(data)) + data


def _field_varint(number: int, value: int) -> bytes:
    return _varint((number << 3) | 0) + _varint(value)


def encode_message(source: str, destination: str, namespace: str, payload: str) -> bytes:
    body = (
        _field_varint(1, 0)
        + _field_bytes(2, source.encode())
        + _field_bytes(3, destination.encode())
        + _field_bytes(4, namespace.encode())
        + _field_varint(5, 0)
        + _field_bytes(6, payload.encode())
    )
    return struct.pack(">I", len(body)) + body


def decode_message(body: bytes) -> dict:
    """Wyciąga pola, których używamy. Nieznane pomija zgodnie z protobufem."""
    out = {"source_id": "", "destination_id": "", "namespace": "", "payload": ""}
    pos = 0
    while pos < len(body):
        tag, pos = _read_varint(body, pos)
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            _, pos = _read_varint(body, pos)
        elif wire == 2:
            length, pos = _read_varint(body, pos)
            chunk = body[pos:pos + length]
            pos += length
            if number == 2:
                out["source_id"] = chunk.decode("utf-8", "replace")
            elif number == 3:
                out["destination_id"] = chunk.decode("utf-8", "replace")
            elif number == 4:
                out["namespace"] = chunk.decode("utf-8", "replace")
            elif number == 6:
                out["payload"] = chunk.decode("utf-8", "replace")
        elif wire == 5:
            pos += 4
        elif wire == 1:
            pos += 8
        else:
            break
    return out


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
    raise CastError("uszkodzona ramka protobuf")


# --------------------------------------------------------------------
# połączenie
# --------------------------------------------------------------------

@dataclass
class CastDevice:
    host: str
    name: str = ""
    model: str = ""
    port: int = CAST_PORT
    _sock: ssl.SSLSocket | None = field(default=None, repr=False)
    _request_id: int = field(default=0, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _session: str | None = field(default=None, repr=False)

    # ---- transport ----

    def connect(self, timeout: float = 8.0) -> None:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            raw = socket.create_connection((self.host, self.port), timeout)
            self._sock = ctx.wrap_socket(raw, server_hostname=self.host)
        except OSError as e:
            raise CastError(f"nie mogę się połączyć z {self.host}:{self.port} — {e}") from e
        self._sock.settimeout(timeout)
        self._send(RECEIVER_ID, NS_CONNECTION, {"type": "CONNECT"})

    def close(self) -> None:
        with self._lock:
            if self._sock:
                try:
                    self._send(RECEIVER_ID, NS_CONNECTION, {"type": "CLOSE"})
                except Exception:
                    pass
                try:
                    self._sock.close()
                finally:
                    self._sock = None

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def _send(self, destination: str, namespace: str, payload: dict) -> None:
        if not self._sock:
            raise CastError("brak połączenia")
        self._sock.sendall(encode_message(SOURCE_ID, destination, namespace,
                                          json.dumps(payload)))

    def _recv(self) -> dict:
        header = b""
        while len(header) < 4:
            chunk = self._sock.recv(4 - len(header))
            if not chunk:
                raise CastError("urządzenie zamknęło połączenie")
            header += chunk
        length = struct.unpack(">I", header)[0]
        body = b""
        while len(body) < length:
            chunk = self._sock.recv(length - len(body))
            if not chunk:
                raise CastError("urządzenie zamknęło połączenie")
            body += chunk
        return decode_message(body)

    def _exchange(self, destination: str, namespace: str, payload: dict,
                  timeout: float = 8.0) -> dict:
        """Wysyła żądanie i czeka na odpowiedź o tym samym requestId.

        Po drodze odpowiada na PING — bez tego urządzenie rozłącza nas
        po kilkunastu sekundach.
        """
        with self._lock:
            self._request_id += 1
            payload = dict(payload, requestId=self._request_id)
            self._send(destination, namespace, payload)

            deadline = time.time() + timeout
            while time.time() < deadline:
                self._sock.settimeout(max(0.5, deadline - time.time()))
                try:
                    msg = self._recv()
                except socket.timeout:
                    break
                try:
                    data = json.loads(msg["payload"]) if msg["payload"] else {}
                except ValueError:
                    continue
                if msg["namespace"] == NS_HEARTBEAT and data.get("type") == "PING":
                    self._send(msg["source_id"] or RECEIVER_ID, NS_HEARTBEAT,
                               {"type": "PONG"})
                    continue
                if data.get("requestId") == self._request_id:
                    return data
            raise CastError(f"brak odpowiedzi na {payload.get('type')}")

    # ---- odbiornik ----

    def status(self) -> dict:
        return self._exchange(RECEIVER_ID, NS_RECEIVER, {"type": "GET_STATUS"})

    def set_volume(self, level: float) -> dict:
        level = max(0.0, min(1.0, float(level)))
        return self._exchange(RECEIVER_ID, NS_RECEIVER,
                              {"type": "SET_VOLUME", "volume": {"level": level}})

    def set_mute(self, muted: bool) -> dict:
        return self._exchange(RECEIVER_ID, NS_RECEIVER,
                              {"type": "SET_VOLUME", "volume": {"muted": bool(muted)}})

    def launch(self, app_id: str) -> dict:
        return self._exchange(RECEIVER_ID, NS_RECEIVER,
                              {"type": "LAUNCH", "appId": app_id}, timeout=15.0)

    def stop_app(self) -> dict:
        status = self.status()
        apps = status.get("status", {}).get("applications", [])
        if not apps:
            return {"ok": True, "note": "nic nie działa"}
        return self._exchange(RECEIVER_ID, NS_RECEIVER,
                              {"type": "STOP", "sessionId": apps[0]["sessionId"]})

    # ---- multimedia ----

    def _media_session(self) -> str:
        """Uruchamia domyślny odbiornik multimediów i zwraca jego transportId."""
        status = self.status().get("status", {})
        apps = status.get("applications", [])
        current = next((a for a in apps if a.get("appId") == DEFAULT_MEDIA_APP), None)
        if current is None:
            launched = self.launch(DEFAULT_MEDIA_APP).get("status", {})
            apps = launched.get("applications", [])
            current = next((a for a in apps if a.get("appId") == DEFAULT_MEDIA_APP), None)
            if current is None:
                raise CastError("nie udało się uruchomić odbiornika multimediów")
        transport = current["transportId"]
        if self._session != transport:
            # Każda sesja aplikacji wymaga własnego CONNECT.
            self._send(transport, NS_CONNECTION, {"type": "CONNECT"})
            self._session = transport
        return transport

    def play_url(self, url: str, title: str = "", content_type: str = "audio/mpeg",
                 media_type: str = "MUSIC_TRACK") -> dict:
        transport = self._media_session()
        payload = {
            "type": "LOAD",
            "autoplay": True,
            "currentTime": 0,
            "media": {
                "contentId": url,
                "streamType": "BUFFERED",
                "contentType": content_type,
                "metadata": {"metadataType": 3 if media_type == "MUSIC_TRACK" else 0,
                             "title": title or url.rsplit("/", 1)[-1]},
            },
        }
        return self._exchange(transport, NS_MEDIA, payload, timeout=15.0)

    def media_status(self) -> dict:
        try:
            transport = self._media_session()
        except CastError:
            return {}
        return self._exchange(transport, NS_MEDIA, {"type": "GET_STATUS"})

    def media_command(self, command: str) -> dict:
        transport = self._media_session()
        state = self._exchange(transport, NS_MEDIA, {"type": "GET_STATUS"})
        sessions = state.get("status", [])
        if not sessions:
            raise CastError("nic nie jest odtwarzane")
        media_session_id = sessions[0]["mediaSessionId"]
        mapping = {"play": "PLAY", "pause": "PAUSE", "stop": "STOP"}
        if command not in mapping:
            raise CastError(f"nieznana komenda: {command}")
        return self._exchange(transport, NS_MEDIA,
                              {"type": mapping[command],
                               "mediaSessionId": media_session_id})


# --------------------------------------------------------------------
# wykrywanie
# --------------------------------------------------------------------

def describe(host: str, timeout: float = 3.0) -> dict | None:
    """Dane urządzenia z portu 8008 — bez żadnego uwierzytelniania."""
    try:
        with urllib.request.urlopen(
                f"http://{host}:{SETUP_PORT}/setup/eureka_info?options=detail",
                timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None
    name = data.get("name") or ""
    model = (data.get("device_info") or {}).get("model_name") or ""
    return {
        "host": host,
        "name": name,
        "model": model,
        "kind": device_kind(model, name, data.get("cast_build_revision") or ""),
        "mac": data.get("mac_address") or "",
        "ethernet": bool(data.get("ethernet_connected")),
        "ssid": data.get("ssid") or "",
        "build": data.get("cast_build_revision") or "",
        "uptime": int(data.get("uptime") or 0),
    }


def mdns_models(timeout: float = 3.0) -> dict[str, dict]:
    """Nazwa i model z rekordów TXT mDNS, mapowane po adresie nadawcy.

    `eureka_info` na porcie 8008 nie zawiera nazwy modelu — sprawdziłem pięć
    wariantów parametrów, żaden jej nie oddaje. Model siedzi wyłącznie
    w rekordzie TXT usługi `_googlecast._tcp` jako `md=`.

    Nie rozwijamy pełnego parsera DNS: każde urządzenie odpowiada z własnego
    adresu, więc wystarczy wyłuskać ciągi `md=` i `fn=` z pakietu i przypisać
    je do nadawcy.
    """
    import re as _re

    def _name(label: str) -> bytes:
        out = b""
        for part in label.split("."):
            if part:
                out += bytes([len(part)]) + part.encode()
        return out + b"\x00"

    query = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    query += _name("_googlecast._tcp.local") + struct.pack(">HH", 12, 1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)
    out: dict[str, dict] = {}
    try:
        sock.sendto(query, ("224.0.0.251", 5353))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(9000)
            except (socket.timeout, OSError):
                break
            text = data.decode("latin-1")
            entry = out.setdefault(addr[0], {})
            for key, field_name in (("md", "model"), ("fn", "name")):
                m = _re.search(rf"{key}=([\x20-\x7e]{{1,40}})", text)
                if m and field_name not in entry:
                    entry[field_name] = m.group(1).strip()
    except OSError:
        pass
    finally:
        sock.close()
    return out


def find(cidr: str | None = None, workers: int = 128) -> list[dict]:
    """Szuka urządzeń Cast po otwartym porcie 8008."""
    found: list[dict] = []
    for net in ([cidr] if cidr else local_subnets()):
        hosts = [str(h) for h in ipaddress.ip_network(net, strict=False).hosts()]

        def alive(host: str) -> str | None:
            return host if _port_open(host, SETUP_PORT, 0.6) else None

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            candidates = [h for h in pool.map(alive, hosts) if h]

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            for info in pool.map(describe, candidates):
                if info:
                    found.append(info)
        if found:
            break

    # Model dołączamy z mDNS - eureka_info go nie zwraca.
    models = mdns_models()
    for entry in found:
        extra = models.get(entry["host"], {})
        if extra.get("model"):
            entry["model"] = extra["model"]
        if not entry["name"] and extra.get("name"):
            entry["name"] = extra["name"]
        entry["kind"] = device_kind(entry["model"], entry["name"], entry.get("build", ""))

    return sorted(found, key=lambda d: (d["kind"], d["name"]))




# --------------------------------------------------------------------
# zarządzanie wieloma urządzeniami
# --------------------------------------------------------------------

class CastHub:
    """Trzyma połączenia do urządzeń Cast i buforuje ich stan.

    Połączenie zestawiamy leniwie i zamykamy po chwili bezczynności —
    urządzenia Cast nie lubią wielu jednoczesnych sesji od jednego nadawcy,
    a stan i tak odczytujemy rzadko.
    """

    IDLE_TIMEOUT = 45.0
    FRESH = 4.0

    def __init__(self) -> None:
        self.devices: list[dict] = []
        self.scan_note = ""
        self.scanning = False
        self._conns: dict[str, CastDevice] = {}
        self._touched: dict[str, float] = {}
        self._status: dict[str, dict] = {}
        self._stamps: dict[str, float] = {}
        self._lock = threading.RLock()

    # ---- połączenia ----

    def _device(self, host: str) -> CastDevice:
        with self._lock:
            self._reap()
            dev = self._conns.get(host)
            if dev is None or not dev.connected:
                info = next((d for d in self.devices if d["host"] == host), {})
                dev = CastDevice(host, name=info.get("name", ""),
                                 model=info.get("model", ""))
                dev.connect()
                self._conns[host] = dev
            self._touched[host] = time.time()
            return dev

    def _reap(self) -> None:
        now = time.time()
        for host, last in list(self._touched.items()):
            if now - last > self.IDLE_TIMEOUT:
                try:
                    self._conns.pop(host).close()
                except (KeyError, Exception):
                    self._conns.pop(host, None)
                self._touched.pop(host, None)

    def close_all(self) -> None:
        with self._lock:
            for dev in self._conns.values():
                try:
                    dev.close()
                except Exception:
                    pass
            self._conns.clear()
            self._touched.clear()

    # ---- odczyt ----

    def status(self, host: str, force: bool = False) -> dict:
        now = time.time()
        if not force and now - self._stamps.get(host, 0) < self.FRESH:
            return self._status.get(host, {})
        try:
            raw = self._device(host).status().get("status", {})
            vol = raw.get("volume", {})
            apps = raw.get("applications", [])
            out = {
                "online": True,
                "volume": round(vol.get("level", 0) * 100) if vol.get("level") is not None else None,
                "muted": vol.get("muted"),
                "step": vol.get("stepInterval"),
                "app": apps[0].get("displayName") if apps else None,
                "app_id": apps[0].get("appId") if apps else None,
                "status_text": apps[0].get("statusText") if apps else None,
                "error": None,
            }
        except CastError as e:
            self._conns.pop(host, None)
            out = {"online": False, "error": str(e), "volume": None,
                   "muted": None, "app": None, "app_id": None, "status_text": None}
        self._status[host] = out
        self._stamps[host] = now
        return out

    def overview(self) -> list[dict]:
        """Lista urządzeń ze stanem. Odpytujemy równolegle, żeby nie czekać po kolei."""
        if not self.devices:
            return []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            states = list(pool.map(lambda d: self.status(d["host"]), self.devices))
        return [dict(d, **s) for d, s in zip(self.devices, states)]

    # ---- akcje ----

    def act(self, host: str, action: str, value=None) -> dict:
        dev = self._device(host)
        if action == "volume":
            dev.set_volume(float(value) / 100.0)
        elif action == "volume_step":
            current = self.status(host, force=True).get("volume") or 0
            dev.set_volume((current + float(value)) / 100.0)
        elif action == "mute":
            dev.set_mute(bool(value))
        elif action == "stop_app":
            dev.stop_app()
        elif action in ("play", "pause", "stop"):
            dev.media_command(action)
        elif action == "play_url":
            dev.play_url(str(value.get("url")), str(value.get("title", "")),
                         str(value.get("content_type", "audio/mpeg")))
        else:
            raise CastError(f"nieznana akcja: {action}")
        self._stamps.pop(host, None)
        return {"ok": True}

    # ---- wykrywanie ----

    def scan(self) -> None:
        self.scanning = True
        self.scan_note = "szukam…"
        try:
            self.devices = find()
            self.scan_note = (f"znaleziono {len(self.devices)}" if self.devices
                              else "nie znalazłem urządzeń Cast")
        except Exception as e:                       # noqa: BLE001
            self.scan_note = f"błąd: {e}"
        finally:
            self.scanning = False


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        dev = CastDevice(sys.argv[1])
        dev.connect()
        print(json.dumps(dev.status(), indent=2, ensure_ascii=False)[:2000])
        dev.close()
    else:
        for d in find():
            print(f"  {d['host']:<16} {d['kind']:<11} {d['name']:<26} "
                  f"{d['model'] or '?':<22} {'LAN' if d['ethernet'] else 'Wi-Fi'}")
