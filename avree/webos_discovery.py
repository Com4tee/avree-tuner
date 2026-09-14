"""Wyszukiwanie urządzeń LG webOS (rzutnik, telewizor) w sieci lokalnej.

Osobno od `discovery.py`, bo kryterium jest inne: amplituner poznajemy po
odpowiedzi na `Deviceinfo.xml`, a webOS po otwartym porcie SSAP.

Ważna nauka z rozpoznania: szukanie po MAC producenta zawodzi. W badanej
sieci były trzy urządzenia LG i to, które miało otwarty port LG IP Control,
wcale nie było rzutnikiem. Rozstrzyga funkcja, nie producent.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import re
import socket
import urllib.request

from .discovery import _port_open, local_subnets

SSAP_PORT = 3000
SSAP_TLS_PORT = 3001

# Nazwy modeli, które webOS zwraca dla usług pomocniczych — nie są
# oznaczeniem sprzętu, więc szukamy dalej.
GENERIC_MODELS = {"LG TV", "LG Smart TV", "LG WebOSTV DMRplus", ""}


def describe(host: str, timeout: float = 3.0) -> dict:
    """Nazwa i model z opisu UPnP, który webOS wystawia na losowym porcie.

    Odpowiedzi SSDP filtrujemy po adresie nadawcy. Bez tego filtra odpowiedzi
    multicast od innych urządzeń podszywają się pod odpytywany host — na tym
    się przejechałem przy pierwszym rozpoznaniu.
    """
    query = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        "ST: ssdp:all\r\n\r\n"
    ).encode()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    locations: set[str] = set()
    try:
        sock.sendto(query, (host, 1900))
        while True:
            try:
                data, addr = sock.recvfrom(65507)
            except (socket.timeout, OSError):
                break
            if addr[0] != host:
                continue
            m = re.search(r"LOCATION:\s*(.+)", data.decode("utf-8", "replace"), re.I)
            if m and host in m.group(1):
                locations.add(m.group(1).strip())
    except OSError:
        pass
    finally:
        sock.close()

    best = {"name": "", "model": ""}
    for loc in locations:
        try:
            with urllib.request.urlopen(loc, timeout=timeout) as r:
                xml = r.read(6000).decode("utf-8", "replace")
        except Exception:
            continue
        name = re.search(r"<friendlyName>(.*?)</friendlyName>", xml, re.S)
        model = re.search(r"<modelName>(.*?)</modelName>", xml, re.S)
        if name and not best["name"]:
            best["name"] = name.group(1).strip()
        if model and model.group(1).strip() not in GENERIC_MODELS:
            best["model"] = model.group(1).strip()
    return best


def find(cidr: str | None = None, workers: int = 128) -> list[dict]:
    """Zwraca urządzenia z otwartym portem SSAP, z nazwą i modelem jeśli się da."""
    found: list[dict] = []
    for net in ([cidr] if cidr else local_subnets()):
        hosts = [str(h) for h in ipaddress.ip_network(net, strict=False).hosts()]

        def alive(host: str) -> str | None:
            return host if _port_open(host, SSAP_PORT, 0.6) else None

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            candidates = [h for h in pool.map(alive, hosts) if h]

        for host in candidates:
            info = describe(host)
            found.append({
                "host": host,
                "name": info["name"],
                "model": info["model"],
                "tls": _port_open(host, SSAP_TLS_PORT, 0.6),
            })
        if found:
            break
    return found


if __name__ == "__main__":
    import sys

    for dev in find(sys.argv[1] if len(sys.argv) > 1 else None):
        label = dev["name"] or "(bez nazwy)"
        model = dev["model"] or "model nieustalony"
        print(f"  {dev['host']:<16} {label:<22} {model}")
