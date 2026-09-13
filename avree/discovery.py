"""Wykrywanie amplitunerów Denon/Marantz w sieci lokalnej.

Dwie metody, obie bez zewnętrznych zależności:
  1. SSDP M-SEARCH (UPnP) - szybkie, zwraca też opis urządzenia.
  2. Skan puli adresów po portach sterowania - fallback, gdy router
     gubi multicast albo AVR ma wyłączone UPnP.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import re
import socket
import urllib.request
from dataclasses import dataclass, field

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900

# Porty sterowania Denon/Marantz
PORT_TELNET = 23      # protokół ASCII, push zmian stanu w czasie rzeczywistym
PORT_HTTP = 8080      # /goform/... (na części modeli także 80)
PORT_HEOS = 1255      # HEOS CLI

_SSDP_QUERY = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: {st}\r\n"
    "\r\n"
)

# ST-y, na które odpowiadają amplitunery D+M
_SEARCH_TARGETS = (
    "urn:schemas-upnp-org:device:MediaRenderer:1",
    "urn:schemas-denon-com:device:ACT-Denon:1",
    "upnp:rootdevice",
)


@dataclass
class Discovered:
    host: str
    location: str | None = None
    server: str | None = None
    open_ports: list[int] = field(default_factory=list)
    model: str | None = None

    def __str__(self) -> str:
        bits = [self.host]
        if self.model:
            bits.append(f"({self.model})")
        if self.open_ports:
            bits.append("porty: " + ",".join(str(p) for p in self.open_ports))
        return "  ".join(bits)


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def scan_ports(host: str, timeout: float = 0.4) -> list[int]:
    """Zwraca listę otwartych portów sterowania na danym hoście."""
    return [p for p in (PORT_TELNET, PORT_HTTP, PORT_HEOS) if _port_open(host, p, timeout)]


def ssdp_search(timeout: float = 3.0) -> dict[str, Discovered]:
    """M-SEARCH po multicaście. Zwraca mapę host -> Discovered."""
    found: dict[str, Discovered] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)
    try:
        for st in _SEARCH_TARGETS:
            try:
                sock.sendto(_SSDP_QUERY.format(st=st).encode(), (SSDP_ADDR, SSDP_PORT))
            except OSError:
                pass
        while True:
            try:
                data, addr = sock.recvfrom(65507)
            except socket.timeout:
                break
            text = data.decode("utf-8", "replace")
            host = addr[0]
            entry = found.setdefault(host, Discovered(host=host))
            if m := re.search(r"^LOCATION:\s*(.+)$", text, re.I | re.M):
                entry.location = m.group(1).strip()
            if m := re.search(r"^SERVER:\s*(.+)$", text, re.I | re.M):
                entry.server = m.group(1).strip()
    finally:
        sock.close()
    return found


def fetch_model(host: str, timeout: float = 2.0) -> str | None:
    """Pyta AVR o nazwę modelu przez /goform/Deviceinfo.xml."""
    for port in (PORT_HTTP, 80):
        url = f"http://{host}:{port}/goform/Deviceinfo.xml"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                xml = r.read().decode("utf-8", "replace")
        except Exception:
            continue
        if m := re.search(r"<ModelName>(.*?)</ModelName>", xml, re.S):
            return m.group(1).strip()
        if m := re.search(r"<FriendlyName>(.*?)</FriendlyName>", xml, re.S):
            return m.group(1).strip()
    return None


def sweep_subnet(cidr: str, workers: int = 128) -> list[Discovered]:
    """Skan całej podsieci po porcie telnet/HTTP. Fallback gdy SSDP milczy."""
    net = ipaddress.ip_network(cidr, strict=False)
    hosts = [str(h) for h in net.hosts()]
    out: list[Discovered] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for host, ports in zip(hosts, pool.map(scan_ports, hosts)):
            if ports:
                out.append(Discovered(host=host, open_ports=ports))
    return out


def discover(cidr: str | None = None) -> list[Discovered]:
    """SSDP, a jeśli nic nie znajdzie sensownego - skan podsieci."""
    results: dict[str, Discovered] = {}
    for host, entry in ssdp_search().items():
        entry.open_ports = scan_ports(host)
        if PORT_TELNET in entry.open_ports or PORT_HTTP in entry.open_ports:
            entry.model = fetch_model(host)
            results[host] = entry

    if not results and cidr:
        for entry in sweep_subnet(cidr):
            entry.model = fetch_model(entry.host)
            results[entry.host] = entry

    # AVR odpowiada na Deviceinfo.xml - to nasz najlepszy filtr
    return sorted(results.values(), key=lambda d: (d.model is None, d.host))


if __name__ == "__main__":
    import sys

    cidr = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.0/24"
    print(f"SSDP + skan {cidr} ...\n")
    for d in discover(cidr):
        print(d)
