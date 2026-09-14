"""Klient Android TV Remote v2 — pilot do Google TV.

Dwa porty, oba TLS z certyfikatem klienta (samopodpisanym):
  6467 — parowanie, jednorazowo, z sześcioznakowym kodem z ekranu
  6466 — pilot, na stałe

Ramki: długość jako varint, potem komunikat protobuf. Kodowanie ręczne,
tak samo jak w kliencie Cast — dla kilkunastu pól biblioteka protobuf
byłaby nieproporcjonalna.

Sekret parowania ma wbudowany BAJT KONTROLNY: pierwszy bajt kodu z ekranu
musi się równać pierwszemu bajtowi wyliczonego skrótu. Dzięki temu da się
sprawdzić poprawność obliczeń LOKALNIE, zanim cokolwiek poleci do
urządzenia — i nie trzeba zgadywać metodą prób na cudzym telewizorze.
Wykorzystujemy to: liczymy skrót dla kilku wariantów kodowania liczb
i wybieramy ten, który przechodzi test kontrolny.
"""

from __future__ import annotations

import hashlib
import json
import socket
import ssl
import struct
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .discovery import CONFIG_PATH

PAIR_PORT = 6467
REMOTE_PORT = 6466

CERT_PATH = CONFIG_PATH.parent / "androidtv-cert.pem"
KEY_PATH = CONFIG_PATH.parent / "androidtv-key.pem"
PAIRED_PATH = CONFIG_PATH.parent / "androidtv-paired.json"

# Kody klawiszy Androida — te same, którymi posługuje się system.
KEYS = {
    "HOME": 3, "BACK": 4, "DPAD_UP": 19, "DPAD_DOWN": 20,
    "DPAD_LEFT": 21, "DPAD_RIGHT": 22, "DPAD_CENTER": 23,
    "VOLUME_UP": 24, "VOLUME_DOWN": 25, "POWER": 26, "MUTE": 164,
    "MENU": 82, "SEARCH": 84,
    "MEDIA_PLAY_PAUSE": 85, "MEDIA_STOP": 86, "MEDIA_NEXT": 87,
    "MEDIA_PREVIOUS": 88, "MEDIA_REWIND": 89, "MEDIA_FAST_FORWARD": 90,
    "CHANNEL_UP": 166, "CHANNEL_DOWN": 167,
    "TV": 170, "GUIDE": 172, "INFO": 165, "SETTINGS": 176,
    "ASSIST": 219, "APP_SWITCH": 187,
    "0": 7, "1": 8, "2": 9, "3": 10, "4": 11,
    "5": 12, "6": 13, "7": 14, "8": 15, "9": 16,
}

DIRECTION_SHORT = 3


class AndroidTvError(RuntimeError):
    pass


# --------------------------------------------------------------------
# protobuf: kodowanie i dekodowanie tego, czego używamy
# --------------------------------------------------------------------

def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
    raise AndroidTvError("uszkodzony varint")


def _tag_bytes(number: int, payload: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(payload)) + payload


def _tag_varint(number: int, value: int) -> bytes:
    return _varint((number << 3) | 0) + _varint(value)


def parse_fields(body: bytes) -> dict[int, list]:
    """Surowe pola protobuf: numer -> lista wartości (bytes albo int)."""
    out: dict[int, list] = {}
    pos = 0
    while pos < len(body):
        tag, pos = _read_varint(body, pos)
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            value, pos = _read_varint(body, pos)
        elif wire == 2:
            length, pos = _read_varint(body, pos)
            value = body[pos:pos + length]
            pos += length
        elif wire == 5:
            value = body[pos:pos + 4]
            pos += 4
        elif wire == 1:
            value = body[pos:pos + 8]
            pos += 8
        else:
            break
        out.setdefault(number, []).append(value)
    return out


# --------------------------------------------------------------------
# certyfikat klienta
# --------------------------------------------------------------------

def ensure_certificate() -> tuple[Path, Path]:
    """Tworzy samopodpisany certyfikat klienta, jeśli go jeszcze nie ma.

    Urządzenie wiąże parowanie z konkretnym certyfikatem — jego utrata
    oznacza konieczność parowania od nowa.
    """
    if CERT_PATH.exists() and KEY_PATH.exists():
        return CERT_PATH, KEY_PATH

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import datetime

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "avree-tuner"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AVREE"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )

    CERT_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEY_PATH.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    CERT_PATH.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return CERT_PATH, KEY_PATH


