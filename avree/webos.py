"""Klient SSAP — sterowanie urządzeniami LG webOS (rzutnik, telewizor).

SSAP to JSON po WebSocket na porcie 3000 (albo 3001 po TLS). Protokół jest
otwarty i nie wymaga żadnego keycode: przy pierwszym połączeniu urządzenie
wyświetla pytanie na ekranie, a po akceptacji odsyła `client-key`, którego
używamy bezterminowo.

WebSocket zaimplementowany tutaj od zera, żeby nie wprowadzać zależności —
reszta projektu też chodzi na samej bibliotece standardowej. Potrzebna jest
tylko podzbiór protokołu: ramki tekstowe, maskowanie po stronie klienta,
ping-pong i zamknięcie.

Ustalone pomiarowo na rzutniku [LG] lodownia (DBF510P-GL, 192.168.0.75):
uścisk WebSocket na porcie 3000 przechodzi i zwraca 101 Switching Protocols.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .discovery import CONFIG_PATH

KEYS_PATH = CONFIG_PATH.parent / "webos-keys.json"

SSAP_PORT = 3000
SSAP_TLS_PORT = 3001

# Uprawnienia, o które prosimy przy parowaniu.
#
# Uwaga wynikająca z pomyłki: urządzenie przyznaje uprawnienia na podstawie
# manifestu wysyłanego przy KAŻDYM połączeniu, nie tylko przy pierwszym
# parowaniu. Zawężenie tej listy odbiera dostęp mimo ważnego klucza klienta.
# Dlatego lista musi tu zostać kompletna, a nie być doraźnie modyfikowana.
PERMISSIONS = [
    "LAUNCH", "LAUNCH_WEBAPP", "APP_TO_APP", "CLOSE",
    "TEST_OPEN", "TEST_PROTECTED",
    "CONTROL_AUDIO", "CONTROL_DISPLAY",
    "CONTROL_INPUT_JOYSTICK", "CONTROL_INPUT_MEDIA_RECORDING",
    "CONTROL_INPUT_MEDIA_PLAYBACK", "CONTROL_INPUT_TV",
    "CONTROL_POWER", "CONTROL_TV_SCREEN", "CONTROL_TV_STANBY",
    "CONTROL_TV_POWER", "CONTROL_WOL", "CONTROL_TIMER_INFO",
    "CONTROL_FAVORITE_GROUP", "CONTROL_USER_INFO",
    "CONTROL_BLUETOOTH", "CHECK_BLUETOOTH_DEVICE",
    "CONTROL_INPUT_TEXT", "CONTROL_MOUSE_AND_KEYBOARD",
    "CONTROL_RECORDING", "CONTROL_BOX_CHANNEL", "CONTROL_CHANNEL_GROUP",
    "CONTROL_CHANNEL_BLOCK",
    "READ_APP_STATUS", "READ_CURRENT_CHANNEL", "READ_COUNTRY_INFO",
    "READ_INPUT_DEVICE_LIST", "READ_INSTALLED_APPS", "READ_NETWORK_STATE",
    "READ_POWER_STATE", "READ_RUNNING_APPS", "READ_SETTINGS",
    "READ_TV_CHANNEL_LIST", "READ_TV_CONTENT_STATE", "READ_TV_CURRENT_TIME",
    "READ_TV_PROGRAM_INFO", "READ_RECORDING_STATE", "READ_RECORDING_LIST",
    "READ_RECORDING_SCHEDULE", "READ_STORAGE_DEVICE_LIST",
    "WRITE_NOTIFICATION_TOAST", "WRITE_RECORDING_LIST",
    "WRITE_RECORDING_SCHEDULE",
    "ADD_LAUNCHER_CHANNEL", "SET_CHANNEL_SKIP", "RELEASE_CHANNEL_SKIP",
    "DELETE_SELECT_CHANNEL", "SCAN_TV_CHANNELS", "STB_INTERNAL_CONNECTION",
]

REGISTER_MANIFEST = {
    "manifestVersion": 1,
    "appVersion": "1.1",
    "signed": {
        "created": "20140509",
        "appId": "com.lge.test",
        "vendorId": "com.lge",
        "localizedAppNames": {"": "LG Remote App"},
        "localizedVendorNames": {"": "LG Electronics"},
        "permissions": ["TEST_SECURE", "CONTROL_INPUT_TEXT",
                        "CONTROL_MOUSE_AND_KEYBOARD", "READ_INSTALLED_APPS",
                        "READ_LGE_SDX", "READ_NOTIFICATIONS", "SEARCH",
                        "WRITE_SETTINGS", "WRITE_NOTIFICATION_ALERT",
                        "CONTROL_POWER", "READ_CURRENT_CHANNEL",
                        "READ_RUNNING_APPS", "READ_UPDATE_INFO",
                        "UPDATE_FROM_REMOTE_APP",
                        "READ_LGE_TV_INPUT_EVENTS", "READ_TV_CURRENT_TIME"],
        "serial": "2f930e2d2cfe083771f68e4fe7bb07",
    },
    "permissions": PERMISSIONS,
    "signatures": [{
        "signatureVersion": 1,
        "signature": (
            "eyJhbGdvcml0aG0iOiJSU0EtU0hBMjU2Iiwia2V5SWQiOiJ0ZXN0LXNpZ25pbmctY2"
            "VydCIsInNpZ25hdHVyZVZlcnNpb24iOjF9.hrVRgjCwXVvE2OOSpDZ58hR"
            "+59aFNwYDyjQgKk3auukd7pcegmE2CzPCa0bJ0ZsRAcKkCTJrWo5iDzNhMBWRyaMOv5"
            "zWSrthlf7G128qvIlpMT0YNY+n/FaOHE73uLrS/g7swl3/qH/BGFG2Hu4RlL48eb3lL"
            "KqTt2xKHdCs6Cd4RMfJPYnzgvI4BNrFUKsjkcu+WD4OO2A27Pq1n50cMchmcaXadJhG"
            "rOqH5YmHdOCj5NSHzJYrsW0HPlpuAx/ECMeIZYDh6RMqaFM2DXzdKX9NmmyqzJ3o/0l"
            "kk/N97gfVRLW5hA29yeAwaCViZNCP8iC9aO0q9fQojoa7NQnAtw=="
        ),
    }],
}

# Jedno miejsce prawdy dla tego, co da się zrobić.
COMMANDS = {
    "power_off":    "ssap://system/turnOff",
    "volume_up":    "ssap://audio/volumeUp",
    "volume_down":  "ssap://audio/volumeDown",
    "get_volume":   "ssap://audio/getVolume",
    "set_volume":   "ssap://audio/setVolume",
    "set_mute":     "ssap://audio/setMute",
    "get_inputs":   "ssap://tv/getExternalInputList",
    "switch_input": "ssap://tv/switchInput",
    "list_apps":    "ssap://com.webos.applicationManager/listLaunchPoints",
    "launch_app":   "ssap://system.launcher/launch",
    "close_app":    "ssap://system.launcher/close",
    "foreground":   "ssap://com.webos.applicationManager/getForegroundAppInfo",
    "toast":        "ssap://system.notifications/createToast",
    "power_state":  "ssap://com.webos.service.tvpower/power/getPowerState",
    "sw_info":      "ssap://com.webos.service.update/getCurrentSWInformation",
    "system_info":  "ssap://system/getSystemInfo",
}


class WebOsError(RuntimeError):
    pass


# --------------------------------------------------------------------
# minimalny WebSocket
# --------------------------------------------------------------------

class WebSocket:
    """Klient WebSocket: ramki tekstowe, maskowanie, ping-pong.

    Nie obsługuje rozszerzeń ani ramek binarnych - SSAP ich nie używa.
    Fragmentację obsługuje, bo webOS potrafi podzielić dłuższą listę aplikacji.
    """

    def __init__(self, host: str, port: int = SSAP_PORT, timeout: float = 4.0) -> None:
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.timeout = timeout
        # Gniazdo pilota leży pod ścieżką z tokenem, nie pod "/".
        self.path = "/"

    def connect(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            # webOS weryfikuje Origin i zrywa połączenie kodem 1008
            # "invalid origin" dla wszystkiego poza 'null' i 'file://'.
            # Sprawdzone i odrzucone: http://host, ws://host, com.lge.test,
            # pusty. Brak nagłówka też nie przechodzi — wtedy kod 1002.
            f"Sec-WebSocket-Version: 13\r\n"
            f"Origin: null\r\n\r\n"
        )
        try:
            self.sock = socket.create_connection((self.host, self.port), self.timeout)
        except OSError as e:
            raise WebOsError(f"nie mogę się połączyć z {self.host}:{self.port} — {e}") from e
        self.sock.settimeout(self.timeout)
        self.sock.sendall(request.encode())

        # Nagłówki odpowiedzi kończy pusta linia; czytamy bajt po bajcie,
        # żeby nie zjeść początku pierwszej ramki.
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                raise WebOsError("urządzenie zerwało połączenie podczas uścisku")
            head += chunk
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if "101" not in status:
            raise WebOsError(f"urządzenie odrzuciło WebSocket: {status}")

    def send(self, text: str) -> None:
        if not self.sock:
            raise WebOsError("brak połączenia")
        payload = text.encode("utf-8")
        header = bytearray([0x81])                 # FIN + opcode tekstowy
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)           # bit maski zawsze ustawiony
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise WebOsError("połączenie zamknięte przez urządzenie")
            buf += chunk
        return buf

    def recv(self) -> str | None:
        """Jedna wiadomość tekstowa. None gdy urządzenie zamknęło połączenie."""
        message = b""
        while True:
            first, second = self._recv_exact(2)
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            data = self._recv_exact(length) if length else b""
            if masked:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))

            if opcode == 0x8:                      # close
                return None
            if opcode == 0x9:                      # ping -> pong
                self._pong(data)
                continue
            if opcode == 0xA:                      # pong
                continue
            message += data
            if fin:
                return message.decode("utf-8", "replace")

    def _pong(self, data: bytes) -> None:
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes([0x8A, 0x80 | len(data)]) + mask + masked)

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.sendall(bytes([0x88, 0x80]) + os.urandom(4))
            except OSError:
                pass
            try:
                self.sock.close()
            finally:
                self.sock = None


# --------------------------------------------------------------------
# klucze klienta
# --------------------------------------------------------------------

def load_keys() -> dict[str, str]:
    try:
        return json.loads(KEYS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_key(host: str, key: str) -> None:
    keys = load_keys()
    keys[host] = key
    try:
        KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
        KEYS_PATH.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------
# klient SSAP
# --------------------------------------------------------------------

@dataclass
class WebOsDevice:
    host: str
    port: int = SSAP_PORT
    client_key: str | None = None
    name: str = ""
    _ws: WebSocket | None = field(default=None, repr=False)
    _counter: int = field(default=0, repr=False)
    _pointer: "PointerInput | None" = field(default=None, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # ---- połączenie i parowanie ----

    def connect(self, on_prompt=None, prompt_timeout: float = 60.0) -> str:
        """Łączy i paruje. `on_prompt` wołane, gdy urządzenie czeka na akceptację.

        Zwraca klucz klienta. Przy pierwszym razie wymaga potwierdzenia
        na ekranie urządzenia.
        """
        with self._lock:
            if self.client_key is None:
                self.client_key = load_keys().get(self.host)

            ws = WebSocket(self.host, self.port)
            ws.connect()
            self._ws = ws

            payload = {
                "forcePairing": False,
                "pairingType": "PROMPT",
                "manifest": REGISTER_MANIFEST,
            }
            if self.client_key:
                payload["client-key"] = self.client_key

            self._counter += 1
            request_id = f"register_{self._counter}"
            ws.send(json.dumps({"type": "register", "id": request_id, "payload": payload}))

            deadline = time.time() + prompt_timeout
            prompted = False
            while time.time() < deadline:
                ws.sock.settimeout(max(1.0, deadline - time.time()))
                try:
                    raw = ws.recv()
                except socket.timeout:
                    continue
                if raw is None:
                    raise WebOsError("urządzenie zamknęło połączenie w trakcie parowania")
                msg = json.loads(raw)

                if msg.get("type") == "response" and \
                        msg.get("payload", {}).get("pairingType") == "PROMPT":
                    prompted = True
                    if on_prompt:
                        on_prompt()
                    continue

                if msg.get("type") == "registered":
                    key = msg.get("payload", {}).get("client-key")
                    if not key:
                        raise WebOsError("urządzenie nie odesłało klucza klienta")
                    self.client_key = key
                    save_key(self.host, key)
                    ws.sock.settimeout(10.0)
                    return key

                if msg.get("type") == "error":
                    raise WebOsError(f"parowanie odrzucone: {msg.get('error')}")

            raise WebOsError(
                "minął czas na potwierdzenie na ekranie"
                + (" — pytanie zostało wyświetlone, ale nikt go nie zaakceptował"
                   if prompted else " — urządzenie nie pokazało pytania")
            )

    def close(self) -> None:
        with self._lock:
            if self._pointer:
                self._pointer.close()
                self._pointer = None
            if self._ws:
                self._ws.close()
                self._ws = None

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._ws.sock is not None

    # ---- żądania ----

    def request(self, uri: str, payload: dict | None = None,
                timeout: float = 8.0) -> dict:
        """Wysyła żądanie i czeka na odpowiedź o tym samym identyfikatorze.

        Urządzenie miesza odpowiedzi z powiadomieniami o zmianach stanu,
        więc dopasowujemy po `id`, a nie po kolejności.
        """
        with self._lock:
            if not self.connected:
                raise WebOsError("brak połączenia — najpierw connect()")
            self._counter += 1
            request_id = f"req_{self._counter}"
            self._ws.send(json.dumps({
                "type": "request", "id": request_id,
                "uri": uri, "payload": payload or {},
            }))

            deadline = time.time() + timeout
            while time.time() < deadline:
                self._ws.sock.settimeout(max(0.5, deadline - time.time()))
                try:
                    raw = self._ws.recv()
                except socket.timeout:
                    break
                if raw is None:
                    self._ws = None
                    raise WebOsError("urządzenie zamknęło połączenie")
                msg = json.loads(raw)
                if msg.get("id") != request_id:
                    continue                      # cudza odpowiedź albo zdarzenie
                if msg.get("type") == "error":
                    raise WebOsError(msg.get("error") or "urządzenie zwróciło błąd")
                return msg.get("payload", {})
            raise WebOsError(f"brak odpowiedzi na {uri}")

    # ---- konkretne akcje ----

    def power_off(self) -> dict:
        return self.request(COMMANDS["power_off"])

    def volume(self) -> dict:
        return self.request(COMMANDS["get_volume"])

    def set_volume(self, level: int) -> dict:
        return self.request(COMMANDS["set_volume"], {"volume": max(0, min(100, int(level)))})

    def set_mute(self, on: bool) -> dict:
        return self.request(COMMANDS["set_mute"], {"mute": bool(on)})

    def inputs(self) -> list[dict]:
        return self.request(COMMANDS["get_inputs"]).get("devices", [])

    def switch_input(self, input_id: str) -> dict:
        return self.request(COMMANDS["switch_input"], {"inputId": input_id})

    def apps(self) -> list[dict]:
        return self.request(COMMANDS["list_apps"], timeout=12.0).get("launchPoints", [])

    def launch(self, app_id: str) -> dict:
        return self.request(COMMANDS["launch_app"], {"id": app_id})

    def foreground_app(self) -> dict:
        return self.request(COMMANDS["foreground"])

    def toast(self, message: str) -> dict:
        return self.request(COMMANDS["toast"], {"message": message})

    def system_info(self) -> dict:
        return self.request(COMMANDS["system_info"])

    def software_info(self) -> dict:
        return self.request(COMMANDS["sw_info"])

    def power_state(self) -> dict:
        return self.request(COMMANDS["power_state"])

    # ---- pilot -------------------------------------------------------

    def pointer(self) -> "PointerInput":
        """Zestawia gniazdo pilota i trzyma je otwarte między naciśnięciami."""
        if self._pointer is not None and self._pointer.connected:
            return self._pointer
        info = self.request("ssap://com.webos.service.networkinput/getPointerInputSocket")
        path = info.get("socketPath")
        if not path:
            raise WebOsError("urządzenie nie udostępniło gniazda pilota")
        pointer = PointerInput(path)
        pointer.connect()
        self._pointer = pointer
        return pointer

    def press(self, button: str) -> None:
        try:
            self.pointer().button(button)
        except WebOsError:
            # Gniazdo pilota bywa zrywane niezależnie od głównego połączenia.
            self._pointer = None
            self.pointer().button(button)


class PointerInput:
    """Drugie gniazdo WebSocket — emulacja pilota i myszy.

    Adres dostajemy z `getPointerInputSocket`. Protokół jest tekstowy:
    pary `klucz:wartość` w liniach, blok kończy pusta linia.

        type:button
        name:HOME
        <pusta linia>

    To jest jedyna droga do menu ekranowego rzutnika, gdy podczerwień nie
    dociera — a menu zawiera ustawienia, których SSAP nie wystawia
    (sprawdzone: kluczy timerów nie ma w `settings` na tym modelu).
    """

    # Nazwy przycisków przyjmowane przez webOS.
    BUTTONS = [
        "HOME", "BACK", "EXIT", "MENU", "INFO", "SETTINGS",
        "UP", "DOWN", "LEFT", "RIGHT", "ENTER",
        "VOLUMEUP", "VOLUMEDOWN", "MUTE",
        "CHANNELUP", "CHANNELDOWN",
        "PLAY", "PAUSE", "STOP", "REWIND", "FASTFORWARD",
        "RED", "GREEN", "YELLOW", "BLUE",
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
        "DASH", "ASTERISK", "CC", "GUIDE", "QMENU", "LIST", "POWER",
    ]

    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path
        self._ws: WebSocket | None = None

    def connect(self) -> None:
        # ws://host:port/resources/<hash>/netinput.pointer.sock
        rest = self.socket_path.split("://", 1)[1]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        ws = WebSocket(host, int(port or SSAP_PORT))
        ws.path = "/" + path
        ws.connect()
        self._ws = ws

    def close(self) -> None:
        if self._ws:
            self._ws.close()
            self._ws = None

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._ws.sock is not None

    def button(self, name: str) -> None:
        name = name.upper()
        if name not in self.BUTTONS:
            raise WebOsError(f"nieznany przycisk: {name}")
        self._command(f"type:button\nname:{name}\n\n")

    def move(self, dx: int, dy: int, drag: bool = False) -> None:
        self._command(f"type:move\ndx:{int(dx)}\ndy:{int(dy)}\n"
                      f"down:{1 if drag else 0}\n\n")

    def click(self) -> None:
        self._command("type:click\n\n")

    def scroll(self, dy: int) -> None:
        self._command(f"type:scroll\ndx:0\ndy:{int(dy)}\n\n")

    def _command(self, text: str) -> None:
        if not self.connected:
            raise WebOsError("gniazdo pilota nie jest połączone")
        self._ws.send(text)


def wake_on_lan(mac: str, broadcast: str = "255.255.255.255") -> None:
    """Budzi urządzenie magicznym pakietem.

    SSAP potrafi wyłączyć, ale nie włączyć — w czuwaniu webOS zwija interfejs
    sieciowy. WoL to jedyna droga, o ile w menu włączone jest budzenie przez sieć.
    """
    clean = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(clean) != 12:
        raise ValueError(f"nieprawidłowy MAC: {mac}")
    packet = b"\xff" * 6 + bytes.fromhex(clean) * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        for port in (7, 9):
            s.sendto(packet, (broadcast, port))
    finally:
        s.close()


if __name__ == "__main__":
    import sys

    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.75"
    dev = WebOsDevice(host)
    print(f"Łączę z {host} ...")
    key = dev.connect(on_prompt=lambda: print(
        "\n  >>> POTWIERDŹ NA EKRANIE URZĄDZENIA <<<\n"))
    print(f"  sparowano, klucz: {key[:16]}...\n")

    for label, fn in (("informacje o systemie", dev.system_info),
                      ("oprogramowanie", dev.software_info),
                      ("stan zasilania", dev.power_state),
                      ("głośność", dev.volume),
                      ("aplikacja na wierzchu", dev.foreground_app)):
        try:
            print(f"  {label}: {fn()}")
        except WebOsError as e:
            print(f"  {label}: BŁĄD {e}")

    try:
        print("\n  wejścia:")
        for i in dev.inputs():
            print(f"    {i.get('id'):<14} {i.get('label'):<20} "
                  f"{'PODŁĄCZONE' if i.get('connected') else ''}")
    except WebOsError as e:
        print("  wejścia: BŁĄD", e)

    dev.close()
