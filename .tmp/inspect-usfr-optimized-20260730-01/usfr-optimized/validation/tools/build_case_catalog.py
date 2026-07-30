"""Publish private validation fixtures and freeze a path-free case catalog."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Callable, Mapping, Protocol, Sequence


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".m4v": "video/x-m4v",
}
_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".gif": "image/gif",
}


class CatalogBuildError(RuntimeError):
    pass


class FixturePublisher(Protocol):
    def publish(self, **request: Any) -> Mapping[str, Any]: ...


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve_fixture(asset_id: str, roots: Sequence[Path]) -> Path:
    candidate = Path(asset_id)
    if candidate.is_absolute() or ".." in candidate.parts or not asset_id.startswith("fixtures/"):
        raise CatalogBuildError(f"fixture must be a safe relative fixture path: {asset_id}")
    for root in roots:
        resolved_root = root.resolve()
        resolved = (resolved_root / candidate).resolve()
        if not str(resolved).startswith(
            str(resolved_root) + ("" if str(resolved_root).endswith(("/", "\\")) else "\\")
        ):
            continue
        if resolved.is_file():
            return resolved
    raise CatalogBuildError(f"fixture file not found: {asset_id}")


def _media_kind(path: Path) -> tuple[str, str]:
    suffix = path.suffix.casefold()
    if suffix in _VIDEO_MIME:
        return "video", _VIDEO_MIME[suffix]
    if suffix in _IMAGE_MIME:
        return "image", _IMAGE_MIME[suffix]
    raise CatalogBuildError(f"unsupported validation fixture type: {path.name}")


def _validate_receipt(
    receipt: Mapping[str, Any],
    *,
    object_key: str,
    digest: str,
    size_bytes: int,
    content_type: str,
    duration_seconds: float | None,
) -> dict[str, Any]:
    key = receipt.get("object_key")
    if (
        key != object_key
        or not isinstance(key, str)
        or not key.startswith("private-validation/")
        or ":" in key
        or ".." in key.split("/")
        or receipt.get("sha256") != digest
        or receipt.get("size_bytes") != size_bytes
        or receipt.get("content_type") != content_type
        or receipt.get("status") != "completed"
        or receipt.get("verified") is not True
        or not isinstance(receipt.get("receipt_sha256"), str)
        or _SHA256.fullmatch(receipt["receipt_sha256"]) is None
    ):
        raise CatalogBuildError("publisher receipt is invalid or not privately bound")
    if duration_seconds is not None:
        observed = receipt.get("duration_seconds")
        if not isinstance(observed, (int, float)) or abs(float(observed) - duration_seconds) > 0.001:
            raise CatalogBuildError("publisher receipt duration does not match probe")
    return dict(receipt)


def build_published_catalog(
    *,
    catalog: Mapping[str, Any],
    input_roots: Sequence[Path],
    publisher: FixturePublisher,
    probe_video: Callable[[Path], Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if catalog.get("schema_version") != "usfr-validation-catalog/v1":
        raise CatalogBuildError("validation catalog schema is invalid")
    roots = [Path(root).resolve() for root in input_roots]
    if not roots or any(not root.is_dir() for root in roots):
        raise CatalogBuildError("at least one validation input root is required")
    output = deepcopy(dict(catalog))
    cases = output.get("cases")
    if not isinstance(cases, list):
        raise CatalogBuildError("validation catalog cases are invalid")
    published_by_sha: dict[str, dict[str, Any]] = {}
    fixture_assets: dict[str, dict[str, Any]] = {}

    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
            raise CatalogBuildError("validation case is invalid")
        records = [case.get("source_fixture"), *(case.get("replacement_fixtures") or [])]
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("asset_id"), str):
                raise CatalogBuildError(f"{case['case_id']}: fixture record is invalid")
            asset_id = record["asset_id"]
            if asset_id.startswith(("https://", "parameter/")):
                record["sha256"] = _sha_bytes(asset_id.encode("utf-8"))
                continue
            path = _resolve_fixture(asset_id, roots)
            data = path.read_bytes()
            digest = _sha_bytes(data)
            kind, content_type = _media_kind(path)
            probe: dict[str, Any] = {}
            duration_seconds: float | None = None
            if kind == "video":
                observed = probe_video(path)
                if not isinstance(observed, Mapping):
                    raise CatalogBuildError(f"{asset_id}: video probe returned invalid evidence")
                probe = dict(observed)
                raw_duration = probe.get("duration_seconds")
                if isinstance(raw_duration, bool) or not isinstance(raw_duration, (int, float)):
                    raise CatalogBuildError(f"{asset_id}: video duration is missing")
                duration_seconds = float(raw_duration)
                if duration_seconds < 0 or duration_seconds > 30.0:
                    raise CatalogBuildError(f"{asset_id}: video exceeds the 30 seconds limit")
            published = published_by_sha.get(digest)
            if published is None:
                object_key = f"private-validation/{digest}/{path.name}"
                request = {
                    "source_path": path,
                    "object_key": object_key,
                    "sha256": digest,
                    "size_bytes": len(data),
                    "content_type": content_type,
                }
                if duration_seconds is not None:
                    request["duration_seconds"] = duration_seconds
                receipt = publisher.publish(**request)
                if not isinstance(receipt, Mapping):
                    raise CatalogBuildError("publisher receipt must be an object")
                published = _validate_receipt(
                    receipt,
                    object_key=object_key,
                    digest=digest,
                    size_bytes=len(data),
                    content_type=content_type,
                    duration_seconds=duration_seconds,
                )
                published.update(
                    {
                        key: value
                        for key, value in probe.items()
                        if key in {"width", "height", "fps"}
                    }
                )
                published_by_sha[digest] = published
                fixture_assets[object_key] = deepcopy(published)
            record["asset_id"] = published["object_key"]
            record["sha256"] = digest
        case["fixture_fingerprint"] = hashlib.sha256(
            _canonical(
                {
                    "source_fixture": case.get("source_fixture"),
                    "replacement_fixtures": case.get("replacement_fixtures"),
                    "toolchain_sha256": case.get("toolchain_sha256"),
                }
            )
        ).hexdigest()

    fixture_manifest = {
        "schema_version": "usfr-validation-fixtures/v1",
        "assets": fixture_assets,
    }
    return output, fixture_manifest


def load_publisher(spec: str) -> FixturePublisher:
    raw = str(spec or "")
    module_name, separator, function_name = raw.partition(":")
    if (
        not separator
        or not module_name
        or not function_name
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", module_name) is None
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", function_name) is None
        or ".codex" in module_name.casefold()
    ):
        raise CatalogBuildError("publisher factory must be a packaged module:function")
    try:
        factory = getattr(importlib.import_module(module_name), function_name)
        publisher = factory()
    except Exception as exc:
        raise CatalogBuildError("publisher factory could not be loaded") from exc
    if not callable(getattr(publisher, "publish", None)):
        raise CatalogBuildError("publisher factory must return an object with publish()")
    return publisher


def probe_video_ffprobe(path: Path) -> dict[str, Any]:
    command = [
        os.getenv("USFR_FFPROBE_BIN", "ffprobe"),
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=30
        )
        payload = json.loads(completed.stdout)
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as exc:
        raise CatalogBuildError(f"video probe failed: {path.name}") from exc
    format_payload = payload.get("format") if isinstance(payload, Mapping) else None
    streams = payload.get("streams") if isinstance(payload, Mapping) else None
    if not isinstance(format_payload, Mapping) or not isinstance(streams, list):
        raise CatalogBuildError(f"video probe returned invalid evidence: {path.name}")
    video = next(
        (
            stream
            for stream in streams
            if isinstance(stream, Mapping) and stream.get("codec_type") == "video"
        ),
        None,
    )
    if not isinstance(video, Mapping):
        raise CatalogBuildError(f"video stream is missing: {path.name}")
    try:
        duration = float(format_payload["duration"])
        rate = str(video.get("r_frame_rate") or "0/1")
        numerator, denominator = rate.split("/", 1)
        fps = float(numerator) / float(denominator)
        width = int(video["width"])
        height = int(video["height"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise CatalogBuildError(f"video probe fields are invalid: {path.name}") from exc
    return {
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "fps": fps,
    }


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish private validation media and freeze a path-free catalog."
    )
    parser.add_argument("--catalog-template", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, action="append", required=True)
    parser.add_argument("--publisher-factory", required=True)
    parser.add_argument("--output-catalog", type=Path, required=True)
    parser.add_argument("--output-fixtures", type=Path, required=True)
    args = parser.parse_args()
    catalog = json.loads(args.catalog_template.read_text(encoding="utf-8"))
    published, fixtures = build_published_catalog(
        catalog=catalog,
        input_roots=args.input_root,
        publisher=load_publisher(args.publisher_factory),
        probe_video=probe_video_ffprobe,
    )
    _write_json_atomic(args.output_catalog, published)
    _write_json_atomic(args.output_fixtures, fixtures)
    print(args.output_catalog)
    print(args.output_fixtures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
