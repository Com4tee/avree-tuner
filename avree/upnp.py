"""Sterowanie amplitunerem jako odtwarzaczem UPnP/DLNA.

AVR-X3300W wystawia MediaRenderer na porcie 8080 z usługami AVTransport
i RenderingControl. Można mu podać adres HTTP dowolnego pliku audio,
a on go sam pobierze i odtworzy.

Ograniczenie ustalone przez GetProtocolInfo: renderer jest STEREO.
Brak AC3, E-AC3 i DTS. Materiał wielokanałowy wymaga HDMI albo optyki.
"""

from __future__ import annotations

import re
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

RENDERER_PORT = 8080
DESCRIPTION_PATH = "/description.xml"

AVTRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"
RENDERING = "urn:schemas-upnp-org:service:RenderingControl:1"
CONNECTION = "urn:schemas-upnp-org:service:ConnectionManager:1"

# Rozszerzenie -> typ MIME akceptowany przez renderer.
MIME_BY_EXT = {
    ".flac": "audio/flac", ".wav": "audio/wav", ".aiff": "audio/aiff",
    ".aif": "audio/aiff", ".mp3": "audio/mpeg", ".m4a": "audio/x-m4a",
    ".mp4": "audio/mp4", ".aac": "audio/vnd.dlna.adts", ".wma": "audio/x-ms-wma",
    ".dsf": "audio/x-dsd", ".dff": "audio/x-dsd",
}

# Formaty, których renderer nie przyjmie - wychwytujemy je zawczasu,
# żeby zamiast ciszy dać czytelny komunikat. Dwie osobne przyczyny:
# wielokanałowość i po prostu brak kodeka.
MULTICHANNEL_EXT = {
    ".ac3": "Dolby Digital", ".eac3": "Dolby Digital Plus", ".dts": "DTS",
    ".thd": "Dolby TrueHD", ".mlp": "Dolby TrueHD",
    ".mkv": "kontener wideo", ".mka": "kontener Matroska",
}

NO_CODEC_EXT = {
    ".ogg": "Ogg Vorbis", ".opus": "Opus", ".ape": "Monkey's Audio",
    ".wv": "WavPack", ".mpc": "Musepack", ".tak": "TAK", ".tta": "TTA",
}

UNSUPPORTED_EXT = MULTICHANNEL_EXT | NO_CODEC_EXT


class UpnpError(RuntimeError):
    pass


@dataclass
class Renderer:
    host: str
    port: int = RENDERER_PORT
    name: str = ""
    model: str = ""
    controls: dict[str, str] = field(default_factory=dict)
    sink_formats: list[str] = field(default_factory=list)

    def control_url(self, service: str) -> str:
        path = self.controls.get(service)
        if not path:
            raise UpnpError(f"amplituner nie wystawia usługi {service}")
        return f"http://{self.host}:{self.port}{path}"


def _soap(url: str, service: str, action: str, args: dict[str, str],
          timeout: float = 6.0) -> str:
    body_args = "".join(
        f"<{k}>{_escape(v)}</{k}>" for k, v in args.items()
    )
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"'
        ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:{action} xmlns:u="{service}">{body_args}</u:{action}>'
        "</s:Body></s:Envelope>"
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=envelope,
        headers={"Content-Type": 'text/xml; charset="utf-8"',
                 "SOAPACTION": f'"{service}#{action}"'},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:                                   # noqa: BLE001
        raise UpnpError(f"{action}: {e}") from e


def _escape(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace('"', "&quot;"))


def _tag(xml: str, name: str) -> str | None:
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", xml, re.S)
    return m.group(1).strip() if m else None


def describe(host: str, port: int = RENDERER_PORT, timeout: float = 5.0) -> Renderer:
    """Czyta description.xml i wyciąga adresy sterowania usługami."""
    url = f"http://{host}:{port}{DESCRIPTION_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            xml = r.read().decode("utf-8", "replace")
    except Exception as e:                                   # noqa: BLE001
        raise UpnpError(f"nie mogę odczytać {url}: {e}") from e

    rend = Renderer(host=host, port=port,
                    name=_tag(xml, "friendlyName") or "",
                    model=_tag(xml, "modelName") or "")
    for block in re.findall(r"<service>(.*?)</service>", xml, re.S):
        st = _tag(block, "serviceType")
        cu = _tag(block, "controlURL")
        if st and cu:
            rend.controls[st] = cu if cu.startswith("/") else "/" + cu
    return rend


def protocol_info(rend: Renderer) -> list[str]:
    """Lista formatów, które renderer przyjmuje (pole Sink)."""
    xml = _soap(rend.control_url(CONNECTION), CONNECTION, "GetProtocolInfo", {})
    sink = _tag(xml, "Sink") or ""
    mimes = []
    for entry in sink.split(","):
        parts = entry.split(":")
        if len(parts) >= 3 and parts[2] and parts[2] not in mimes:
            mimes.append(parts[2])
    rend.sink_formats = mimes
    return mimes


def transport_info(rend: Renderer) -> dict[str, str]:
    xml = _soap(rend.control_url(AVTRANSPORT), AVTRANSPORT,
                "GetTransportInfo", {"InstanceID": "0"})
    return {
        "state": _tag(xml, "CurrentTransportState") or "UNKNOWN",
        "status": _tag(xml, "CurrentTransportStatus") or "",
    }


def position_info(rend: Renderer) -> dict[str, str]:
    xml = _soap(rend.control_url(AVTRANSPORT), AVTRANSPORT,
                "GetPositionInfo", {"InstanceID": "0"})
    return {
        "duration": _tag(xml, "TrackDuration") or "",
        "elapsed": _tag(xml, "RelTime") or "",
        "uri": _tag(xml, "TrackURI") or "",
    }


def _didl(title: str, url: str, mime: str) -> str:
    return (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<item id="1" parentID="0" restricted="1">'
        f"<dc:title>{_escape(title)}</dc:title>"
        "<upnp:class>object.item.audioItem.musicTrack</upnp:class>"
        f'<res protocolInfo="http-get:*:{mime}:*">{_escape(url)}</res>'
        "</item></DIDL-Lite>"
    )


def play_url(rend: Renderer, url: str, title: str, mime: str) -> None:
    """Podaje amplitunerowi adres do odtworzenia i uruchamia transport."""
    _soap(rend.control_url(AVTRANSPORT), AVTRANSPORT, "SetAVTransportURI",
          {"InstanceID": "0", "CurrentURI": url,
           "CurrentURIMetaData": _didl(title, url, mime)})
    _soap(rend.control_url(AVTRANSPORT), AVTRANSPORT, "Play",
          {"InstanceID": "0", "Speed": "1"})


def pause(rend: Renderer) -> None:
    _soap(rend.control_url(AVTRANSPORT), AVTRANSPORT, "Pause", {"InstanceID": "0"})


def resume(rend: Renderer) -> None:
    _soap(rend.control_url(AVTRANSPORT), AVTRANSPORT, "Play",
          {"InstanceID": "0", "Speed": "1"})


def stop(rend: Renderer) -> None:
    _soap(rend.control_url(AVTRANSPORT), AVTRANSPORT, "Stop", {"InstanceID": "0"})


def local_ip_towards(host: str) -> str:
    """Adres tego komputera widziany od strony amplitunera.

    Potrzebny, bo URL pliku musi być osiągalny dla amplitunera -
    localhost oczywiście nie zadziała.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 9))
        return s.getsockname()[0]
    finally:
        s.close()