def _client_context() -> ssl.SSLContext:
    cert, key = ensure_certificate()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.load_cert_chain(str(cert), str(key))
    return ctx


# --------------------------------------------------------------------
# transport
# --------------------------------------------------------------------

class FramedTls:
    """TLS z ramkowaniem: varint z długością, potem komunikat."""

    def __init__(self, host: str, port: int, timeout: float = 10.0) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.sock: ssl.SSLSocket | None = None

    def connect(self) -> None:
        ctx = _client_context()
        try:
            raw = socket.create_connection((self.host, self.port), self.timeout)
            self.sock = ctx.wrap_socket(raw, server_hostname=self.host)
        except OSError as e:
            raise AndroidTvError(f"nie mogę się połączyć z {self.host}:{self.port} — {e}") from e
        self.sock.settimeout(self.timeout)

    def peer_public_numbers(self):
        """Klucz publiczny urządzenia — potrzebny do skrótu parowania."""
        from cryptography import x509
        der = self.sock.getpeercert(binary_form=True)
        return x509.load_der_x509_certificate(der).public_key().public_numbers()

    def send(self, payload: bytes) -> None:
        self.sock.sendall(_varint(len(payload)) + payload)

    def recv(self) -> bytes:
        # Długość przychodzi jako varint, więc czytamy bajt po bajcie.
        length = shift = 0
        while True:
            chunk = self.sock.recv(1)
            if not chunk:
                raise AndroidTvError("urządzenie zamknęło połączenie")
            byte = chunk[0]
            length |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        body = b""
        while len(body) < length:
            chunk = self.sock.recv(length - len(body))
            if not chunk:
                raise AndroidTvError("urwana ramka")
            body += chunk
        return body

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None


# --------------------------------------------------------------------
# parowanie
# --------------------------------------------------------------------

def _int_variants(value: int) -> list[bytes]:
    """Kilka sposobów zapisu liczby na bajty — sprawdzimy, który pasuje.

    Oryginalna implementacja jest w Javie i używa BigInteger.toByteArray(),
    które dokleja wiodące zero dla liczb dodatnich z ustawionym najstarszym
    bitem. Porty na inne języki robią to różnie. Zamiast zgadywać,
    generujemy warianty i wybieramy ten, który przejdzie bajt kontrolny.
    """
    size = (value.bit_length() + 7) // 8
    plain = value.to_bytes(size, "big")
    return [plain, b"\x00" + plain, plain.lstrip(b"\x00")]


def _pairing_secret(code: str, client_pub, server_pub) -> bytes:
    """Skrót parowania, z lokalną weryfikacją bajtu kontrolnego."""
    code = code.strip().replace(" ", "")
    if len(code) != 6:
        raise AndroidTvError("kod z ekranu ma sześć znaków szesnastkowych")
    try:
        code_bytes = bytes.fromhex(code)
    except ValueError as e:
        raise AndroidTvError(f"kod nie jest szesnastkowy: {code}") from e

    for cm in _int_variants(client_pub.n):
        for ce in _int_variants(client_pub.e):
            for sm in _int_variants(server_pub.n):
                for se in _int_variants(server_pub.e):
                    h = hashlib.sha256()
                    h.update(cm); h.update(ce); h.update(sm); h.update(se)
                    h.update(code_bytes[1:])
                    digest = h.digest()
                    if digest[0] == code_bytes[0]:
                        return digest
    raise AndroidTvError(
        "żaden wariant obliczeń nie zgadza się z bajtem kontrolnym kodu — "
        "sprawdź, czy kod przepisany jest dokładnie tak, jak na ekranie")


