"""Bind local UI Sidecar temporary artifacts to a published USFR final video."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Iterable
from urllib.request import Request, urlopen


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _retention_endpoint(render_endpoint: str) -> str:
    endpoint = str(render_endpoint or "").strip().rstrip("/")
    if not endpoint.endswith("/v1/render"):
        raise ValueError("UI Sidecar render endpoint must end with /v1/render")
    return f"{endpoint[:-len('/v1/render')]}/v1/retention/finalized"


def finalize_ui_sidecar_requests(
    *,
    render_endpoint: str,
    api_token: str,
    request_sha256s: Iterable[str],
    final_video_sha256: str,
    opener: Callable[..., Any] = urlopen,
    timeout_seconds: float = 15.0,
) -> None:
    """Start the fixed 24-hour Sidecar retention clock after final promotion."""

    if _SHA256.fullmatch(str(final_video_sha256 or "")) is None:
        raise ValueError("final video SHA-256 is invalid")
    token = str(api_token or "").strip()
    if not token:
        raise ValueError("UI Sidecar retention requires an API token")
    endpoint = _retention_endpoint(render_endpoint)
    unique_requests = tuple(sorted({str(item or "") for item in request_sha256s}))
    if any(_SHA256.fullmatch(item) is None for item in unique_requests):
        raise ValueError("UI Sidecar retention request SHA-256 is invalid")
    for request_sha256 in unique_requests:
        payload = json.dumps(
            {"request_sha256": request_sha256, "final_video_sha256": final_video_sha256},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            endpoint,
            data=payload,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {token}",
            },
        )
        with opener(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if int(status) != 202:
                raise RuntimeError("UI Sidecar did not accept its retention schedule")
            try:
                body = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("UI Sidecar retention response is invalid") from exc
            if not isinstance(body, dict) or not isinstance(body.get("purge_after_ms"), int):
                raise RuntimeError("UI Sidecar retention receipt is incomplete")


__all__ = ["finalize_ui_sidecar_requests"]
