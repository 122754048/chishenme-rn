"""Server-only, single-attempt authorization for paid Seedance requests.

Provider request sidecars are deliberately not part of the public RunningHub
payload.  A syntactically complete mapping (even one carrying a previously
valid HMAC) is therefore untrusted until this module binds it to the current
job's immutable audit/media artifacts and the one persisted Provider attempt.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Mapping, Sequence
from typing import Any

from .runninghub_standard_contract import (
    RunningHubStandardPayloadError,
    validate_audio_reference_artifact_receipt,
)


_SCHEMA = "usfr-provider-request-authorization/v1"
_SHA = __import__("re").compile(r"^[0-9a-f]{64}$")
_FIELDS = frozenset(
    {
        "schema_version", "job_id", "audit_artifact_id", "audit_artifact_sha256",
        "payload_sha256", "video_reference_binding_sha256", "final_reference_lineage_sha256",
        "audio_reference_binding_sha256", "audio_reference_artifact_receipt_sha256",
        "visual_artifacts", "audio_artifact", "attempt_id", "expires_at_ms", "nonce", "hmac_sha256",
    }
)


class AudioProviderAuthorizationError(ValueError):
    """The request was not minted for this exact server-side paid attempt."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _ref_field(ref: Any, field: str) -> Any:
    return ref.get(field) if isinstance(ref, Mapping) else getattr(ref, field, None)


def _identity(ref: Any, *, kind: str) -> dict[str, str]:
    artifact_id = str(_ref_field(ref, "artifact_id") or "").strip()
    object_key = str(_ref_field(ref, "object_key") or "").strip()
    digest = str(_ref_field(ref, "sha256") or "").lower()
    if (
        str(_ref_field(ref, "kind") or "") != kind
        or not artifact_id or not object_key or _SHA.fullmatch(digest) is None
    ):
        raise AudioProviderAuthorizationError(f"server artifact is not an immutable {kind}")
    return {"artifact_id": artifact_id, "object_key": object_key, "kind": kind, "sha256": digest}


def _same_identity(actual: Any, expected: Mapping[str, str]) -> bool:
    try:
        return _identity(actual, kind=expected["kind"]) == dict(expected)
    except AudioProviderAuthorizationError:
        return False


def _audio_identity(
    job_store: Any, job_id: str, receipt: Mapping[str, object], binding: Mapping[str, object]
) -> dict[str, str]:
    try:
        validate_audio_reference_artifact_receipt(binding, receipt)
    except RunningHubStandardPayloadError as exc:
        raise AudioProviderAuthorizationError("audio artifact receipt is invalid") from exc
    ref = job_store.get_artifact(job_id, str(receipt["artifact_id"]))
    expected = _identity(ref, kind="background_music_reference")
    if (
        expected["artifact_id"] != receipt["artifact_id"]
        or expected["object_key"] != receipt["object_key"]
        or expected["sha256"] != receipt["sha256"]
    ):
        raise AudioProviderAuthorizationError("audio artifact receipt is not a current-job server artifact")
    metadata = _ref_field(ref, "metadata")
    for field in (
        "source_audio_sha256", "segment_id", "start_ms", "end_ms", "segment_plan_sha256",
        "replacement_timing_policy", "source_music_windows",
    ):
        if not isinstance(metadata, Mapping) or metadata.get(field) != receipt.get(field):
            raise AudioProviderAuthorizationError("audio artifact receipt does not match current server metadata")
    return expected


def _visual_identities(job_store: Any, job_id: str, lineage: Mapping[str, object] | None) -> list[dict[str, str]]:
    if lineage is None:
        return []
    board = lineage.get("approved_board")
    source = lineage.get("source_reference")
    if not isinstance(board, Mapping) or not isinstance(source, Mapping):
        raise AudioProviderAuthorizationError("final visual lineage lacks immutable board/source identities")
    expected_rows = [
        ("storyboard_image", board.get("artifact_id"), board.get("sha256")),
        ("source_video_reference", source.get("artifact_id"), source.get("sha256")),
    ]
    for kind, sha_field in (
        ("source_keyframe_sheet", board.get("source_keyframe_sheet_sha256")),
        ("replacement_control_keyframe_sheet", board.get("replacement_control_keyframe_sheet_sha256")),
        ("replacement_control_keyframe_receipt", board.get("replacement_control_keyframe_receipt_sha256")),
    ):
        digest = str(sha_field or "").lower()
        matches = [
            row for row in job_store.list_artifacts(job_id)
            if str(_ref_field(row, "kind") or "") == kind and str(_ref_field(row, "sha256") or "").lower() == digest
        ]
        if len(matches) != 1:
            raise AudioProviderAuthorizationError(f"final visual lineage lacks one current-job {kind} artifact")
        expected_rows.append((kind, _ref_field(matches[0], "artifact_id"), digest))
    result: list[dict[str, str]] = []
    for kind, artifact_id, digest in expected_rows:
        ref = job_store.get_artifact(job_id, str(artifact_id or ""))
        identity = _identity(ref, kind=kind)
        if identity["sha256"] != str(digest or "").lower():
            raise AudioProviderAuthorizationError("final visual lineage artifact digest differs from current server artifact")
        result.append(identity)
    return result


