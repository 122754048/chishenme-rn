from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import hashlib
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import socket
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image

from .errors import ReplicationError
from .intake import bind_uploaded_slots


_PUBLIC_TO_SLOT = {
    "source_video": "source_video",
    "new_product_images": "new_product_image",
    "new_model_images": "new_model_image",
    "ui_screenshots": "ui_screenshot",
    "app_store_url": "app_store_url",
    "ui_operation_video": "ui_operation_video",
    "tail_video": "tail_video",
}
_MEDIA_FIELDS = frozenset(set(_PUBLIC_TO_SLOT) - {"app_store_url"}) | {"audio"}
_IMAGE_FIELDS = frozenset({"new_product_images", "new_model_images", "ui_screenshots"})
_VIDEO_FIELDS = frozenset({"source_video", "ui_operation_video", "tail_video"})


def _error(code: str, message: str, *, retryable: bool = False, status: int = 422, **details: Any) -> ReplicationError:
    return ReplicationError(
        code,
        message,
        category="input",
        retryable=retryable,
        user_action_required=not retryable,
        http_status=status,
        details=details or None,
    )


@dataclass(frozen=True)
class ValidatedUrl:
    url: str
    host: str
    addresses: tuple[str, ...]


class OssUrlPolicy:
    def __init__(self, allowed_hosts: Sequence[str], *, resolver: Callable[[str], Sequence[str]] | None = None) -> None:
        normalized = tuple(str(item or "").strip().lower() for item in allowed_hosts if str(item or "").strip())
        if not normalized:
            raise ValueError("at least one allowed OSS host is required")
        self.allowed_hosts = normalized
        self.resolver = resolver or self._resolve

    @staticmethod
    def _resolve(host: str) -> tuple[str, ...]:
        try:
            rows = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise _error("SOURCE_UNAVAILABLE", "OSS address could not be resolved", retryable=True, status=503) from exc
        return tuple(sorted({str(row[4][0]) for row in rows}))

    def _host_allowed(self, host: str) -> bool:
        for pattern in self.allowed_hosts:
            if pattern.startswith("*."):
                suffix = pattern[2:]
                if host.endswith("." + suffix) and host != suffix:
                    return True
            elif fnmatch.fnmatchcase(host, pattern):
                return True
        return False

    def validate(self, url: str) -> ValidatedUrl:
        parsed = urlparse(str(url or ""))
        host = (parsed.hostname or "").rstrip(".").lower()
        if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password:
            raise _error("INVALID_REQUEST", "media URL must be an HTTPS OSS URL", status=400)
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None or not self._host_allowed(host):
            raise _error("INVALID_REQUEST", "media URL host is not allowed", status=400)
        addresses = tuple(self.resolver(host))
        if not addresses:
            raise _error("SOURCE_UNAVAILABLE", "OSS address has no DNS result", retryable=True, status=503)
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise _error("INVALID_REQUEST", "OSS DNS result is invalid", status=400) from exc
            if not ip.is_global:
                raise _error("INVALID_REQUEST", "OSS URL must resolve to a public address", status=400)
        return ValidatedUrl(str(url), host, addresses)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RemoteMediaImporter:
    def __init__(
        self,
        *,
        object_store: Any,
        policy: OssUrlPolicy,
        fetcher: Callable[[ValidatedUrl, Path, int], None] | None = None,
        max_bytes: int = 512 * 1024 * 1024,
        timeout_seconds: float = 60.0,
    ) -> None:
        if object_store is None:
            raise ValueError("object_store is required")
        self.object_store = object_store
        self.policy = policy
        self.fetcher = fetcher or self._download
        self.max_bytes = int(max_bytes)
        self.timeout_seconds = float(timeout_seconds)

    def _download(self, validated: ValidatedUrl, destination: Path, max_bytes: int) -> None:
        opener = build_opener(_NoRedirect())
        current = validated
        started = time.monotonic()
        for _ in range(4):
            if time.monotonic() - started > self.timeout_seconds:
                raise _error("SOURCE_UNAVAILABLE", "OSS download timed out", retryable=True, status=503)
            request = Request(current.url, headers={"User-Agent": "USFR/1.0", "Accept": "*/*"})
            try:
                response = opener.open(request, timeout=min(self.timeout_seconds, 30.0))
            except HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308}:
                    location = exc.headers.get("Location")
                    if not location:
                        raise _error("SOURCE_UNAVAILABLE", "OSS redirect has no destination", status=422) from exc
                    current = self.policy.validate(urljoin(current.url, location))
                    continue
                retryable = exc.code >= 500 or exc.code == 429
                raise _error("SOURCE_UNAVAILABLE", "OSS file could not be downloaded", retryable=retryable, status=503 if retryable else 422) from exc
            except (URLError, TimeoutError, OSError) as exc:
                raise _error("SOURCE_UNAVAILABLE", "OSS file could not be downloaded", retryable=True, status=503) from exc
            try:
                raw_length = response.headers.get("Content-Length")
                if raw_length is not None and int(raw_length) > max_bytes:
                    raise _error("UNSUPPORTED_MEDIA", "media file exceeds the configured size limit", status=413)
                size = 0
                with destination.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_bytes:
                            raise _error("UNSUPPORTED_MEDIA", "media file exceeds the configured size limit", status=413)
                        output.write(chunk)
                if size == 0:
                    raise _error("UNSUPPORTED_MEDIA", "media file is empty")
                return
            finally:
                response.close()
        raise _error("SOURCE_UNAVAILABLE", "OSS redirect limit exceeded", status=422)

    @staticmethod
    def _values(value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [str(item) for item in value]
        return [str(value)]

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _probe(path: Path, *, kind: str, source: bool) -> tuple[str, float | None]:
        if kind == "image":
            try:
                with Image.open(path) as image:
                    image.verify()
                    image_format = str(image.format or "").upper()
            except Exception as exc:
                raise _error("UNSUPPORTED_MEDIA", "uploaded image is not decodable") from exc
            mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "AVIF": "image/avif", "GIF": "image/gif"}.get(image_format)
            if mime is None:
                raise _error("UNSUPPORTED_MEDIA", "uploaded image format is not supported")
            return mime, None
        command = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=30.0, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise _error("UNSUPPORTED_MEDIA", "uploaded media could not be probed") from exc
        if completed.returncode != 0:
            raise _error("UNSUPPORTED_MEDIA", "uploaded media is not decodable")
        try:
            payload = json.loads(completed.stdout)
            streams = payload.get("streams") or []
            duration = float((payload.get("format") or {}).get("duration"))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise _error("UNSUPPORTED_MEDIA", "uploaded media metadata is invalid") from exc
        expected_stream = "video" if kind == "video" else "audio"
        if not any(item.get("codec_type") == expected_stream for item in streams if isinstance(item, Mapping)):
            raise _error("UNSUPPORTED_MEDIA", f"uploaded {kind} has no {expected_stream} stream")
        if source and duration > 30.0:
            raise _error("SOURCE_TOO_LONG", "source video must be at most 30 seconds", status=422, duration_seconds=duration)
        suffix = path.suffix.lower()
        if kind == "video":
            mime = "video/webm" if suffix == ".webm" else "video/quicktime" if suffix == ".mov" else "video/mp4"
        else:
            mime = {
                ".aac": "audio/aac", ".flac": "audio/flac", ".m4a": "audio/mp4",
                ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav",
            }.get(suffix, "audio/mpeg")
        return mime, duration

    def _import_one(self, *, job_id: str, field: str, index: int, url: str, work_dir: Path) -> dict[str, Any]:
        validated = self.policy.validate(url)
        suffix = Path(urlparse(validated.url).path).suffix.lower() or ".bin"
        destination = work_dir / f"{field}-{index}{suffix}"
        self.fetcher(validated, destination, self.max_bytes)
        kind = "image" if field in _IMAGE_FIELDS else "video" if field in _VIDEO_FIELDS else "audio"
        content_type, duration = self._probe(destination, kind=kind, source=field == "source_video")
        digest = self._sha256(destination)
        object_key = f"uploads/{job_id}/{field}/{index}-{digest}{suffix}"
        with destination.open("rb") as stream:
            stored = self.object_store.put_stream(
                object_key=object_key,
                stream=stream,
                content_type=content_type,
                expected_sha256=digest,
            )
        completion = {
            "object_key": object_key,
            "sha256": str(getattr(stored, "sha256", digest)),
            "size_bytes": int(getattr(stored, "size_bytes", destination.stat().st_size)),
            "content_type": content_type,
            "status": "completed",
        }
        if duration is not None:
            completion["duration_seconds"] = duration
        return completion

    def import_request(self, *, job_id: str, request: Mapping[str, Any], work_dir: str | Path) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise _error("INVALID_REQUEST", "public intake must be an object", status=400)
        work = Path(work_dir)
        work.mkdir(parents=True, exist_ok=True)
        slot_objects: dict[str, Any] = {}
        for public_field, slot_id in _PUBLIC_TO_SLOT.items():
            values = self._values(request.get(public_field))
            if public_field == "app_store_url":
                if values:
                    slot_objects[slot_id] = values[0]
                continue
            imported = [
                self._import_one(job_id=job_id, field=public_field, index=index, url=url, work_dir=work)
                for index, url in enumerate(values)
            ]
            if imported:
                slot_objects[slot_id] = imported if len(imported) > 1 else imported[0]
        audio_values = self._values(request.get("audio"))
        background_music = None
        if audio_values:
            background_music = self._import_one(
                job_id=job_id,
                field="audio",
                index=0,
                url=audio_values[0],
                work_dir=work,
            )
        output_language = str(request.get("output_language") or "").strip() or None
        has_change_media = any(key != "source_video" for key in slot_objects) or background_music is not None
        manifest = bind_uploaded_slots(
            slot_objects,
            background_music=background_music,
            object_store=self.object_store,
            upload_scope=job_id,
            allow_language_only=bool(output_language and not has_change_media),
            output_language=output_language,
        )
        manifest["output_language"] = output_language
        manifest["review_route"] = "route_2"
        manifest.setdefault("extensions", {})
        if request.get("ui_operation_video"):
            manifest["extensions"]["ui_operation_policy"] = {
                "audio_policy": "mute",
                "screenshot_assist": bool(request.get("ui_screenshots")),
            }
        return manifest


def policy_from_environment() -> OssUrlPolicy:
    hosts = tuple(item.strip() for item in os.getenv("USFR_ALLOWED_OSS_HOSTS", "").split(",") if item.strip())
    return OssUrlPolicy(hosts)


__all__ = ["OssUrlPolicy", "RemoteMediaImporter", "ValidatedUrl", "policy_from_environment"]
