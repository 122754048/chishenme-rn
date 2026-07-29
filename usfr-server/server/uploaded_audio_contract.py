"""Immutable classification contracts for a user-supplied audio replacement.

The classification boundary is deliberately narrow: an uploaded track is
either a song with a timestamped lyric transcript or a non-song replacement.
Unknown classifications are not a compatibility mode because they would let a
song bypass script confirmation and lip-sync requirements.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KINDS = {"song", "non_song"}
_MIN_CONFIDENCE = 0.80
_FIELDS = {
    "contract",
    "audio_sha256",
    "kind",
    "confidence",
    "classification_evidence_sha256",
    "lyrics",
}


class UploadedAudioContractError(ValueError):
    """Raised when a replacement-audio classification is unverified or ambiguous."""


class UploadedAudioClassifierUnavailable(RuntimeError):
    """Raised when the deployment-owned upload classifier cannot be used."""


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any, *, field: str) -> str:
    candidate = str(value or "").strip().lower()
    if _SHA256.fullmatch(candidate) is None:
        raise UploadedAudioContractError(f"{field} must be a lowercase SHA-256")
    return candidate


def _ms(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UploadedAudioContractError(f"{field} must be a non-negative integer millisecond value")
    return value


def validate_uploaded_audio_contract(
    value: Mapping[str, Any], *, audio_sha256: str
) -> dict[str, object]:
    """Validate the one current-run upload classification before script drafting.

    The caller supplies the immutable upload digest from the fixed input
    extension.  A contract for any other byte sequence is invalid even if its
    classification looks plausible.
    """

    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise UploadedAudioContractError("uploaded audio classification contract fields are invalid")
    if value.get("contract") != "uploaded-audio-classification/v1":
        raise UploadedAudioContractError("uploaded audio classification contract is unsupported")
    expected_audio = _sha256(audio_sha256, field="uploaded audio SHA")
    contract_audio = _sha256(value.get("audio_sha256"), field="audio_sha256")
    if contract_audio != expected_audio:
        raise UploadedAudioContractError("uploaded audio classification does not match the immutable upload")
    kind = str(value.get("kind") or "").strip().casefold()
    if kind not in _KINDS:
        raise UploadedAudioContractError("kind must be song or non_song")
    confidence = value.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not _MIN_CONFIDENCE <= float(confidence) <= 1.0:
        raise UploadedAudioContractError("uploaded audio classification confidence is ambiguous")
    evidence = _sha256(value.get("classification_evidence_sha256"), field="classification_evidence_sha256")
    lyrics = value.get("lyrics")
    if not isinstance(lyrics, Sequence) or isinstance(lyrics, (str, bytes, bytearray)):
        raise UploadedAudioContractError("lyrics must be an array")
    normalized: list[dict[str, object]] = []
    previous_end = 0
    for index, raw in enumerate(lyrics, start=1):
        if not isinstance(raw, Mapping) or set(raw) != {"start_ms", "end_ms", "text"}:
            raise UploadedAudioContractError("lyric window is invalid")
        start_ms = _ms(raw.get("start_ms"), field=f"lyrics[{index}].start_ms")
        end_ms = _ms(raw.get("end_ms"), field=f"lyrics[{index}].end_ms")
        text = str(raw.get("text") or "").strip()
        if end_ms <= start_ms or not text:
            raise UploadedAudioContractError("lyric window is invalid")
        if start_ms < previous_end:
            raise UploadedAudioContractError("lyrics overlap or are out of order")
        normalized.append({"start_ms": start_ms, "end_ms": end_ms, "text": text})
        previous_end = end_ms
    if kind == "song" and not normalized:
        raise UploadedAudioContractError("song classification requires timestamped lyrics")
    if kind == "non_song" and normalized:
        raise UploadedAudioContractError("non_song classification cannot carry lyrics")
    return {
        "contract": "uploaded-audio-classification/v1",
        "audio_sha256": contract_audio,
        "kind": kind,
        "confidence": float(confidence),
        "classification_evidence_sha256": evidence,
        "lyrics": normalized,
    }


class EvidenceBoundHttpUploadedAudioClassifier:
    """Classify an uploaded audio replacement without trusting worker-local hints.

    The backend receives the exact upload bytes and returns a model-bound
    song/non-song classification.  Its raw response hash becomes the immutable
    evidence ID stored beside the classification contract.
    """

    evidence_bound = True
    capability_kind = "uploaded_audio_classifier"

    def __init__(
        self,
        *,
        endpoint: str,
        model_id: str,
        model_sha256: str,
        api_token: str | None = None,
        timeout_seconds: float = 120.0,
        production: bool = True,
        implementation: str = "server.uploaded_audio_contract:EvidenceBoundHttpUploadedAudioClassifier",
        version: str = "1.0.0",
    ) -> None:
        self.endpoint = str(endpoint or "").strip()
        parsed = urlparse(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("uploaded audio classifier endpoint must be a credential-free HTTP(S) URL")
        if production and parsed.scheme != "https":
            raise ValueError("production uploaded audio classifier endpoint must use HTTPS")
        self.model_id = str(model_id or "").strip()
        if not self.model_id:
            raise ValueError("uploaded audio classifier model_id is required")
        self.model_sha256 = _sha256(model_sha256, field="uploaded audio classifier model_sha256")
        self.api_token = str(api_token).strip() if api_token else None
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("uploaded audio classifier timeout_seconds must be positive")
        self.production = bool(production)
        self.implementation = implementation
        self.version = version

    @classmethod
    def from_environment(cls, *, production: bool = True) -> "EvidenceBoundHttpUploadedAudioClassifier":
        import os

        return cls(
            endpoint=os.environ["USFR_UPLOADED_AUDIO_CLASSIFIER_ENDPOINT"],
            model_id=os.environ["USFR_UPLOADED_AUDIO_CLASSIFIER_MODEL_ID"],
            model_sha256=os.environ["USFR_UPLOADED_AUDIO_CLASSIFIER_MODEL_SHA256"],
            api_token=os.getenv("USFR_UPLOADED_AUDIO_CLASSIFIER_API_TOKEN"),
            production=production,
        )

    def capability_identity(self) -> dict[str, str]:
        return {
            "capability": self.capability_kind,
            "implementation": self.implementation,
            "version": self.version,
            "evidence_binding": "usfr-uploaded-audio-classification-evidence/v1",
            "model_id": self.model_id,
            "model_sha256": self.model_sha256,
        }

    def classify_uploaded_audio(self, path: str | Path, *, audio_sha256: str) -> dict[str, object]:
        expected_audio_sha256 = _sha256(audio_sha256, field="uploaded audio SHA")
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            raise UploadedAudioClassifierUnavailable("could not read uploaded audio bytes") from exc
        actual_audio_sha256 = hashlib.sha256(data).hexdigest()
        if actual_audio_sha256 != expected_audio_sha256:
            raise UploadedAudioContractError("uploaded audio bytes do not match the immutable upload")
        request_payload: dict[str, Any] = {
            "schema_version": "usfr-uploaded-audio-classification-request/v1",
            "input_sha256": actual_audio_sha256,
            "model": {"id": self.model_id, "sha256": self.model_sha256},
            "audio_b64": base64.b64encode(data).decode("ascii"),
        }
        request_sha256 = hashlib.sha256(_canonical(request_payload)).hexdigest()
        request_payload["request_sha256"] = request_sha256
        request = Request(
            self.endpoint,
            data=_canonical(request_payload),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                **({"Authorization": f"Bearer {self.api_token}"} if self.api_token else {}),
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - deployment-owned endpoint
                raw_response = response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise UploadedAudioClassifierUnavailable("uploaded audio classifier request failed") from exc
        try:
            response = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UploadedAudioContractError("uploaded audio classifier returned malformed JSON") from exc
        if not isinstance(response, Mapping):
            raise UploadedAudioContractError("uploaded audio classifier response must be an object")
        if response.get("schema_version") != "usfr-uploaded-audio-classification-evidence/v1":
            raise UploadedAudioContractError("uploaded audio classifier response schema is unsupported")
        if response.get("request_sha256") != request_sha256 or response.get("input_sha256") != actual_audio_sha256:
            raise UploadedAudioContractError("uploaded audio classifier response is not bound to the request")
        model = response.get("model")
        if (
            not isinstance(model, Mapping)
            or model.get("id") != self.model_id
            or str(model.get("sha256") or "").lower() != self.model_sha256
        ):
            raise UploadedAudioContractError("uploaded audio classifier model identity does not match")
        classification = response.get("classification")
        if not isinstance(classification, Mapping):
            raise UploadedAudioContractError("uploaded audio classifier response has no classification")
        contract = {
            "contract": "uploaded-audio-classification/v1",
            "audio_sha256": actual_audio_sha256,
            "kind": classification.get("kind"),
            "confidence": classification.get("confidence"),
            "classification_evidence_sha256": hashlib.sha256(raw_response).hexdigest(),
            "lyrics": classification.get("lyrics"),
        }
        return validate_uploaded_audio_contract(contract, audio_sha256=actual_audio_sha256)


__all__ = [
    "EvidenceBoundHttpUploadedAudioClassifier",
    "UploadedAudioClassifierUnavailable",
    "UploadedAudioContractError",
    "validate_uploaded_audio_contract",
]
