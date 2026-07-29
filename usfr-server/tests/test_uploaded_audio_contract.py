from __future__ import annotations

import json
from hashlib import sha256

import pytest

from server.uploaded_audio_contract import UploadedAudioContractError, validate_uploaded_audio_contract


def _contract(*, kind: str = "song", lyrics: list[dict] | None = None) -> dict:
    return {
        "contract": "uploaded-audio-classification/v1",
        "audio_sha256": "a" * 64,
        "kind": kind,
        "confidence": 0.97,
        "classification_evidence_sha256": "b" * 64,
        "lyrics": lyrics if lyrics is not None else [
            {"start_ms": 0, "end_ms": 4000, "text": "Meet me where the morning starts"}
        ],
    }


def test_song_classification_requires_a_timestamped_lyric_transcript() -> None:
    contract = validate_uploaded_audio_contract(_contract(), audio_sha256="a" * 64)

    assert contract["kind"] == "song"
    assert contract["lyrics"] == [
        {"start_ms": 0, "end_ms": 4000, "text": "Meet me where the morning starts"}
    ]


def test_non_song_classification_allows_no_lyrics_and_is_replacement_only() -> None:
    contract = validate_uploaded_audio_contract(_contract(kind="non_song", lyrics=[]), audio_sha256="a" * 64)

    assert contract["kind"] == "non_song"
    assert contract["lyrics"] == []


def test_evidence_bound_classifier_publishes_a_song_contract_from_the_exact_upload(monkeypatch, tmp_path) -> None:
    from server import uploaded_audio_contract as contracts
    from server.uploaded_audio_contract import EvidenceBoundHttpUploadedAudioClassifier

    upload = tmp_path / "song.wav"
    upload.write_bytes(b"RIFFsong")
    audio_sha = sha256(upload.read_bytes()).hexdigest()

    class Response:
        def __init__(self, data: bytes) -> None:
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return self.data

    response_bytes: list[bytes] = []

    def fake_urlopen(request, *, timeout: float):
        assert timeout == 120.0
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["input_sha256"] == audio_sha
        response = {
            "schema_version": "usfr-uploaded-audio-classification-evidence/v1",
            "request_sha256": payload["request_sha256"],
            "input_sha256": audio_sha,
            "model": {"id": "music-classifier", "sha256": "c" * 64},
            "classification": {
                "kind": "song",
                "confidence": 0.98,
                "lyrics": [{"start_ms": 0, "end_ms": 3000, "text": "We are ready tonight"}],
            },
        }
        encoded = json.dumps(response, separators=(",", ":")).encode("utf-8")
        response_bytes.append(encoded)
        return Response(encoded)

    monkeypatch.setattr(contracts, "urlopen", fake_urlopen)
    classifier = EvidenceBoundHttpUploadedAudioClassifier(
        endpoint="http://classifier.test/v1/classify",
        model_id="music-classifier",
        model_sha256="c" * 64,
        production=False,
    )

    contract = classifier.classify_uploaded_audio(upload, audio_sha256=audio_sha)

    assert contract["audio_sha256"] == audio_sha
    assert contract["kind"] == "song"
    assert contract["lyrics"] == [{"start_ms": 0, "end_ms": 3000, "text": "We are ready tonight"}]
    assert contract["classification_evidence_sha256"] == sha256(response_bytes[0]).hexdigest()


@pytest.mark.parametrize(
    "value, message",
    [
        (_contract(kind="unknown"), "kind must be song or non_song"),
        (_contract(lyrics=[]), "song classification requires timestamped lyrics"),
        (_contract(lyrics=[{"start_ms": 0, "end_ms": 4000, "text": "one"}, {"start_ms": 3500, "end_ms": 5000, "text": "two"}]), "lyrics overlap"),
    ],
)
def test_ambiguous_or_malformed_uploaded_audio_classification_blocks(value: dict, message: str) -> None:
    with pytest.raises(UploadedAudioContractError, match=message):
        validate_uploaded_audio_contract(value, audio_sha256="a" * 64)