def _signature_payload(value: Mapping[str, object]) -> dict[str, object]:
    return {key: value[key] for key in sorted(_FIELDS - {"hmac_sha256"})}


def _sign(value: Mapping[str, object], secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), _canonical(_signature_payload(value)), hashlib.sha256).hexdigest()


class ServerAudioAuthorizationVerifier:
    """Injected, non-serializable authority consumed directly before HTTP."""

    def __init__(self, *, job_store: Any, job_id: str, authorization: Mapping[str, object], secret: str) -> None:
        self._job_store = job_store
        self._job_id = job_id
        self._authorization = dict(authorization)
        self._secret = secret
        self._consumed = False

    def verify_and_consume(
        self,
        *, payload: Mapping[str, object], video_reference_binding: Mapping[str, object] | None,
        final_reference_lineage: Mapping[str, object] | None,
        audio_reference_binding: Mapping[str, object] | None,
        audio_reference_artifact_receipt: Mapping[str, object] | None,
        authorization: Mapping[str, object] | None,
    ) -> None:
        if self._consumed:
            raise AudioProviderAuthorizationError("audio provider authorization was already consumed")
        if not isinstance(authorization, Mapping) or dict(authorization) != self._authorization:
            raise AudioProviderAuthorizationError("audio provider authorization differs from the server-minted attempt")
        if set(authorization) != _FIELDS or authorization.get("schema_version") != _SCHEMA:
            raise AudioProviderAuthorizationError("audio provider authorization schema is invalid")
        if not hmac.compare_digest(str(authorization.get("hmac_sha256") or ""), _sign(authorization, self._secret)):
            raise AudioProviderAuthorizationError("audio provider authorization HMAC is invalid")
        now_ms = time.time_ns() // 1_000_000
        if now_ms >= int(authorization.get("expires_at_ms") or 0):
            raise AudioProviderAuthorizationError("audio provider authorization has expired")
        snapshot = self._job_store.get_job(self._job_id)
        if snapshot is None or str(_ref_field(snapshot, "job_id") or "") != self._job_id:
            raise AudioProviderAuthorizationError("audio provider authorization job no longer exists")
        if int(_ref_field(snapshot, "expires_at_ms") or 0) != int(authorization["expires_at_ms"]):
            raise AudioProviderAuthorizationError("audio provider authorization job expiry is stale")
        if _digest(dict(payload)) != authorization["payload_sha256"]:
            raise AudioProviderAuthorizationError("audio provider authorization payload differs from the audited request")
        checks = {
            "video_reference_binding_sha256": _digest(dict(video_reference_binding)) if isinstance(video_reference_binding, Mapping) else None,
            "final_reference_lineage_sha256": _digest(dict(final_reference_lineage)) if isinstance(final_reference_lineage, Mapping) else None,
            "audio_reference_binding_sha256": _digest(dict(audio_reference_binding)) if isinstance(audio_reference_binding, Mapping) else None,
            "audio_reference_artifact_receipt_sha256": _digest(dict(audio_reference_artifact_receipt)) if isinstance(audio_reference_artifact_receipt, Mapping) else None,
        }
        if any(authorization.get(key) != value for key, value in checks.items()):
            raise AudioProviderAuthorizationError("audio provider authorization sidecars differ from the audited request")
        audit = self._job_store.get_artifact(self._job_id, str(authorization["audit_artifact_id"]))
        try:
            audit_identity = _identity(audit, kind="seedance_request_audit")
        except AudioProviderAuthorizationError as exc:
            raise AudioProviderAuthorizationError("audio provider authorization audit artifact is stale") from exc
        if audit_identity["artifact_id"] != authorization["audit_artifact_id"] or audit_identity["sha256"] != authorization["audit_artifact_sha256"]:
            raise AudioProviderAuthorizationError("audio provider authorization audit artifact is stale")
        if isinstance(audio_reference_binding, Mapping) and isinstance(audio_reference_artifact_receipt, Mapping):
            if authorization.get("audio_artifact") != _audio_identity(self._job_store, self._job_id, audio_reference_artifact_receipt, audio_reference_binding):
                raise AudioProviderAuthorizationError("audio provider authorization music artifact is stale")
        elif authorization.get("audio_artifact") is not None:
            raise AudioProviderAuthorizationError("audio provider authorization unexpectedly carries music evidence")
        if authorization.get("visual_artifacts") != _visual_identities(self._job_store, self._job_id, final_reference_lineage):
            raise AudioProviderAuthorizationError("audio provider authorization visual artifacts are stale")
        attempts = self._job_store.list_provider_attempts(self._job_id)
        expected_attempt = next((row for row in attempts if _ref_field(row, "attempt_id") == authorization["attempt_id"]), None)
        if (
            expected_attempt is None
            or _ref_field(expected_attempt, "operation") != "CreateVideo"
            or _ref_field(expected_attempt, "status") != "SUBMITTING"
            or _ref_field(expected_attempt, "request_sha256") != authorization["payload_sha256"]
        ):
            raise AudioProviderAuthorizationError("audio provider authorization attempt scope is stale")
        consume = getattr(self._job_store, "consume_provider_authorization_nonce", None)
        if not callable(consume):
            raise AudioProviderAuthorizationError("job store cannot durably consume provider authorization")
        try:
            consumed = consume(
                job_id=self._job_id,
                attempt_id=str(authorization["attempt_id"]),
                request_sha256=str(authorization["payload_sha256"]),
                nonce=str(authorization["nonce"]),
                authorization_sha256=_digest(dict(authorization)),
                expires_at_ms=int(authorization["expires_at_ms"]),
            )
        except Exception as exc:
            raise AudioProviderAuthorizationError("audio provider authorization nonce could not be durably consumed") from exc
        if consumed is not True:
            raise AudioProviderAuthorizationError("audio provider authorization was already consumed or is stale")
        self._consumed = True


