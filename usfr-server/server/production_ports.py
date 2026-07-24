"""Strict, side-effect-free production boundaries for GPT and RunningHub.

This module deliberately does not assemble the stage map.  It establishes the
deployment configuration, structured GPT transport, and the one RunningHub
provider instance that later factory wiring will bind to the existing ports.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
from http import client as httpclient
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from .performance_audio_contracts import build_source_audio_contracts
from .review_models import RevisionManifest


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RUNNINGHUB_IMAGE_CREATE_PATH = "/openapi/v2/rhart-image-g-2-official/image-to-image"
_RUNNINGHUB_RUNNING_STATUSES = {"QUEUED", "RUNNING"}
_RUNNINGHUB_FAILURE_STATUSES = {"FAILED", "CANCELLED", "CANCELED"}
_RUNNINGHUB_STATUSES = _RUNNINGHUB_RUNNING_STATUSES | _RUNNINGHUB_FAILURE_STATUSES | {"SUCCESS"}
_REVISION_SCHEMA_VERSION = "usfr-creative-revision/v1"
_REPLACEMENT_SLOT_IDS = (
    "new_product_image",
    "new_model_image",
    "ui_screenshot",
    "app_store_url",
    "ui_operation_video",
    "tail_video",
)
_OUTPUT_LANGUAGES = {"en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh"}
_OUTPUT_LANGUAGE_NAMES = {
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "id": "Indonesian",
    "zh": "Chinese",
}
_TARGET_EVIDENCE_ARTIFACT_KINDS = {
    "app_store_evidence",
    "app_store_screenshot",
    "generated_ui_video",
    "overlay_evidence",
    "overlay_mapping",
    "target_evidence",
    "ui_evidence",
    "ui_truth_card",
}
_UNSAFE_DRAFT_FIELDS = {
    "api_key",
    "file_path",
    "hidden_reasoning",
    "local_path",
    "path",
    "prompt_chain",
    "reasoning",
    "secret",
    "work_dir",
}


class ProductionPortsError(RuntimeError):
    """Production port configuration or provider contract is invalid."""


class RunningHubTaskFailed(ProductionPortsError):
    """A RunningHub task reached a known terminal failure state."""


class RunningHubCreateAmbiguousError(ProductionPortsError):
    """A paid create may have been accepted and requires reconciliation."""

    code = "VIDEO_CREATE_AMBIGUOUS"
    retryable = False
    reconciliation_required = True


@dataclass(frozen=True)
class _PinnedHttpsEndpoint:
    url: str
    hostname: str
    port: int
    target: str
    addresses: tuple[str, ...]


class _RejectRedirect(urlrequest.HTTPRedirectHandler):
    """Prevent a deployment URL from forwarding credentials to a redirect."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        raise ProductionPortsError("production HTTPS transport must not follow redirects")


class _PinnedHttpsConnection(httpclient.HTTPSConnection):
    """Connect to a prevalidated address while preserving TLS host validation."""

    def __init__(
        self,
        *,
        hostname: str,
        port: int,
        resolved_address: str,
        timeout_seconds: float,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        super().__init__(
            host=hostname,
            port=port,
            timeout=timeout_seconds,
            context=ssl_context or ssl.create_default_context(),
        )
        self._resolved_address = resolved_address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._resolved_address, self.port),
            self.timeout,
            self.source_address,
        )
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class _PinnedHttpsResponse:
    def __init__(self, response: Any, connection: Any) -> None:
        self._response = response
        self._connection = connection

    def __enter__(self) -> Any:
        return self._response

    def __exit__(self, _exc_type: Any, _exc_value: Any, _traceback: Any) -> None:
        try:
            self._response.close()
        finally:
            self._connection.close()


class _PinnedHttpsOpener:
    """No-redirect HTTPS opener that never re-resolves a validated hostname."""

    def __init__(self, *, connection_factory: Callable[..., Any] = _PinnedHttpsConnection) -> None:
        self._connection_factory = connection_factory

    def open(self, request: urlrequest.Request, *, endpoint: _PinnedHttpsEndpoint, timeout: float) -> _PinnedHttpsResponse:
        last_error: Exception | None = None
        for address in endpoint.addresses:
            connection = self._connection_factory(
                hostname=endpoint.hostname,
                port=endpoint.port,
                resolved_address=address,
                timeout_seconds=timeout,
            )
            try:
                connection.request(
                    request.get_method(),
                    endpoint.target,
                    body=request.data,
                    headers=dict(request.header_items()),
                )
                response = connection.getresponse()
            except (OSError, httpclient.HTTPException) as exc:
                connection.close()
                last_error = exc
                continue
            status = int(getattr(response, "status", 0))
            if 300 <= status < 400:
                response.close()
                connection.close()
                raise ProductionPortsError("production HTTPS transport must not follow redirects")
            if not 200 <= status < 300:
                response.close()
                connection.close()
                raise ProductionPortsError("production HTTPS request failed")
            return _PinnedHttpsResponse(response, connection)
        raise ProductionPortsError("production HTTPS request failed") from last_error


_NO_REDIRECT_OPENER = _PinnedHttpsOpener()


def _require_secret(environ: Mapping[str, str], name: str) -> None:
    if not str(environ.get(name) or "").strip():
        raise ProductionPortsError(f"{name} is required")


def _require_text(environ: Mapping[str, str], name: str) -> str:
    value = str(environ.get(name) or "").strip()
    if not value:
        raise ProductionPortsError(f"{name} is required")
    if any(character.isspace() for character in value):
        raise ProductionPortsError(f"{name} must not contain whitespace")
    return value


def _require_sha256(environ: Mapping[str, str], name: str) -> str:
    value = _require_text(environ, name)
    if _SHA256.fullmatch(value) is None:
        raise ProductionPortsError(f"{name} must be a lowercase SHA-256")
    return value


def _resolve_hostname(hostname: str) -> tuple[str, ...]:
    try:
        records = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ProductionPortsError(f"production hostname could not be resolved: {hostname}") from exc
    addresses = tuple(sorted({str(record[4][0]) for record in records if record[4]}))
    if not addresses:
        raise ProductionPortsError(f"production hostname did not resolve to an address: {hostname}")
    return addresses


def _require_public_hostname(hostname: str, name: str) -> tuple[str, ...]:
    normalized = hostname.rstrip(".").casefold()
    if not normalized or normalized == "localhost":
        raise ProductionPortsError(f"{name} must not target a local or private host")
    try:
        values = (str(ipaddress.ip_address(normalized)),)
    except ValueError:
        values = _resolve_hostname(normalized)
    for value in values:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ProductionPortsError(f"{name} hostname resolution returned an invalid address") from exc
        if not address.is_global:
            raise ProductionPortsError(f"{name} must not target a local, private, or link-local address")
    return values


def _pinned_https_endpoint(value: str, name: str, *, allow_query: bool) -> _PinnedHttpsEndpoint:
    try:
        parsed = urlparse.urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise ProductionPortsError(f"{name} must be a credential-free HTTPS URL") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and not 1 <= port <= 65535)
        or (not allow_query and (parsed.query or parsed.fragment))
    ):
        raise ProductionPortsError(f"{name} must be a credential-free HTTPS URL")
    addresses = _require_public_hostname(parsed.hostname, name)
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    return _PinnedHttpsEndpoint(
        url=value.rstrip("/"),
        hostname=parsed.hostname,
        port=port or 443,
        target=target,
        addresses=addresses,
    )


def _validated_https_url(value: str, name: str, *, allow_query: bool) -> str:
    return _pinned_https_endpoint(value, name, allow_query=allow_query).url


