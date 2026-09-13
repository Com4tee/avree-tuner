"""Wykrywanie amplitunerów Denon/Marantz w dowolnej sieci lokalnej.

Nic tu nie jest zaszyte na sztywno: adresy podsieci biorą się z interfejsów
tego komputera, a SSDP leci z każdego z nich osobno. Dzięki temu działa też
tam, gdzie router gubi multicast albo maszyna siedzi na kilku sieciach naraz
(Wi-Fi + LAN + VPN + wirtualne interfejsy Dockera czy VirtualBoxa).

Kolejność prób, od najtańszej do najdroższej:
  1. zapamiętany adres z poprzedniego uruchomienia
  2. SSDP M-SEARCH na każdym interfejsie
  3. skan portów sterowania po każdej wykrytej podsieci /24
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import os
import re
import socket
import struct
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900

PORT_TELNET = 23      # protokół ASCII, push zmian stanu w czasie rzeczywistym
PORT_HEOS = 1255      # HEOS CLI (nowsze modele)
HTTP_PORTS = (80, 8080)   # /goform bywa na 80 albo na 8080 zależnie od rocznika

CONFIG_PATH = Path(
    os.environ.get("APPDATA") or Path.home() / ".config"
) / "avree-tuner" / "config.json"

_SSDP_QUERY = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: {st}\r\n"
    "\r\n"
)

_SEARCH_TARGETS = (
    "urn:schemas-upnp-org:device:MediaRenderer:1",
    "urn:schemas-denon-com:device:ACT-Denon:1",
    "upnp:rootdevice",
)

# Po czym poznajemy, że to nasz sprzęt, a nie przypadkowy renderer UPnP.
_BRAND_HINTS = ("denon", "marantz", "avr-", "avc-", "sr60", "sr70", "nr1")


@dataclass
class Discovered:
    host: str
    model: str | None = None
    name: str | None = None
    http_port: int | None = None
    open_ports: list[int] = field(default_factory=list)
    source: str = ""

    @property
    def is_receiver(self) -> bool:
        """Amplituner potwierdzony: odpowiedział na Deviceinfo.xml."""
        return self.model is not None

    def as_dict(self) -> dict:
        return {"host": self.host, "model": self.model, "name": self.name,
                "http_port": self.http_port, "open_ports": self.open_ports,
                "source": self.source, "confirmed": self.is_receiver}

    def __str__(self) -> str:
        bits = [self.host]
        if self.model:
            bits.append(f"({self.model})")
        if self.name:
            bits.append(f'"{self.name}"')
        if self.open_ports:
            bits.append("porty " + ",".join(str(p) for p in self.open_ports))
        return "  ".join(bits)


# --------------------------------------------------------------------
# zapamiętany adres
# --------------------------------------------------------------------

def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_host(host: str) -> None:
    """Zapisuje ostatni działający adres, żeby kolejny start był natychmiastowy."""
    cfg = load_config()
    cfg["host"] = host
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass          # brak zapisu to nie powód, żeby nie działać


# --------------------------------------------------------------------
# interfejsy i podsieci
# --------------------------------------------------------------------

def local_ips() -> list[str]:
    """Adresy IPv4 tego komputera, bez pętli zwrotnej."""
    found: list[str] = []

    # Trik z UDP: nie wysyła pakietu, ale system wybiera interfejs wyjściowy.
    for target in ("8.8.8.8", "192.168.1.1", "10.0.0.1", "172.16.0.1"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 9))
            ip = s.getsockname()[0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
        except OSError:
            pass
        finally:
            s.close()

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except socket.gaierror:
        pass

    return found


def local_subnets(prefix: int = 24) -> list[str]:
    """Podsieci /24 wokół każdego lokalnego adresu, bez powtórzeń."""
    nets: list[str] = []
    for ip in local_ips():
        try:
            net = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
        except ValueError:
            continue
        text = str(net)
        if text not in nets:
            nets.append(text)
    return nets


# --------------------------------------------------------------------
# SSDP
# --------------------------------------------------------------------

def ssdp_search(timeout: float = 2.5) -> dict[str, str]:
    """M-SEARCH z każdego interfejsu. Zwraca host -> nagłówek SERVER/LOCATION."""
    found: dict[str, str] = {}
    sources = local_ips() or [""]

    for source_ip in sources:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
        try:
            if source_ip:
                # Przypięcie do konkretnego interfejsu - bez tego Windows
                # wysyła multicast tylko jedną, przypadkową drogą.
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                                socket.inet_aton(source_ip))
                sock.bind((source_ip, 0))
            sock.settimeout(timeout)
            for st in _SEARCH_TARGETS:
                try:
                    sock.sendto(_SSDP_QUERY.format(st=st).encode(), (SSDP_ADDR, SSDP_PORT))
                except OSError:
                    pass
            while True:
                try:
                    data, addr = sock.recvfrom(65507)
                except (socket.timeout, OSError):
                    break
                found.setdefault(addr[0], data.decode("utf-8", "replace"))
        except OSError:
            pass
        finally:
            sock.close()
    return found


# --------------------------------------------------------------------
# identyfikacja i skan
# --------------------------------------------------------------------

def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def identify(host: str, timeout: float = 2.0) -> Discovered | None:
    """Potwierdza amplituner przez /goform/Deviceinfo.xml na 80 albo 8080."""
    for port in HTTP_PORTS:
        try:
            with urllib.request.urlopen(
                    f"http://{host}:{port}/goform/Deviceinfo.xml", timeout=timeout) as r:
                xml = r.read(20000).decode("utf-8", "replace")
        except Exception:
            continue
        model = re.search(r"<ModelName>(.*?)</ModelName>", xml, re.S)
        if not model:
            continue
        name = re.search(r"<FriendlyName>(.*?)</FriendlyName>", xml, re.S)
        return Discovered(
            host=host,
            model=model.group(1).strip().lstrip("*"),
            name=name.group(1).strip() if name else None,
            http_port=port,
        )
    return None


def _inspect(host: str) -> Discovered | None:
    """Pełne sprawdzenie jednego hosta: porty + potwierdzenie modelu.

    Rozstrzyga HTTP, nie telnet. Amplituner przyjmuje tylko JEDNO połączenie
    telnet naraz, więc gdy trzyma je już nasza własna aplikacja albo appka
    Denona, port 23 odrzuca połączenia i wygląda na zamknięty. Opieranie
    wykrywania na nim dawałoby "nie znaleziono amplitunera" przy działającym
    amplitunerze.
    """
    entry = identify(host)
    ports = [p for p in (PORT_TELNET, *HTTP_PORTS, PORT_HEOS) if _port_open(host, p)]
    if entry is None:
        # Bez potwierdzenia z Deviceinfo.xml zostaje tylko poszlaka: otwarty
        # telnet. Taki host wraca jako kandydat, nie jako pewne trafienie.
        if PORT_TELNET not in ports:
            return None
        entry = Discovered(host=host)
    entry.open_ports = ports
    return entry


def sweep(cidr: str, workers: int = 160, progress=None) -> list[Discovered]:
    """Skan jednej podsieci. `progress` dostaje (zrobione, wszystkie)."""
    hosts = [str(h) for h in ipaddress.ip_network(cidr, strict=False).hosts()]
    out: list[Discovered] = []
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for entry in pool.map(_inspect, hosts):
            done += 1
            if progress and done % 16 == 0:
                progress(done, len(hosts))
            if entry:
                entry.source = "skan"
                out.append(entry)
    return out


def discover(cidr: str | None = None, progress=None) -> list[Discovered]:
    """Pełne wykrywanie. Zwraca potwierdzone amplitunery przed kandydatami."""
    results: dict[str, Discovered] = {}

    # 1. zapamiętany adres - najtańsze trafienie
    remembered = load_config().get("host")
    if remembered:
        entry = _inspect(remembered)
        if entry:
            entry.source = "zapamiętany"
            results[remembered] = entry
            if entry.is_receiver:
                return [entry]

    # 2. SSDP
    for host, payload in ssdp_search().items():
        if host in results:
            continue
        low = payload.lower()
        entry = _inspect(host)
        if entry is None:
            continue
        entry.source = "ssdp"
        if entry.is_receiver or any(h in low for h in _BRAND_HINTS):
            results[host] = entry

    if any(e.is_receiver for e in results.values()):
        return _sorted(results)

    # 3. skan podsieci
    for net in ([cidr] if cidr else local_subnets()):
        if progress:
            progress(0, 0, net)
        for entry in sweep(net, progress=(lambda d, t: progress(d, t, net)) if progress else None):
            results.setdefault(entry.host, entry)
        if any(e.is_receiver for e in results.values()):
            break

    return _sorted(results)


def _sorted(results: dict[str, Discovered]) -> list[Discovered]:
    return sorted(results.values(), key=lambda d: (not d.is_receiver, d.host))


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else None
    print("Interfejsy :", ", ".join(local_ips()) or "brak")
    print("Podsieci   :", ", ".join(local_subnets()) or "brak")
    print()

    seen = set()

    def show(done, total, net=None):
        if net and net not in seen:
            seen.add(net)
            print(f"skanuję {net} ...")

    for d in discover(target, progress=show):
        mark = "[POTWIERDZONY]" if d.is_receiver else "[kandydat]    "
        print(f"  {mark} {d}  ({d.source})")