def mint_audio_provider_authorization(
    *, job_store: Any, job_id: str, audit_artifact: Any, payload: Mapping[str, object],
    video_reference_binding: Mapping[str, object] | None, final_reference_lineage: Mapping[str, object] | None = None,
    audio_reference_binding: Mapping[str, object] | None, audio_reference_artifact_receipt: Mapping[str, object] | None,
    attempt: Any, secret: str,
) -> tuple[dict[str, object], ServerAudioAuthorizationVerifier]:
    """Mint one authorization after the durable attempt has been persisted."""

    if not isinstance(secret, str) or not secret:
        raise AudioProviderAuthorizationError("server capability secret is required")
    snapshot = job_store.get_job(job_id)
    if snapshot is None or str(_ref_field(snapshot, "job_id") or "") != job_id:
        raise AudioProviderAuthorizationError("cannot authorize a missing job")
    audit = _identity(audit_artifact, kind="seedance_request_audit")
    if not _same_identity(job_store.get_artifact(job_id, audit["artifact_id"]), audit):
        raise AudioProviderAuthorizationError("seedance request audit is not a current-job immutable artifact")
    payload_sha256 = _digest(dict(payload))
    if (
        _ref_field(attempt, "operation") != "CreateVideo"
        or _ref_field(attempt, "status") != "SUBMITTING"
        or _ref_field(attempt, "request_sha256") != payload_sha256
    ):
        raise AudioProviderAuthorizationError("provider attempt is not the current audited request")
    if bool(audio_reference_binding) != bool(audio_reference_artifact_receipt):
        raise AudioProviderAuthorizationError("audio authorization requires both binding and artifact receipt")
    audio_artifact = (
        _audio_identity(job_store, job_id, audio_reference_artifact_receipt, audio_reference_binding)
        if isinstance(audio_reference_binding, Mapping) and isinstance(audio_reference_artifact_receipt, Mapping)
        else None
    )
    authorization: dict[str, object] = {
        "schema_version": _SCHEMA, "job_id": job_id,
        "audit_artifact_id": audit["artifact_id"], "audit_artifact_sha256": audit["sha256"],
        "payload_sha256": payload_sha256,
        "video_reference_binding_sha256": _digest(dict(video_reference_binding)) if isinstance(video_reference_binding, Mapping) else None,
        "final_reference_lineage_sha256": _digest(dict(final_reference_lineage)) if isinstance(final_reference_lineage, Mapping) else None,
        "audio_reference_binding_sha256": _digest(dict(audio_reference_binding)) if isinstance(audio_reference_binding, Mapping) else None,
        "audio_reference_artifact_receipt_sha256": _digest(dict(audio_reference_artifact_receipt)) if isinstance(audio_reference_artifact_receipt, Mapping) else None,
        "visual_artifacts": _visual_identities(job_store, job_id, final_reference_lineage),
        "audio_artifact": audio_artifact, "attempt_id": str(_ref_field(attempt, "attempt_id") or ""),
        "expires_at_ms": int(_ref_field(snapshot, "expires_at_ms") or 0), "nonce": secrets.token_urlsafe(24),
    }
    if not authorization["attempt_id"] or int(authorization["expires_at_ms"]) <= time.time_ns() // 1_000_000:
        raise AudioProviderAuthorizationError("provider attempt authorization is already expired")
    authorization["hmac_sha256"] = _sign(authorization, secret)
    return authorization, ServerAudioAuthorizationVerifier(
        job_store=job_store, job_id=job_id, authorization=authorization, secret=secret
    )


__all__ = ["AudioProviderAuthorizationError", "ServerAudioAuthorizationVerifier", "mint_audio_provider_authorization"]
