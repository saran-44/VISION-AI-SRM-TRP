"""Server-side frame source for the gate camera.

The browser can only capture the webcam attached to the machine it runs on: a
high-end gate camera is an RTSP stream or an HTTP snapshot endpoint, and
`backend/services.py` already reports `rtsp` as `gateway_required` because a
browser cannot open it. This module gives the portal a frame it can grab
*itself*, so the gate PC works without a browser camera and without a gateway
process in the middle.

Three source shapes, all configured by one environment variable:

    CAMERA_SOURCE=http://user:pass@192.168.1.64/ISAPI/Streaming/channels/101/picture
    CAMERA_SOURCE=rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101
    CAMERA_SOURCE=usb:0

Nothing here logs or returns credentials: every error and header goes through
`mask_source()`, and a URL password never reaches the audit log.
"""
from __future__ import annotations

import base64
import ipaddress
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# A JPEG snapshot from a 4K camera is ~1-3 MB. Anything far beyond that is not
# a frame the detector asked for, so it is refused before it becomes a bitmap.
MAX_FRAME_BYTES = 8_000_000
MIN_FRAME_SIDE = 64


class FrameSourceError(RuntimeError):
    """The camera could not be reached, or did not return a usable frame."""


@dataclass(frozen=True)
class Frame:
    data: bytes
    content_type: str
    label: str
    width: int | None = None
    height: int | None = None


def mask_source(source: str) -> str:
    """`rtsp://admin:hunter2@10.0.0.5/s` -> `rtsp://admin:***@10.0.0.5/s`."""
    try:
        parts = urllib.parse.urlsplit(source)
    except ValueError:
        return "<camera>"
    if not parts.netloc or "@" not in parts.netloc:
        return source
    userinfo, _, host = parts.netloc.rpartition("@")
    user = userinfo.split(":", 1)[0]
    return urllib.parse.urlunsplit(
        (parts.scheme, f"{user}:***@{host}", parts.path, parts.query, parts.fragment)
    )