def _require_https_url(environ: Mapping[str, str], name: str) -> str:
    return _validated_https_url(_require_text(environ, name), name, allow_query=False)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductionPortsError("production request must be JSON-serializable") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _read_environment_secret(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise ProductionPortsError(f"{name} is required before a production request")
    return value


def _post_json(
    *,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    endpoint = _pinned_https_endpoint(url, "production request URL", allow_query=False)
    request = urlrequest.Request(
        endpoint.url,
        data=_canonical_json(payload),
        headers=dict(headers),
        method="POST",
    )
    try:
        with _NO_REDIRECT_OPENER.open(request, endpoint=endpoint, timeout=timeout_seconds) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
    except (urlerror.HTTPError, urlerror.URLError, TimeoutError, OSError) as exc:
        raise ProductionPortsError("production HTTPS request failed") from exc
    if len(raw) > 8 * 1024 * 1024:
        raise ProductionPortsError("production HTTPS response exceeded the byte limit")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionPortsError("production HTTPS response was not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise ProductionPortsError("production HTTPS response must be a JSON object")
    return dict(value)


def _download_bytes(*, url: str, timeout_seconds: float) -> bytes:
    endpoint = _pinned_https_endpoint(url, "RunningHub result URL", allow_query=True)
    request = urlrequest.Request(endpoint.url, method="GET")
    try:
        with _NO_REDIRECT_OPENER.open(request, endpoint=endpoint, timeout=timeout_seconds) as response:
            data = response.read(512 * 1024 * 1024 + 1)
    except (urlerror.HTTPError, urlerror.URLError, TimeoutError, OSError) as exc:
        raise ProductionPortsError("RunningHub result download failed") from exc
    if len(data) > 512 * 1024 * 1024:
        raise ProductionPortsError("RunningHub result exceeded the byte limit")
    return data


@dataclass(frozen=True)
class ProductionEnvironment:
    """Validated deployment configuration with no credential values.

    API credentials are validated during construction but retained only in the
    deployment environment.  The immutable configuration keeps their variable
    names so its representation, identity, and receipts cannot expose secrets.
    """

    openai_api_key_env: str
    openai_base_url: str
    openai_model: str
    openai_model_config_sha256: str
    runninghub_api_key_env: str
    runninghub_base_url: str
    runninghub_seedance_create_url: str
    runninghub_seedance_query_url: str
    runninghub_seedance_workflow_id: str
    runninghub_seedance_model_id: str
    runninghub_seedance_config_sha256: str

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "ProductionEnvironment":
        source: Mapping[str, str] = os.environ if environ is None else environ
        _require_secret(source, "OPENAI_API_KEY")
        _require_secret(source, "RUNNINGHUB_API_KEY")
        return cls(
            openai_api_key_env="OPENAI_API_KEY",
            openai_base_url=_require_https_url(source, "OPENAI_BASE_URL"),
            openai_model=_require_text(source, "OPENAI_MODEL"),
            openai_model_config_sha256=_require_sha256(source, "OPENAI_MODEL_CONFIG_SHA256"),
            runninghub_api_key_env="RUNNINGHUB_API_KEY",
            runninghub_base_url=_require_https_url(source, "RUNNINGHUB_BASE_URL"),
            runninghub_seedance_create_url=_require_https_url(source, "RUNNINGHUB_SEEDANCE_CREATE_URL"),
            runninghub_seedance_query_url=_require_https_url(source, "RUNNINGHUB_SEEDANCE_QUERY_URL"),
            runninghub_seedance_workflow_id=_require_text(source, "RUNNINGHUB_SEEDANCE_WORKFLOW_ID"),
            runninghub_seedance_model_id=_require_text(source, "RUNNINGHUB_SEEDANCE_MODEL_ID"),
            runninghub_seedance_config_sha256=_require_sha256(source, "RUNNINGHUB_SEEDANCE_CONFIG_SHA256"),
        )


class EvidenceBoundGptPlanner:
    """Minimal strict-schema GPT Responses boundary for internal reasoning."""

    _REQUEST_TIMEOUT_SECONDS = 120.0

    def __init__(
        self,
        config: ProductionEnvironment,
        *,
        request_json: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self._request_json = request_json or _post_json

    def request_script(self, *, evidence: Mapping[str, Any], schema: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._request_structured(kind="script", evidence=evidence, schema=schema)

    def request_storyboard(self, *, evidence: Mapping[str, Any], schema: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._request_structured(kind="storyboard", evidence=evidence, schema=schema)

    def request_prompt(self, *, evidence: Mapping[str, Any], schema: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._request_structured(kind="prompt", evidence=evidence, schema=schema)

    @classmethod
    def from_environment(cls, production: bool = True) -> "EvidenceBoundGptPlanner":
        """Construct the deployment-owned planner without retaining secrets.

        ``ProductionEnvironment`` performs HTTPS, public-host, credential, and
        model-identity validation before this planner can make a request.  The
        flag is intentionally accepted by the factory-facing API but cannot
        weaken those deployment checks.
        """

        if not isinstance(production, bool):
            raise ProductionPortsError("production must be a boolean")
        return cls(ProductionEnvironment.from_environ())

    @staticmethod
    def _sha256_field(value: Any, field: str) -> str:
        candidate = str(value or "").strip().lower()
        if _SHA256.fullmatch(candidate) is None:
            raise ProductionPortsError(f"{field} must be a lowercase SHA-256")
        return candidate

    @staticmethod
    def _safe_text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ProductionPortsError(f"{field} is required")
        candidate = value.strip()
        folded = candidate.casefold()
        if (
            candidate.startswith(("/", "\\"))
            or (len(candidate) > 1 and candidate[1] == ":" and candidate[0].isalpha())
            or folded.startswith(("file:", "local:", "path:"))
            or "~/.codex" in folded
            or ".codex/skills" in folded
            or ".codex\\skills" in folded
        ):
            raise ProductionPortsError(f"{field} cannot contain a local path")
        return candidate

    @classmethod
    def _snapshot_slots(cls, context: Any) -> Mapping[str, Any]:
        snapshot = getattr(context, "snapshot", None)
        manifest = getattr(snapshot, "slots_manifest", None)
        if not isinstance(manifest, Mapping):
            raise ProductionPortsError("current job slot manifest is required")
        slots = manifest.get("slots")
        if not isinstance(slots, Mapping):
            raise ProductionPortsError("current job slot manifest has no slots")
        return slots

    @classmethod
    def _slot_sha256s(cls, slots: Mapping[str, Any], slot_id: str) -> tuple[str, ...]:
        slot = slots.get(slot_id)
        if not isinstance(slot, Mapping):
            raise ProductionPortsError(f"current job {slot_id} slot is required")
        raw = slot.get("sha256")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            raise ProductionPortsError(f"current job {slot_id} SHA evidence is required")
        values = tuple(cls._sha256_field(value, f"current job {slot_id} SHA") for value in raw)
        if not values or len(values) != len(set(values)):
            raise ProductionPortsError(f"current job {slot_id} SHA evidence is invalid")
        return values

    @classmethod
    def _safe_artifacts(cls, context: Any) -> tuple[dict[str, str], ...]:
        raw = getattr(context, "artifacts", ())
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            raise ProductionPortsError("current job artifact evidence is invalid")
        records: list[dict[str, str]] = []
        for index, artifact in enumerate(raw):
            if not isinstance(artifact, Mapping):
                raise ProductionPortsError(f"current job artifact {index} is invalid")
            kind = cls._safe_text(artifact.get("kind"), f"current job artifact {index} kind")
            sha256 = cls._sha256_field(artifact.get("sha256"), f"current job artifact {index} SHA")
            artifact_id = cls._safe_text(artifact.get("artifact_id"), f"current job artifact {index} id")
            records.append({"artifact_id": artifact_id, "kind": kind, "sha256": sha256})
        return tuple(records)

    @classmethod
    def _materialized_json(cls, context: Any, *, kind: str, sha256: str, artifact_id: str) -> Mapping[str, Any]:
        materialize = getattr(context, "materialize_artifact", None)
        if not callable(materialize):
            raise ProductionPortsError("current job dynamics evidence requires artifact materialization")
        try:
            with materialize(kind, sha256=sha256, artifact_id=artifact_id) as media:
                path = getattr(media, "path", None)
                if not isinstance(path, Path):
                    raise ProductionPortsError("materialized dynamics evidence is invalid")
                payload = path.read_bytes()
        except ProductionPortsError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise ProductionPortsError("current job dynamics evidence could not be materialized") from exc
        if len(payload) > 4 * 1024 * 1024:
            raise ProductionPortsError("current job dynamics evidence exceeds the byte limit")
        if hashlib.sha256(payload).hexdigest() != sha256:
            raise ProductionPortsError("materialized dynamics evidence SHA does not match the immutable artifact")
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProductionPortsError("current job dynamics evidence is not valid UTF-8 JSON") from exc
        if not isinstance(value, Mapping):
            raise ProductionPortsError("current job dynamics evidence must be a JSON object")
        return value

    @classmethod
    def _source_cut_evidence(
        cls,
        context: Any,
        artifacts: Sequence[Mapping[str, str]],
    ) -> tuple[str, tuple[dict[str, Any], ...]]:
        matches = [item for item in artifacts if item["kind"] == "source_dynamics_analysis"]
        if len(matches) != 1:
            raise ProductionPortsError("current job requires exactly one source dynamics artifact")
        artifact = matches[0]
        payload = cls._materialized_json(
            context,
            kind=artifact["kind"],
            sha256=artifact["sha256"],
            artifact_id=artifact["artifact_id"],
        )
        analysis = payload.get("source_dynamics_analysis", payload)
        if not isinstance(analysis, Mapping):
            raise ProductionPortsError("current job source dynamics analysis is invalid")
        return artifact["sha256"], cls._project_source_cuts(analysis)

    @classmethod
    def _project_source_cuts(cls, analysis: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
        """Return the only safe, revision-relevant projection of source dynamics."""

        cls._reject_unsafe_draft_data(analysis, field="source dynamics analysis")
        cuts = analysis.get("source_cuts", analysis.get("cuts"))
        if not isinstance(cuts, list) or not cuts:
            raise ProductionPortsError("current job source dynamics has no Cut evidence")
        normalized: list[dict[str, Any]] = []
        previous_end: int | None = None
        for index, cut in enumerate(cuts):
            if not isinstance(cut, Mapping):
                raise ProductionPortsError(f"current job source Cut {index} is invalid")
            raw_cut_id = cut.get("cut_id")
            if raw_cut_id is None:
                raw_number = cut.get("cut")
                if isinstance(raw_number, bool) or not isinstance(raw_number, int) or raw_number < 1:
                    raise ProductionPortsError(f"current job source Cut {index} id is invalid")
                cut_id = f"C{raw_number:02d}"
            else:
                cut_id = cls._safe_text(raw_cut_id, f"current job source Cut {index} id")
            if any(item["cut_id"] == cut_id for item in normalized):
                raise ProductionPortsError("current job source Cut evidence contains duplicate cut IDs")
            start_us = cut.get("start_us")
            end_us = cut.get("end_us")
            if (
                isinstance(start_us, bool)
                or not isinstance(start_us, int)
                or isinstance(end_us, bool)
                or not isinstance(end_us, int)
                or start_us < 0
                or end_us <= start_us
                or (index == 0 and start_us != 0)
                or (previous_end is not None and start_us != previous_end)
            ):
                raise ProductionPortsError("current job source Cut timing is invalid")
            record: dict[str, Any] = {
                "cut_id": cut_id,
                "start_us": start_us,
                "end_us": end_us,
                "start_ms": start_us // 1000,
                "end_ms": (end_us + 999) // 1000,
            }
            for field in ("scene", "action", "camera"):
                record[field] = cls._safe_text(cut.get(field), f"current job source Cut {index} {field}")
            normalized.append(record)
            previous_end = end_us
        return tuple(normalized)

    @staticmethod
    def _object_schema(properties: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": dict(properties),
            "required": list(properties),
        }

    @classmethod
    def _revision_schema(cls, kind: str) -> dict[str, Any]:
        string = {"type": "string"}
        evidence_ids = {"type": "array", "items": string}
        common = {
            "kind": {"type": "string", "enum": [kind]},
            "job_id": string,
            "source_sha256": string,
            "source_dynamics_sha256": string,
            "target_sha256": string,
            "output_language": string,
            "parent_revision_sha256": string,
            "cut_coverage_sha256": string,
            "request_evidence_sha256": string,
        }
        if kind == "script":
            proof = cls._object_schema({"evidence_id": string})
            performance = cls._object_schema(
                {
                    "source_time": cls._object_schema({"start_ms": {"type": "integer"}, "end_ms": {"type": "integer"}}),
                    "segment_time": cls._object_schema({"start_ms": {"type": "integer"}, "end_ms": {"type": "integer"}}),
                    "performance_mode": string,
                    "exact_sung_text": string,
                    "lyric_status": string,
                    "beat_anchors_ms": {"type": "array", "items": {"type": "integer"}},
                    "no_beat_reason": string,
                    "lip_sync": cls._object_schema({"face_visibility": string, "articulation": string, "end_state": string}),
                    "action": cls._object_schema({"start": string, "beat_action": string, "end": string}),
                    "expression": cls._object_schema({"start": string, "peak": string, "end": string}),
                    "emotion": string,
                    "end_pose": string,
                    "criticality": string,
                }
            )
            selling_point = cls._object_schema(
                {
                    "feature": string,
                    "mechanism": string,
                    "benefit": string,
                    "proof": proof,
                    "cta": string,
                }
            )
            common["cuts"] = {
                "type": "array",
                "items": cls._object_schema(
                    {
                        "cut_id": string,
                        "start_ms": {"type": "integer"},
                        "end_ms": {"type": "integer"},
                        "scene": string,
                        "action": string,
                        "camera": string,
                        "dialogue": string,
                        "delivery": string,
                        "audio_events": {"type": "array", "items": string},
                        "selling_point": selling_point,
                        "proof": proof,
                        "visual": string,
                        "evidence_ids": evidence_ids,
                        "route": string,
                        "output_language": string,
                        "performance": performance,
                    }
                ),
            }
        elif kind == "storyboard":
            common["cuts"] = {
                "type": "array",
                "items": cls._object_schema(
                    {
                        "cut_id": string,
                        "prompt": string,
                        "negative_prompt": string,
                        "reference_evidence_ids": evidence_ids,
                        "composition": string,
                        "camera": string,
                        "continuity": string,
                        "output_language": string,
                    }
                ),
            }
        else:
            raise ProductionPortsError(f"unsupported creative revision kind: {kind}")
        return cls._object_schema(common)

    @classmethod
    def _performance_audio_evidence(
        cls,
        context: Any,
        artifacts: Sequence[Mapping[str, str]],
    ) -> dict[str, Any] | None:
        """Read safe Stage-3 contracts without ever forwarding audio bytes."""

        by_kind = {
            kind: [item for item in artifacts if item["kind"] == kind]
            for kind in ("performance_audio_source_contract", "audio_lyrics_beat_contract")
        }
        if not by_kind["performance_audio_source_contract"] and not by_kind["audio_lyrics_beat_contract"]:
            return None
        if any(len(rows) != 1 for rows in by_kind.values()):
            raise ProductionPortsError("current job requires exactly one source-audio evidence contract of each kind")
        source_artifact = by_kind["performance_audio_source_contract"][0]
        lyrics_artifact = by_kind["audio_lyrics_beat_contract"][0]
        source = cls._materialized_json(context, kind=source_artifact["kind"], sha256=source_artifact["sha256"], artifact_id=source_artifact["artifact_id"])
        lyrics = cls._materialized_json(context, kind=lyrics_artifact["kind"], sha256=lyrics_artifact["sha256"], artifact_id=lyrics_artifact["artifact_id"])
        cls._reject_unsafe_draft_data(source, field="source-audio contract")
        cls._reject_unsafe_draft_data(lyrics, field="source-audio lyrics contract")
        if source.get("mode") != "source_audio_replicate_v1":
            raise ProductionPortsError("current job source-audio mode is unsupported")
        authorization = source.get("authorization")
        if authorization != {"status": "user_default_authorized", "scope": "current_run_only"}:
            raise ProductionPortsError("current job source-audio authorization is invalid")
        source_audio_sha = cls._sha256_field(source.get("source_audio_sha256"), "current job source audio SHA")
        if source.get("provider_reference_audio") != "forbidden":
            raise ProductionPortsError("current job source audio must be forbidden to Provider B")
        if cls._sha256_field(lyrics.get("source_audio_sha256"), "current job lyric source audio SHA") != source_audio_sha:
            raise ProductionPortsError("current job lyrics are not bound to the source audio")
        segments = lyrics.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ProductionPortsError("current job source-audio lyrics require segments")
        safe_segments: list[dict[str, Any]] = []
        for index, item in enumerate(segments):
            if not isinstance(item, Mapping):
                raise ProductionPortsError("current job source-audio lyric segment is invalid")
            safe_segments.append(
                {
                    "segment_id": cls._safe_text(item.get("segment_id"), f"source-audio segment {index} id"),
                    "start_ms": int(item.get("start_ms")),
                    "end_ms": int(item.get("end_ms")),
                    "text": cls._safe_text(item.get("text"), f"source-audio segment {index} text"),
                    "confidence": item.get("confidence"),
                    "kind": cls._safe_text(item.get("kind"), f"source-audio segment {index} kind"),
                    "beat_anchors_ms": list(item.get("beat_anchors_ms") or []),
                    "emotion": cls._safe_text(item.get("emotion"), f"source-audio segment {index} emotion"),
                }
            )
        return {
            "source_audio_sha256": source_audio_sha,
            "audio_language": cls._safe_text(source.get("audio_language"), "current job source-audio language"),
            "segments": safe_segments,
            "source_contract_sha256": source_artifact["sha256"],
            "lyrics_contract_sha256": lyrics_artifact["sha256"],
        }

    @classmethod
    def _storyboard_performance_evidence(
        cls,
        context: Any,
        artifacts: Sequence[Mapping[str, str]],
        *,
        source_audio_enabled: bool,
    ) -> dict[str, Any] | None:
        rows = [item for item in artifacts if item["kind"] == "performance_line_contract"]
        if not rows:
            if source_audio_enabled:
                raise ProductionPortsError(
                    "source-audio storyboard requires the approved performance line contract"
                )
            return None
        if len(rows) != 1:
            raise ProductionPortsError("storyboard requires exactly one approved performance line contract")
        artifact = rows[0]
        value = cls._materialized_json(
            context,
            kind=artifact["kind"],
            sha256=artifact["sha256"],
            artifact_id=artifact["artifact_id"],
        )
        cls._reject_unsafe_draft_data(value, field="approved performance line contract")
        if value.get("contract") != "performance-line/v1" or not isinstance(value.get("cuts"), list):
            raise ProductionPortsError("approved performance line contract is invalid")
        cuts = [dict(item) for item in value["cuts"] if isinstance(item, Mapping)]
        if len(cuts) != len(value["cuts"]):
            raise ProductionPortsError("approved performance line contract Cut is invalid")
        return {
            "performance_line_contract_sha256": artifact["sha256"],
            "cuts": cuts,
            "instruction": (
                "Render each Cut's exact authorized lyric or instrumental/inaudible state, "
                "beat action, expression change, and end pose as read-only storyboard evidence."
            ),
        }

    @classmethod
    def _revision_evidence(
        cls,
        context: Any,
        *,
        kind: str,
    ) -> dict[str, Any]:
        if kind not in {"script", "storyboard"}:
            raise ProductionPortsError(f"unsupported creative revision kind: {kind}")
        job_id = cls._safe_text(getattr(context, "job_id", None), "current job id")
        snapshot = getattr(context, "snapshot", None)
        manifest = getattr(snapshot, "slots_manifest", None)
        if not isinstance(manifest, Mapping):
            raise ProductionPortsError("current job slot manifest is required")
        language = manifest.get("output_language")
        if not isinstance(language, str) or language not in _OUTPUT_LANGUAGES:
            raise ProductionPortsError("current job output_language is required and unsupported")
        admission = manifest.get("admission")
        language_only = bool(admission.get("language_only")) if isinstance(admission, Mapping) else False
        slots = cls._snapshot_slots(context)
        source_sha256s = cls._slot_sha256s(slots, "source_video")
        if len(source_sha256s) != 1:
            raise ProductionPortsError("current job source SHA evidence must identify one source video")
        replacements: list[dict[str, str]] = []
        for slot_id in _REPLACEMENT_SLOT_IDS:
            slot = slots.get(slot_id)
            if slot is None:
                continue
            if not isinstance(slot, Mapping):
                raise ProductionPortsError(f"current job {slot_id} slot is invalid")
            if slot.get("present") is False:
                continue
            replacements.extend(
                {"slot_id": slot_id, "sha256": sha256}
                for sha256 in cls._slot_sha256s(slots, slot_id)
            )
        artifacts = cls._safe_artifacts(context)
        source_dynamics_sha256, source_cuts = cls._source_cut_evidence(context, artifacts)
        performance_audio = cls._performance_audio_evidence(context, artifacts)
        storyboard_performance = (
            cls._storyboard_performance_evidence(
                context,
                artifacts,
                source_audio_enabled=performance_audio is not None,
            )
            if kind == "storyboard"
            else None
        )
        cut_ids = [item["cut_id"] for item in source_cuts]
        target_artifacts = [
            {"kind": item["kind"], "sha256": item["sha256"]}
            for item in artifacts
            if item["kind"] in _TARGET_EVIDENCE_ARTIFACT_KINDS
        ]
        if not replacements and not target_artifacts:
            raise ProductionPortsError("current job target evidence is required")
        target_sha256 = _sha256(
            {
                "replacement_slots": sorted(replacements, key=lambda item: (item["slot_id"], item["sha256"])),
                "target_artifacts": sorted(target_artifacts, key=lambda item: (item["kind"], item["sha256"])),
            }
        )
        target_evidence_ids = sorted(
            [f"slot:{item['slot_id']}:{item['sha256']}" for item in replacements]
            + [f"artifact:{item['kind']}:{item['sha256']}" for item in target_artifacts]
        )
        source_cut_evidence_sha256 = _sha256(
            {"source_dynamics_sha256": source_dynamics_sha256, "source_cuts": list(source_cuts)}
        )
        parent_revision_sha256 = ""
        if kind == "storyboard":
            parent_revision_sha256 = cls._sha256_field(
                getattr(snapshot, "approved_script_sha256", None),
                "current job approved script SHA",
            )
        base = {
            "schema_version": _REVISION_SCHEMA_VERSION,
            "kind": kind,
            "job_id": job_id,
            "source_sha256": source_sha256s[0],
            "source_dynamics_sha256": source_dynamics_sha256,
            "target_sha256": target_sha256,
            "target_evidence_ids": target_evidence_ids,
            "output_language": language,
            "language_only": language_only,
            "parent_revision_sha256": parent_revision_sha256,
            "source_cuts": list(source_cuts),
            "cut_ids": cut_ids,
            "cut_coverage_sha256": source_cut_evidence_sha256,
        }
        if performance_audio is not None:
            base["performance_audio"] = performance_audio
        if storyboard_performance is not None:
            base["approved_performance_lines"] = storyboard_performance
        return {**base, "request_evidence_sha256": _sha256(base)}

    @classmethod
    def _language_only_instruction(cls, *, kind: str, evidence: Mapping[str, Any]) -> str:
        if evidence.get("language_only") is not True:
            return ""
        language_code = str(evidence.get("output_language") or "").strip().lower()
        language_name = _OUTPUT_LANGUAGE_NAMES.get(language_code, language_code or "the selected language")
        if kind == "script":
            return (
                "Language-only localization task. Preserve the source video's shot order, cut timing, scene layout, camera grammar, "
                "action choreography, facial expression, delivery cadence, product/UI/tail behavior, and every non-language visual exactly. "
                f"Translate only the spoken dialogue and visible text into {language_name} ({language_code or 'selected'}). "
                "Keep the same meaning and tone, and maintain natural lip sync and mouth movement."
            )
        if kind == "storyboard":
            return (
                "Language-only localization task. Preserve the same storyboard structure, shot order, timing, composition, action, "
                "camera grammar, and all non-language visuals exactly. "
                f"Localize only any visible text and language-dependent labels into {language_name} ({language_code or 'selected'}); "
                "do not change the visual story or shot plan."
            )
        return (
            "Language-only localization task. Preserve the same cuts, timing, camera, action, product/UI/tail behavior, and non-language visuals exactly. "
            f"Translate only the spoken dialogue and visible text into {language_name} ({language_code or 'selected'}), keeping meaning, tone, and lip sync aligned."
        )

    @classmethod
    def _source_audio_performance_contract(
        cls,
        *,
        evidence: Mapping[str, Any],
        cuts: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any] | None:
        audio = evidence.get("performance_audio")
        if not isinstance(audio, Mapping):
            return None
        source_cuts = evidence.get("source_cuts")
        if not isinstance(source_cuts, list) or len(source_cuts) != len(cuts):
            raise ProductionPortsError("current job source-audio Cut evidence is incomplete")
        try:
            source_duration_ms = max(int(item["end_ms"]) for item in source_cuts)
            lines = [{"cut_id": cut["cut_id"], **dict(cut["performance"])} for cut in cuts]
            regions = [
                {
                    "region_id": str(source_cut["cut_id"]),
                    "region_type": "generated",
                    "segment_id": str(source_cut["cut_id"]),
                    "source_start_ms": int(source_cut["start_ms"]),
                    "source_end_ms": int(source_cut["end_ms"]),
                }
                for source_cut in source_cuts
            ]
            return build_source_audio_contracts(
                source_audio_sha256=str(audio["source_audio_sha256"]),
                source_duration_ms=source_duration_ms,
                audio_contract={"audio_language": audio["audio_language"], "segments": audio["segments"]},
                timeline_regions=regions,
                performance_lines=lines,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProductionPortsError("GPT performance contract is structurally invalid") from exc
        except Exception as exc:
            raise ProductionPortsError(f"GPT performance contract is invalid: {exc}") from exc

    @classmethod
    def _reject_unsafe_draft_data(cls, value: Any, *, field: str = "GPT draft") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_text = str(key).casefold()
                if key_text in _UNSAFE_DRAFT_FIELDS:
                    raise ProductionPortsError(f"{field} contains an unsafe field")
                cls._reject_unsafe_draft_data(child, field=f"{field}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                cls._reject_unsafe_draft_data(child, field=f"{field}[{index}]")
        elif isinstance(value, str):
            if value:
                cls._safe_text(value, field)

    def _validate_response(self, response: Mapping[str, Any], *, context: Any, kind: str) -> Mapping[str, Any]:
        if not isinstance(response, Mapping):
            raise ProductionPortsError("GPT creative response must be a JSON object")
        evidence = self._revision_evidence(context, kind=kind)
        wrapped = response.get("value")
        value = wrapped if isinstance(wrapped, Mapping) else response
        source_sha256 = str(value.get("source_sha256") or "").lower()
        if source_sha256 != evidence["source_sha256"]:
            raise ProductionPortsError("GPT creative response source SHA does not match the current job")
        if str(value.get("kind") or "") != kind:
            raise ProductionPortsError("GPT creative response kind does not match the current job")
        if str(value.get("job_id") or "") != evidence["job_id"]:
            raise ProductionPortsError("GPT creative response job id does not match the current job")
        if str(value.get("source_dynamics_sha256") or "").lower() != evidence["source_dynamics_sha256"]:
            raise ProductionPortsError("GPT creative response source dynamics SHA does not match the current job")
        if str(value.get("target_sha256") or "").lower() != evidence["target_sha256"]:
            raise ProductionPortsError("GPT creative response target SHA does not match the current job")
        if str(value.get("output_language") or "") != evidence["output_language"]:
            raise ProductionPortsError("GPT creative response output_language does not match the current job")
        if str(value.get("parent_revision_sha256") or "").lower() != evidence["parent_revision_sha256"]:
            raise ProductionPortsError("GPT creative response parent revision SHA does not match the current job")
        if str(value.get("cut_coverage_sha256") or "").lower() != evidence["cut_coverage_sha256"]:
            raise ProductionPortsError("GPT creative response Cut coverage SHA does not match the current job")
        if str(value.get("request_evidence_sha256") or "").lower() != evidence["request_evidence_sha256"]:
            raise ProductionPortsError("GPT creative response request SHA does not match the current job")
        cuts = value.get("cuts")
        if not isinstance(cuts, list):
            raise ProductionPortsError("GPT creative response Cuts must be an array")
        returned_cut_ids = [str(item.get("cut_id") or "") for item in cuts if isinstance(item, Mapping)]
        if len(returned_cut_ids) != len(cuts) or returned_cut_ids != evidence["cut_ids"]:
            raise ProductionPortsError("GPT creative response Cut coverage does not match the current job")
        known_target_evidence_ids = set(evidence["target_evidence_ids"])
        for index, cut in enumerate(cuts):
            if not isinstance(cut, Mapping):
                raise ProductionPortsError(f"GPT creative response Cut {index} is invalid")
            if kind == "script":
                source_cut = evidence["source_cuts"][index]
                if cut.get("start_ms") != source_cut["start_ms"] or cut.get("end_ms") != source_cut["end_ms"]:
                    raise ProductionPortsError("GPT creative response Cut timing does not match the current job")
                if cut.get("output_language") != evidence["output_language"]:
                    raise ProductionPortsError("GPT creative response Cut output_language does not match the current job")
                proof = cut.get("proof")
                selling_point = cut.get("selling_point")
                selling_proof = selling_point.get("proof") if isinstance(selling_point, Mapping) else None
                evidence_ids = cut.get("evidence_ids")
                bound_ids = (
                    list(evidence_ids) if isinstance(evidence_ids, list) else []
                ) + [
                    proof.get("evidence_id") if isinstance(proof, Mapping) else None,
                    selling_proof.get("evidence_id") if isinstance(selling_proof, Mapping) else None,
                ]
            else:
                if cut.get("output_language") != evidence["output_language"]:
                    raise ProductionPortsError("GPT creative response Cut output_language does not match the current job")
                references = cut.get("reference_evidence_ids")
                bound_ids = list(references) if isinstance(references, list) else []
            if not bound_ids or any(not isinstance(item, str) or item not in known_target_evidence_ids for item in bound_ids):
                raise ProductionPortsError("GPT creative response Cut target evidence does not match the current job")
        performance_contract = (
            self._source_audio_performance_contract(evidence=evidence, cuts=cuts)
            if kind == "script"
            else None
        )
        self._reject_unsafe_draft_data(value)
        receipt = response.get("receipt")
        if not isinstance(receipt, Mapping):
            raise ProductionPortsError("GPT creative response receipt is required")
        if receipt.get("provider") != "openai" or receipt.get("model_id") != self.config.openai_model:
            raise ProductionPortsError("GPT creative response model receipt does not match the configured model")
        if receipt.get("configuration_sha256") != self.config.openai_model_config_sha256:
            raise ProductionPortsError("GPT creative response model configuration digest does not match")
        request_sha256 = self._sha256_field(receipt.get("request_sha256"), "GPT creative response request SHA")
        response_sha256 = self._sha256_field(receipt.get("response_sha256"), "GPT creative response response SHA")
        transport = response.get("_transport_digests")
        if not isinstance(transport, Mapping):
            raise ProductionPortsError("GPT creative response transport digests are required")
        expected_request_sha256 = self._sha256_field(
            transport.get("request_sha256"), "GPT creative response transport request SHA"
        )
        expected_response_sha256 = self._sha256_field(
            transport.get("response_sha256"), "GPT creative response transport response SHA"
        )
        if request_sha256 != expected_request_sha256:
            raise ProductionPortsError("GPT creative response request sha256 does not match the transport receipt")
        if response_sha256 != expected_response_sha256:
            raise ProductionPortsError("GPT creative response response sha256 does not match the transport receipt")
        result = {
            "kind": kind,
            "inputs_sha256": _sha256(evidence),
            "value": dict(value),
            "receipt": {
                "provider": "openai",
                "model_id": self.config.openai_model,
                "configuration_sha256": self.config.openai_model_config_sha256,
                "request_sha256": request_sha256,
                "response_sha256": response_sha256,
            },
        }
        if performance_contract is not None:
            result["source_audio_contracts"] = dict(performance_contract)
        return result

    def _draft(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]], kind: str) -> Mapping[str, Any]:
        if not isinstance(input_artifacts, Sequence) or isinstance(input_artifacts, (str, bytes, bytearray)):
            raise ProductionPortsError("current job input artifacts are invalid")
        # The snapshot and artifact store remain authoritative.  Never forward
        # caller-provided objects, media URLs, or lease-local paths to GPT.
        response = self._request_structured(
            kind=kind,
            evidence=self._revision_evidence(context, kind=kind),
            schema=self._revision_schema(kind),
        )
        return self._validate_response(response, context=context, kind=kind)

    def draft_script(self, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        return self._draft(context=context, input_artifacts=input_artifacts, kind="script")

    def draft_storyboard(self, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        return self._draft(context=context, input_artifacts=input_artifacts, kind="storyboard")

    @staticmethod
    def _validate_strict_schema_node(schema: Mapping[str, Any], *, path: str) -> None:
        allowed_keywords = {
            "additionalProperties",
            "enum",
            "items",
            "properties",
            "required",
            "type",
        }
        unsupported = sorted(str(key) for key in set(schema) - allowed_keywords)
        if unsupported:
            raise ProductionPortsError(
                f"GPT structured output schema {path} has unsupported keyword: {unsupported[0]}"
            )
        if "enum" in schema:
            enum = schema["enum"]
            if not isinstance(enum, list) or not enum:
                raise ProductionPortsError(f"GPT structured output schema {path} enum must be a non-empty array")
            _canonical_json(enum)
        schema_type = schema.get("type")
        if schema_type == "object":
            if schema.get("additionalProperties") is not False:
                raise ProductionPortsError(f"GPT structured output schema {path} must set additionalProperties to false")
            properties = schema.get("properties")
            required = schema.get("required")
            if not isinstance(properties, Mapping) or not isinstance(required, list):
                raise ProductionPortsError(f"GPT structured output schema {path} object fields are incomplete")
            property_names = set(properties)
            if (
                any(not isinstance(name, str) for name in property_names)
                or any(not isinstance(name, str) for name in required)
                or len(required) != len(set(required))
                or set(required) != property_names
            ):
                raise ProductionPortsError(f"GPT structured output schema {path} must require every declared property")
            for name, child in properties.items():
                if not isinstance(child, Mapping):
                    raise ProductionPortsError(f"GPT structured output schema {path}.{name} must be an object")
                EvidenceBoundGptPlanner._validate_strict_schema_node(child, path=f"{path}.{name}")
            return
        if schema_type == "array":
            items = schema.get("items")
            if not isinstance(items, Mapping):
                raise ProductionPortsError(f"GPT structured output schema {path} array items must be an object")
            EvidenceBoundGptPlanner._validate_strict_schema_node(items, path=f"{path}[]")
            return
        if schema_type in {"string", "number", "integer", "boolean", "null"}:
            return
        raise ProductionPortsError(f"GPT structured output schema {path} has an unsupported type")

    @staticmethod
    def _validate_schema_value(value: Any, schema: Mapping[str, Any], *, path: str) -> None:
        schema_type = schema["type"]
        if schema_type == "object":
            if not isinstance(value, Mapping):
                raise ProductionPortsError(f"GPT structured output {path} does not match schema type object")
            properties = schema["properties"]
            if set(value) != set(properties):
                raise ProductionPortsError(f"GPT structured output {path} does not match declared object properties")
            for name, child in properties.items():
                EvidenceBoundGptPlanner._validate_schema_value(value[name], child, path=f"{path}.{name}")
        elif schema_type == "array":
            if not isinstance(value, list):
                raise ProductionPortsError(f"GPT structured output {path} does not match schema type array")
            for index, item in enumerate(value):
                EvidenceBoundGptPlanner._validate_schema_value(item, schema["items"], path=f"{path}[{index}]")
        elif schema_type == "string" and not isinstance(value, str):
            raise ProductionPortsError(f"GPT structured output {path} does not match schema type string")
        elif schema_type == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ProductionPortsError(f"GPT structured output {path} does not match schema type number")
        elif schema_type == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            raise ProductionPortsError(f"GPT structured output {path} does not match schema type integer")
        elif schema_type == "boolean" and not isinstance(value, bool):
            raise ProductionPortsError(f"GPT structured output {path} does not match schema type boolean")
        elif schema_type == "null" and value is not None:
            raise ProductionPortsError(f"GPT structured output {path} does not match schema type null")
        enum = schema.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise ProductionPortsError(f"GPT structured output {path} does not match the schema enum")

    @staticmethod
    def _strict_schema(kind: str, schema: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(schema, Mapping) or schema.get("type") != "object":
            raise ProductionPortsError("GPT structured output schema must describe an object")
        try:
            normalized = json.loads(_canonical_json(dict(schema)).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProductionPortsError("GPT structured output schema is invalid") from exc
        if not isinstance(normalized, dict):
            raise ProductionPortsError("GPT structured output schema must be an object")
        EvidenceBoundGptPlanner._validate_strict_schema_node(normalized, path="$")
        return {
            "type": "json_schema",
            "name": f"usfr_{kind}",
            "strict": True,
            "schema": normalized,
        }

    @staticmethod
    def _output_text(response: Mapping[str, Any]) -> str:
        top_level = response.get("output_text")
        if isinstance(top_level, str) and top_level.strip():
            return top_level
        output = response.get("output")
        if not isinstance(output, list):
            raise ProductionPortsError("GPT Responses response omitted structured output text")
        for message in output:
            if not isinstance(message, Mapping):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, Mapping) or item.get("type") != "output_text":
                    continue
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    return text
        raise ProductionPortsError("GPT Responses response omitted structured output text")

    def _request_structured(
        self,
        *,
        kind: str,
        evidence: Mapping[str, Any],
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if not isinstance(evidence, Mapping):
            raise ProductionPortsError("GPT evidence must be a JSON object")
        text_format = self._strict_schema(kind, schema)
        canonical_evidence = _canonical_json(dict(evidence)).decode("utf-8")
        preface = self._language_only_instruction(kind=kind, evidence=evidence)
        input_messages = []
        if preface:
            input_messages.append(
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": preface}],
                }
            )
        input_messages.append(
            {
                "role": "user",
                "content": [{"type": "input_text", "text": canonical_evidence}],
            }
        )
        payload = {
            "model": self.config.openai_model,
            "store": False,
            "input": input_messages,
            "text": {"format": text_format},
        }
        request_sha256 = _sha256(payload)
        try:
            response = self._request_json(
                url=f"{self.config.openai_base_url}/responses",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {_read_environment_secret(self.config.openai_api_key_env)}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                payload=payload,
                timeout_seconds=self._REQUEST_TIMEOUT_SECONDS,
            )
        except ProductionPortsError:
            raise
        except (TimeoutError, OSError, ValueError, TypeError) as exc:
            raise ProductionPortsError("GPT Responses request failed") from exc
        if not isinstance(response, Mapping):
            raise ProductionPortsError("GPT Responses response must be a JSON object")
        response_model = str(response.get("model") or "").strip()
        if response_model != self.config.openai_model:
            raise ProductionPortsError("GPT Responses response model does not match the configured model")
        try:
            value = json.loads(self._output_text(response))
        except json.JSONDecodeError as exc:
            raise ProductionPortsError("GPT Responses output was not valid JSON") from exc
        if not isinstance(value, Mapping):
            raise ProductionPortsError("GPT Responses structured output must be a JSON object")
        self._validate_schema_value(value, text_format["schema"], path="$")
        return {
            "kind": kind,
            "value": dict(value),
            "receipt": {
                "provider": "openai",
                "model_id": self.config.openai_model,
                "configuration_sha256": self.config.openai_model_config_sha256,
                "request_sha256": request_sha256,
                "response_sha256": _sha256(dict(response)),
            },
            "_transport_digests": {
                "request_sha256": request_sha256,
                "response_sha256": _sha256(dict(response)),
            },
        }


class _CreativeRevisionStage:
    """Publish one GPT-validated temporary revision without approving it."""

    def __init__(self, planner: EvidenceBoundGptPlanner, *, kind: str) -> None:
        if not isinstance(planner, EvidenceBoundGptPlanner):
            raise ProductionPortsError("creative revision stage requires an evidence-bound GPT planner")
        if kind not in {"script", "storyboard"}:
            raise ProductionPortsError(f"unsupported creative revision kind: {kind}")
        self._planner = planner
        self._kind = kind

    def _next_revision(self, context: Any) -> int:
        snapshot = getattr(context, "snapshot", None)
        field = "current_script_revision" if self._kind == "script" else "current_storyboard_revision"
        current = getattr(snapshot, field, None)
        if current is None:
            return 1
        if isinstance(current, bool) or not isinstance(current, int) or current < 0:
            raise ProductionPortsError(f"current job {field} is invalid")
        return current + 1

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        draft = (
            self._planner.draft_script(context, input_artifacts)
            if self._kind == "script"
            else self._planner.draft_storyboard(context, input_artifacts)
        )
        revision = self._next_revision(context)
        evidence = self._planner._revision_evidence(context, kind=self._kind)
        performance_line_contract: Mapping[str, Any] | None = None
        performance_line_sha256: str | None = None
        source_audio_contracts: Mapping[str, Any] | None = None
        if self._kind == "script":
            source_audio_contracts = draft.get("source_audio_contracts")
            if source_audio_contracts is not None:
                if not isinstance(source_audio_contracts, Mapping):
                    raise ProductionPortsError("script source-audio contracts are invalid")
                candidate = source_audio_contracts.get("performance_line_contract")
                if not isinstance(candidate, Mapping):
                    raise ProductionPortsError("script source-audio performance line contract is missing")
                performance_line_contract = dict(candidate)
                performance_line_sha256 = hashlib.sha256(
                    _canonical_json(performance_line_contract)
                ).hexdigest()
        payload = {
            "schema_version": _REVISION_SCHEMA_VERSION,
            "kind": self._kind,
            "revision": revision,
            "inputs_sha256": draft["inputs_sha256"],
            "source_sha256": evidence["source_sha256"],
            "source_dynamics_sha256": evidence["source_dynamics_sha256"],
            "target_sha256": evidence["target_sha256"],
            "target_evidence_ids": evidence["target_evidence_ids"],
            "output_language": evidence["output_language"],
            "parent_revision_sha256": evidence["parent_revision_sha256"],
            "source_cuts": evidence["source_cuts"],
            "cut_coverage_sha256": evidence["cut_coverage_sha256"],
            "request_evidence_sha256": evidence["request_evidence_sha256"],
            "cuts": draft["value"]["cuts"],
            "gpt_receipt": draft["receipt"],
        }
        if performance_line_sha256 is not None:
            payload["performance_line_contract_sha256"] = performance_line_sha256
        data = _canonical_json(payload)
        sha256 = hashlib.sha256(data).hexdigest()
        publisher = getattr(context, "publish_bytes", None)
        if not callable(publisher):
            raise ProductionPortsError("creative revision stage requires context.publish_bytes")
        try:
            published = publisher(
                kind=f"{self._kind}_revision",
                data=data,
                content_type="application/json",
                expected_sha256=sha256,
            )
        except ProductionPortsError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise ProductionPortsError("creative revision could not be published") from exc
        if not isinstance(published, Mapping):
            raise ProductionPortsError("creative revision publication returned an invalid artifact")
        published_sha256 = self._planner._sha256_field(published.get("sha256"), "published revision SHA")
        if published_sha256 != sha256:
            raise ProductionPortsError("published revision SHA does not match the validated draft")
        object_key = self._planner._safe_text(published.get("object_key"), "published revision object key")
        published_artifacts = [dict(published)]
        if performance_line_contract is not None and performance_line_sha256 is not None:
            line_bytes = _canonical_json(performance_line_contract)
            line_artifact = publisher(
                kind="performance_line_contract",
                data=line_bytes,
                content_type="application/json",
                expected_sha256=performance_line_sha256,
            )
            if not isinstance(line_artifact, Mapping) or self._planner._sha256_field(
                line_artifact.get("sha256"), "published performance line contract SHA"
            ) != performance_line_sha256:
                raise ProductionPortsError("published performance line contract SHA does not match")
            published_artifacts.append(dict(line_artifact))
        if source_audio_contracts is not None:
            for kind in ("performance_timeline_contract", "audio_splice_policy"):
                value = source_audio_contracts.get(kind)
                if not isinstance(value, Mapping):
                    raise ProductionPortsError(f"script source-audio {kind} is missing")
                contract_bytes = _canonical_json(dict(value))
                contract_sha256 = hashlib.sha256(contract_bytes).hexdigest()
                contract_artifact = publisher(
                    kind=kind,
                    data=contract_bytes,
                    content_type="application/json",
                    expected_sha256=contract_sha256,
                )
                if not isinstance(contract_artifact, Mapping) or self._planner._sha256_field(
                    contract_artifact.get("sha256"), f"published {kind} SHA"
                ) != contract_sha256:
                    raise ProductionPortsError(f"published {kind} SHA does not match")
                published_artifacts.append(dict(contract_artifact))
        parent_script_sha256 = evidence["parent_revision_sha256"] if self._kind == "storyboard" else None
        manifest = RevisionManifest(
            kind=self._kind,
            revision=revision,
            object_key=object_key,
            sha256=sha256,
            inputs_sha256=draft["inputs_sha256"],
            validation_sha256=_sha256(
                {
                    "revision_sha256": sha256,
                    "request_sha256": draft["receipt"]["request_sha256"],
                    "response_sha256": draft["receipt"]["response_sha256"],
                }
            ),
            parent_script_sha256=parent_script_sha256,
            output_language=evidence["output_language"],
        )
        return {
            f"{self._kind}_revision": manifest,
            "published_artifacts": published_artifacts,
            "gpt_receipt": dict(draft["receipt"]),
        }


class _DurableDynamicsEvidenceStage:
    """Persist the existing dynamics result for the later revision-only stage.

    The helper leaves the canonical ``analyze_dynamics`` result untouched.  It
    only turns its already-validated source Cut evidence into a temporary,
    SHA-verified JSON artifact so a later worker lease can materialize it
    without receiving a prior worker's in-memory result or local path.
    """

    def __init__(self, handler: Any) -> None:
        if handler is None:
            raise ProductionPortsError("durable dynamics evidence stage requires an existing stage handler")
        self._handler = handler

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        method = getattr(self._handler, "run", self._handler)
        if not callable(method):
            raise ProductionPortsError("durable dynamics evidence stage handler is invalid")
        value = method(context=context, input_artifacts=input_artifacts)
        if not isinstance(value, Mapping):
            raise ProductionPortsError("durable dynamics evidence stage returned no result")
        analysis = value.get("source_dynamics_analysis")
        if not isinstance(analysis, Mapping):
            raise ProductionPortsError("durable dynamics evidence stage returned no source dynamics analysis")
        # Do not serialize a capability's full result: it can contain local
        # staging details or backend-only reasoning.  The planner needs only
        # a frame-zero-contiguous, path-free Cut projection.
        source_cuts = EvidenceBoundGptPlanner._project_source_cuts(analysis)
        payload = _canonical_json({"source_dynamics_analysis": {"source_cuts": list(source_cuts)}})
        sha256 = hashlib.sha256(payload).hexdigest()
        publisher = getattr(context, "publish_bytes", None)
        if not callable(publisher):
            raise ProductionPortsError("durable dynamics evidence stage requires context.publish_bytes")
        published = publisher(
            kind="source_dynamics_analysis",
            data=payload,
            content_type="application/json",
            expected_sha256=sha256,
        )
        if not isinstance(published, Mapping) or self._planner_sha256(published.get("sha256")) != sha256:
            raise ProductionPortsError("durable dynamics evidence publication is invalid")
        result = dict(value)
        existing = result.get("published_artifacts")
        published_artifacts = [dict(item) for item in existing if isinstance(item, Mapping)] if isinstance(existing, list) else []
        published_artifacts.append(dict(published))
        result["published_artifacts"] = published_artifacts
        return result

    @staticmethod
    def _planner_sha256(value: Any) -> str:
        candidate = str(value or "").strip().lower()
        if _SHA256.fullmatch(candidate) is None:
            raise ProductionPortsError("durable dynamics evidence SHA is invalid")
        return candidate


class _ScriptRevisionStage(_CreativeRevisionStage):
    def __init__(self, planner: EvidenceBoundGptPlanner) -> None:
        super().__init__(planner, kind="script")


class _StoryboardRevisionStage(_CreativeRevisionStage):
    def __init__(self, planner: EvidenceBoundGptPlanner) -> None:
        super().__init__(planner, kind="storyboard")


class RunningHubSeedanceProvider:
    """One immutable, no-retry RunningHub provider adapter."""

    _REQUEST_TIMEOUT_SECONDS = 120.0
    _DOWNLOAD_TIMEOUT_SECONDS = 180.0

    def __init__(
        self,
        config: ProductionEnvironment,
        *,
        request_json: Callable[..., Mapping[str, Any]] | None = None,
        download_bytes: Callable[..., bytes] | None = None,
    ) -> None:
        self.config = config
        self._request_json = request_json or _post_json
        self._download_bytes = download_bytes or _download_bytes
        self._private_result_urls: dict[str, str] = {}

    def capability_identity(self) -> Mapping[str, Any]:
        identity = {
            "capability": "provider_video",
            "implementation": "server.production_ports:RunningHubSeedanceProvider",
            "version": "1.0.0",
            "provider": "runninghub",
            "base_url": self.config.runninghub_base_url,
            "workflow_id": self.config.runninghub_seedance_workflow_id,
            "model_id": self.config.runninghub_seedance_model_id,
            "configuration_sha256": self.config.runninghub_seedance_config_sha256,
        }
        return {**identity, "sha256": _sha256(identity)}

    def create_asset(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(request, Mapping):
            raise ProductionPortsError("RunningHub asset request must be a JSON object")
        return self._create(
            operation="asset",
            url=f"{self.config.runninghub_base_url}{_RUNNINGHUB_IMAGE_CREATE_PATH}",
            payload=dict(request),
        )

    def create_video(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(request, Mapping):
            raise ProductionPortsError("RunningHub video request must be a JSON object")
        return self._create(
            operation="video",
            url=self.config.runninghub_seedance_create_url,
            payload={
                "workflowId": self.config.runninghub_seedance_workflow_id,
                "modelId": self.config.runninghub_seedance_model_id,
                "request": dict(request),
            },
        )

    def _create(self, *, operation: str, url: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        request_sha256 = _sha256(dict(payload))
        api_key = _read_environment_secret(self.config.runninghub_api_key_env)
        try:
            response = self._request_json(
                url=url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                payload=dict(payload),
                timeout_seconds=self._REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise RunningHubCreateAmbiguousError(
                "RunningHub paid create outcome is ambiguous and must not be retried automatically"
            ) from exc
        if not isinstance(response, Mapping):
            raise RunningHubCreateAmbiguousError(
                "RunningHub paid create response is ambiguous and must not be retried automatically"
            )
        task_id = str(response.get("taskId") or "").strip()
        if not task_id:
            raise RunningHubCreateAmbiguousError(
                "RunningHub paid create response omitted taskId and must be reconciled before retry"
            )
        return {
            "task_id": task_id,
            "receipt": {
                "provider": "runninghub",
                "operation": operation,
                "task_id": task_id,
                "request_sha256": request_sha256,
                "response_sha256": _sha256(dict(response)),
                "configuration_sha256": self.config.runninghub_seedance_config_sha256,
            },
        }

    def lookup(self, intent: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(intent, Mapping) or set(intent) != {"taskId"}:
            raise ProductionPortsError("RunningHub lookup must contain only taskId")
        task_id = str(intent.get("taskId") or "").strip()
        if not task_id:
            raise ProductionPortsError("RunningHub lookup taskId is required")
        payload = {"taskId": task_id}
        try:
            response = self._request_json(
                url=self.config.runninghub_seedance_query_url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {_read_environment_secret(self.config.runninghub_api_key_env)}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                payload=payload,
                timeout_seconds=self._REQUEST_TIMEOUT_SECONDS,
            )
        except ProductionPortsError:
            raise
        except (TimeoutError, OSError, ValueError, TypeError) as exc:
            raise ProductionPortsError("RunningHub lookup request failed") from exc
        if not isinstance(response, Mapping):
            raise ProductionPortsError("RunningHub lookup response must be a JSON object")
        status = response.get("status")
        if not isinstance(status, str) or status not in _RUNNINGHUB_STATUSES:
            received = status if isinstance(status, str) else "<missing-or-non-string>"
            raise ProductionPortsError(f"RunningHub returned unsupported task status: {received}")
        receipt = {
            "provider": "runninghub",
            "task_id": task_id,
            "status": status,
            "request_sha256": _sha256(payload),
            "response_sha256": _sha256(dict(response)),
            "configuration_sha256": self.config.runninghub_seedance_config_sha256,
        }
        if status in _RUNNINGHUB_RUNNING_STATUSES:
            return {"task_id": task_id, "status": status, "receipt": receipt}
        if status in _RUNNINGHUB_FAILURE_STATUSES:
            message = str(response.get("message") or response.get("errorMessage") or "provider task failed")
            raise RunningHubTaskFailed(f"RunningHub task {task_id} ended with {status}: {message}")
        results = response.get("results")
        if not isinstance(results, list) or not results or not isinstance(results[0], Mapping):
            raise ProductionPortsError("RunningHub successful task omitted results[0]")
        result_url = str(results[0].get("url") or "").strip()
        _require_result_https_url(result_url)
        self._private_result_urls[task_id] = result_url
        return {
            "task_id": task_id,
            "status": status,
            "receipt": receipt,
        }

    def download(self, task_id_or_url: str, destination: str | Path) -> Mapping[str, Any]:
        private_task_id = str(task_id_or_url or "").strip()
        result_url = self._private_result_urls.get(private_task_id)
        if not result_url:
            raise ProductionPortsError("RunningHub download requires a private task result from lookup")
        _require_result_https_url(result_url)
        try:
            data = self._download_bytes(url=result_url, timeout_seconds=self._DOWNLOAD_TIMEOUT_SECONDS)
        except ProductionPortsError:
            raise
        except (TimeoutError, OSError, ValueError, TypeError) as exc:
            raise ProductionPortsError("RunningHub result download failed") from exc
        if not isinstance(data, bytes) or not data:
            raise ProductionPortsError("RunningHub result download was empty or invalid")
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        self._private_result_urls.pop(private_task_id, None)
        return {
            "provider": "runninghub",
            "result_url": _receipt_result_url(result_url),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }


def _require_result_https_url(value: str) -> None:
    _validated_https_url(value, "RunningHub result URL", allow_query=True)


def _receipt_result_url(value: str) -> str:
    """Retain the stable media location without copying a signed query token."""

    parsed = urlparse.urlparse(value)
    return urlparse.urlunparse(parsed._replace(query="", fragment=""))


__all__ = [
    "EvidenceBoundGptPlanner",
    "ProductionEnvironment",
    "ProductionPortsError",
    "RunningHubCreateAmbiguousError",
    "RunningHubSeedanceProvider",
    "RunningHubTaskFailed",
]
