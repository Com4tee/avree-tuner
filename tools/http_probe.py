"""Rozpoznanie warstwy HTTP amplitunera (port 8080 / 80).

Denon wystawia dwa rodzaje endpointów:
  * GET /goform/*.xml            - odczyt stanu
  * POST /goform/AppCommand.xml  - komendy aplikacji mobilnej (XML w body)

Ten drugi jest ciekawszy: to kanał, z którego korzysta oficjalna appka
Denon AVR, więc tam siedzą rzeczy niedostępne po telnecie.
"""
from __future__ import annotations

import sys
import time
import json
import urllib.request
import urllib.error
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

GET_PATHS = [
    "/goform/Deviceinfo.xml",
    "/goform/formMainZone_MainZoneXmlStatus.xml",
    "/goform/formMainZone_MainZoneXmlStatusLite.xml",
    "/goform/formZone2_Zone2XmlStatus.xml",
    "/goform/formNetAudio_StatusXml.xml",
    "/goform/formMainZone_MainZoneXml.xml",
    "/",
    "/ajax/globals",
    "/upnp/desc/aios_device/aios_device.xml",
    "/description.xml",
]

APP_COMMANDS = [
    "GetAllZonePowerStatus",
    "GetSurroundModeStatus",
    "GetAudyssey",
    "GetToneControl",
    "GetSubwooferLevel",
    "GetChannelVolume",
    "GetSpeakerDistance",
    "GetDeviceInfo",
    "GetSourceStatus",
    "GetVolumeLevel",
    "GetAllZoneSource",
    "GetRenameSource",
]


def http_get(host, port, path, timeout=3.0):
    url = f"http://{host}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, str(e)


def app_command(host, port, names, timeout=5.0):
    """POST /goform/AppCommand.xml - format: <tx><cmd id="1">NAZWA</cmd>...</tx>"""
    parts = ['<?xml version="1.0" encoding="utf-8"?>', "<tx>"]
    for n in names:
        parts.append(f'<cmd id="1">{n}</cmd>')
    parts.append("</tx>")
    body = "\n".join(parts).encode("utf-8")
    req = urllib.request.Request(
        f"http://{host}:{port}/goform/AppCommand.xml",
        data=body,
        headers={"Content-Type": "text/xml; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, str(e)


def main(host="192.168.0.73"):
    report = {"host": host, "get": {}, "app_command": {}}

    for port in (8080, 80):
        print(f"\n########## PORT {port} ##########")
        for path in GET_PATHS:
            status, body = http_get(host, port, path)
            key = f"{port}{path}"
            if status == 200 and body:
                report["get"][key] = body
                preview = " ".join(body.split())[:180]
                print(f"  [200 {len(body):>6}B] {path}\n        {preview}")
            else:
                print(f"  [{str(status):>8}] {path}")

    print("\n########## AppCommand.xml ##########")
    for port in (8080, 80):
        status, body = app_command(host, port, APP_COMMANDS)
        print(f"  port {port}: HTTP {status}, {len(body)} B")
        if status == 200 and body:
            report["app_command"][str(port)] = body
            print("  " + " ".join(body.split())[:1500])
            break

    out = Path(__file__).resolve().parent.parent / "captures" / \
        f"http-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nZapisano: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "192.168.0.73"))
