from __future__ import annotations

from hashlib import sha256

import pytest


MODEL_SHA = "a" * 64


def _config():
    from server.production_ports import ProductionEnvironment

    return ProductionEnvironment(
        openai_api_key_env="OPENAI_API_KEY",
        capability_secret_env="USFR_CAPABILITY_SECRET",
        openai_base_url="https://api.example.test/v1",
        openai_model="gpt-test",
        openai_model_config_sha256=MODEL_SHA,
        runninghub_api_key_env="RUNNINGHUB_API_KEY",
        runninghub_base_url="https://runninghub.example.test",
        runninghub_seedance_api_key_env="RUNNINGHUB_SEEDANCE_API_KEY",
        runninghub_seedance_create_url="https://runninghub.example.test/create",
        runninghub_seedance_query_url="https://runninghub.example.test/query",
        runninghub_seedance_upload_url="https://runninghub.example.test/upload",
        runninghub_seedance_model_id="seedance-2.0-fast-token",
        runninghub_seedance_config_sha256="b" * 64,
    )


def _response(**_kwargs):
    return {"output_text": '{"summary":"verified"}'}


def test_gateway_rejects_local_path_and_requires_structured_gpt_response() -> None:
    from server.gpt_evidence_gateway import GptEvidenceError, GptEvidenceGateway

    gateway = GptEvidenceGateway(config=_config(), request_json=_response)

    with pytest.raises(GptEvidenceError, match="local path"):
        gateway.analyze(path="C:/source.mp4", evidence={})


def test_gateway_binds_media_and_model_identity_to_every_receipt(monkeypatch) -> None:
    from server.gpt_evidence_gateway import GptEvidenceGateway

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-secret")
    gateway = GptEvidenceGateway(config=_config(), request_json=_response)
    result = gateway.recognize(media_bytes=b"ui", expected_text=["Buy"])

    assert result["input_sha256"] == sha256(b"ui").hexdigest()
    assert result["model_sha256"] == MODEL_SHA
    assert result["receipt"]["schema_version"] == "usfr-gpt-evidence/v1"
    assert result["receipt"]["request_sha256"] != result["receipt"]["response_sha256"]


def test_gateway_sends_all_frame_bytes_in_one_bound_video_evidence_request(monkeypatch) -> None:
    from server.gpt_evidence_gateway import GptEvidenceGateway

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-secret")
    captured: dict[str, object] = {}

    def response(**kwargs):
        captured.update(kwargs)
        return {"output_text": '{"source_cuts":[]}' }

    gateway = GptEvidenceGateway(config=_config(), request_json=response)
    result = gateway.analyze_images(
        frames=[
            {"bytes": b"frame-zero", "content_type": "image/jpeg", "timestamp_us": 0},
            {"bytes": b"frame-one", "content_type": "image/jpeg", "timestamp_us": 1_000_000},
        ],
        evidence={"source_sha256": "f" * 64, "purpose": "single-pass-video"},
    )

    content = captured["payload"]["input"][0]["content"]
    assert [item["type"] for item in content] == ["input_text", "input_image", "input_image"]
    assert result["frame_sha256s"] == [sha256(b"frame-zero").hexdigest(), sha256(b"frame-one").hexdigest()]
    assert result["receipt"]["input_sha256s"] == result["frame_sha256s"]