def source_kind(source: str) -> str:
    """One of `http`, `rtsp`, `usb` — or an empty string when unrecognised."""
    text = (source or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith(("http://", "https://")):
        return "http"
    if lowered.startswith("rtsp://"):
        return "rtsp"
    if lowered.startswith("usb:"):
        return "usb"
    if text.isdigit():
        return "usb"
    return ""


def camera_timeout(explicit: float | None = None) -> float:
    if explicit is not None:
        return max(0.5, float(explicit))
    try:
        return max(0.5, float(os.getenv("CAMERA_TIMEOUT", "5")))
    except ValueError:
        return 5.0


def snapshot(source: str | None = None, timeout: float | None = None) -> Frame:
    """Grab one frame from `source`, or from `CAMERA_SOURCE` when omitted."""
    chosen = (source if source is not None else os.getenv("CAMERA_SOURCE", "")).strip()
    kind = source_kind(chosen)
    if not kind:
        raise FrameSourceError(
            "No camera is configured. Set CAMERA_SOURCE to an HTTP snapshot URL, an RTSP "
            "URL, or usb:0 in the gate configuration file."
        )
    wait = camera_timeout(timeout)
    if kind == "http":
        frame = _http_snapshot(chosen, wait)
    else:
        frame = _opencv_snapshot(chosen.lstrip("usb:"), wait)
    _verify(frame)
    return frame


# --------------------------------------------------------------------- HTTP
def _http_snapshot(source: str, timeout: float) -> Frame:
    """A JPEG snapshot endpoint — Hikvision ISAPI, Axis, Dahua, most ONVIF boxes."""
    parts = urllib.parse.urlsplit(source)
    headers = {"Accept": "image/jpeg", "User-Agent": "VisionAI-Gate/1.0"}
    url = source
    if parts.username is not None:
        # Do not put the password back into the URL: urllib keeps it out of the
        # request line, and only this header carries it.
        credentials = f"{urllib.parse.unquote(parts.username)}:{urllib.parse.unquote(parts.password or '')}"
        headers["Authorization"] = "Basic " + base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        host = parts.hostname or ""
        netloc = f"[{host}]" if ":" in host else host
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        url = urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if content_type and not content_type.startswith("image/"):
                raise FrameSourceError(
                    f"{mask_source(source)} answered {content_type}, not an image. A camera "
                    "that returns HTML is usually asking for a login, or the snapshot path is wrong."
                )
            data = response.read(MAX_FRAME_BYTES + 1)
    except urllib.error.HTTPError as exc:
        hint = {
            401: "the camera rejected the username/password",
            403: "the camera's account may not be allowed to read snapshots",
            404: "the snapshot path is wrong",
        }.get(exc.code, "the camera returned an error")
        raise FrameSourceError(f"{mask_source(source)} answered HTTP {exc.code}: {hint}") from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise FrameSourceError(
            f"Could not reach {mask_source(source)} ({reason}). Check the cable, the camera's "
            "IP address, and that the gate PC is on the same LAN."
        ) from exc
    if len(data) > MAX_FRAME_BYTES:
        raise FrameSourceError(
            f"The camera returned more than {MAX_FRAME_BYTES // 1_000_000} MB. Point "
            "CAMERA_SOURCE at a still-image endpoint, not at a video stream."
        )
    return Frame(data=data, content_type="image/jpeg", label=mask_source(source))


# ------------------------------------------------------------------- OpenCV
def _opencv_snapshot(target: str, timeout: float) -> Frame:
    """RTSP stream or USB device, read through OpenCV.

    Several frames are read because the first ones are still converging after a
    stream opens (the same warm-up problem the webcam capture had), and the
    sharpest frame of the sample is the one worth running the detector on.
    """
    try:
        import cv2  # type: ignore
    except ImportError as exc:
        raise FrameSourceError(
            "OpenCV is needed for RTSP and USB cameras: "
            "python -m pip install -r backend/requirements-vision.txt"
        ) from exc

    capture_target: object = target
    if target.isdigit():
        capture_target = int(target)
    address = target if isinstance(capture_target, str) else f"usb:{target}"
    label = mask_source(address) if isinstance(capture_target, str) else f"usb:{target}"

    capture = cv2.VideoCapture(capture_target)
    if not capture.isOpened():
        if isinstance(capture_target, str) and _reachable(target, timeout):
            raise FrameSourceError(
                f"{label} answers on the network but OpenCV could not open the stream. "
                "Check the RTSP path and that the stream is H.264 (some cameras offer H.265 only)."
            )
        raise FrameSourceError(
            f"Could not open {label}. For RTSP check the URL, the password and the network; "
            "for USB check that no other program (Teams, Camera) is holding the device."
        )

    best, best_score = None, -1.0
    try:
        for _ in range(max(4, int(os.getenv("CAMERA_FRAMES", "8")))):
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            score = float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
            if score > best_score:
                best, best_score = frame, score
    finally:
        capture.release()

    if best is None:
        raise FrameSourceError(
            f"{label} opened but returned no frame. The stream may need a different path, "
            "or the camera is still starting up."
        )
    ok, encoded = cv2.imencode(".jpg", best, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise FrameSourceError(f"Could not encode the frame from {label} as JPEG")
    return Frame(
        data=encoded.tobytes(),
        content_type="image/jpeg",
        label=label,
        width=int(best.shape[1]),
        height=int(best.shape[0]),
    )


def _reachable(target: str, timeout: float) -> bool:
    """Was it a TCP reachability problem rather than a bad stream path?"""
    parts = urllib.parse.urlsplit(target)
    if not parts.hostname:
        return False
    port = parts.port or 554
    try:
        with socket.create_connection((parts.hostname, port), timeout=timeout):
            return True
    except OSError:
        return False


# ------------------------------------------------------------------ verify
def _verify(frame: Frame) -> None:
    """Reject anything the detector could not use, before it reaches the model."""
    try:
        from PIL import Image  # type: ignore

        with Image.open(__import__("io").BytesIO(frame.data)) as probe:
            width, height = probe.size
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same answer
        raise FrameSourceError(
            f"{frame.label} did not return a readable image ({type(exc).__name__}). "
            "Check that CAMERA_SOURCE points at a still image, not at a video stream."
        ) from exc
    if min(width, height) < MIN_FRAME_SIDE:
        raise FrameSourceError(
            f"{frame.label} returned a {width}×{height} image. Use the camera's full-resolution "
            "snapshot, not a thumbnail: the detector needs the sticker to survive the letterbox."
        )
    object.__setattr__(frame, "width", width)
    object.__setattr__(frame, "height", height)


def describe(source: str | None = None) -> dict[str, object]:
    """What the API and the preflight report about the configured camera."""
    chosen = (source if source is not None else os.getenv("CAMERA_SOURCE", "")).strip()
    kind = source_kind(chosen)
    return {
        "configured": bool(chosen),
        "kind": kind or None,
        "source": mask_source(chosen) if chosen else None,
        "timeout_seconds": camera_timeout(),
    }


def is_loopback_host(host: str) -> bool:
    """Used by the preflight: a public camera URL on a private LAN is fine."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() in {"localhost", "127.0.0.1", "::1"}