def pair(host: str, code_callback, client_name: str = "AVREE Tuner") -> bool:
    """Parowanie. `code_callback()` ma zwrócić kod pokazany na ekranie."""
    link = FramedTls(host, PAIR_PORT)
    link.connect()
    try:
        # 1. prośba o parowanie
        request = _tag_bytes(1, b"avree-tuner") + _tag_bytes(2, client_name.encode())
        link.send(_tag_varint(1, 2) + _tag_varint(2, 200) + _tag_bytes(10, request))
        _expect_ok(link.recv(), "prośba o parowanie")

        # 2. sposób kodowania: sześć znaków szesnastkowych, rola wejścia
        encoding = _tag_varint(1, 3) + _tag_varint(2, 6)
        option = _tag_bytes(1, encoding) + _tag_varint(3, 1)
        link.send(_tag_varint(1, 2) + _tag_varint(2, 200) + _tag_bytes(20, option))
        _expect_ok(link.recv(), "ustalenie kodowania")

        # 3. konfiguracja — po niej urządzenie pokazuje kod
        config = _tag_bytes(1, encoding) + _tag_varint(2, 1)
        link.send(_tag_varint(1, 2) + _tag_varint(2, 200) + _tag_bytes(30, config))
        _expect_ok(link.recv(), "konfiguracja")

        client_pub = _client_public_numbers()
        server_pub = link.peer_public_numbers()

        code = code_callback()
        secret = _pairing_secret(code, client_pub, server_pub)

        link.send(_tag_varint(1, 2) + _tag_varint(2, 200)
                  + _tag_bytes(40, _tag_bytes(1, secret)))
        _expect_ok(link.recv(), "sekret")

        _remember(host)
        return True
    finally:
        link.close()


def _client_public_numbers():
    from cryptography.hazmat.primitives import serialization
    from cryptography import x509
    cert_path, _ = ensure_certificate()
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return cert.public_key().public_numbers()


def _expect_ok(frame: bytes, step: str) -> dict:
    fields = parse_fields(frame)
    status = fields.get(2, [0])[0]
    if status != 200:
        raise AndroidTvError(f"{step}: urządzenie odpowiedziało statusem {status}")
    return fields


def _remember(host: str) -> None:
    try:
        data = json.loads(PAIRED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[host] = True
    try:
        PAIRED_PATH.parent.mkdir(parents=True, exist_ok=True)
        PAIRED_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def is_paired(host: str) -> bool:
    try:
        return bool(json.loads(PAIRED_PATH.read_text(encoding="utf-8")).get(host))
    except (OSError, ValueError):
        return False


# --------------------------------------------------------------------
# pilot
# --------------------------------------------------------------------

@dataclass
class AndroidTv:
    host: str
    name: str = ""
    _link: FramedTls | None = field(default=None, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def connect(self) -> None:
        with self._lock:
            link = FramedTls(self.host, REMOTE_PORT)
            link.connect()
            self._link = link
            # Urządzenie zaczyna rozmowę: konfiguracja, potem prośba
            # o uaktywnienie. Odpowiadamy na obie, inaczej rozłącza.
            self._handshake()

    def _handshake(self) -> None:
        for _ in range(6):
            frame = self._link.recv()
            fields = parse_fields(frame)
            if 1 in fields:                       # remote_configure
                info = (_tag_bytes(1, b"AVREE Tuner") + _tag_bytes(2, b"AVREE")
                        + _tag_varint(3, 1) + _tag_bytes(4, b"1")
                        + _tag_bytes(5, b"pl.avree.tuner") + _tag_bytes(6, b"1.0"))
                self._link.send(_tag_bytes(1, _tag_varint(1, 1) + _tag_bytes(2, info)))
                continue
            if 2 in fields:                       # remote_set_active
                self._link.send(_tag_bytes(2, _tag_varint(1, 622)))
                return
            if 8 in fields:                       # ping
                self._pong(fields)
                return
        raise AndroidTvError("urządzenie nie dokończyło uzgadniania")

    def _pong(self, fields: dict) -> None:
        inner = parse_fields(fields[8][0])
        val = inner.get(1, [0])[0]
        self._link.send(_tag_bytes(9, _tag_varint(1, val)))

    @property
    def connected(self) -> bool:
        return self._link is not None and self._link.sock is not None

    def press(self, key: str) -> None:
        code = KEYS.get(key.upper())
        if code is None:
            raise AndroidTvError(f"nieznany klawisz: {key}")
        with self._lock:
            if not self.connected:
                self.connect()
            inject = _tag_varint(1, code) + _tag_varint(2, DIRECTION_SHORT)
            self._link.send(_tag_bytes(10, inject))

    def close(self) -> None:
        with self._lock:
            if self._link:
                self._link.close()
            self._link = None
