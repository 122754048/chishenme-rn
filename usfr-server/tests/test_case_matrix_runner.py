from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from validation.tools.run_case_matrix import (
    HttpMatrixTransport,
    MatrixRunError,
    run_case,
    run_case_matrix,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads(
    (ROOT / "validation" / "case_catalog.json").read_text(encoding="utf-8")
)


def _context() -> dict[str, str]:
    return {
        "bundle_sha256": "a" * 64,
        "capability_sha256": "b" * 64,
        "model_sha256": "c" * 64,
        "provider_sha256": "d" * 64,
        "prompt_compiler_sha256": "e" * 64,
    }


def _fixtures() -> dict[str, Any]:
    assets: dict[str, Any] = {}
    for case in CATALOG["cases"]:
        for record in [case["source_fixture"], *case["replacement_fixtures"]]:
            asset_id = record["asset_id"]
            if asset_id.startswith(("https://", "parameter/")):
                continue
            suffix = Path(asset_id).suffix.lower()
            video = suffix in {".mp4", ".mov", ".webm", ".m4v"}
            content_type = "video/mp4" if video else "image/png"
            completion = {
                "object_key": f"uploads/validation/{asset_id}",
                "sha256": record["sha256"],
                "size_bytes": 1024,
                "content_type": content_type,
                "status": "completed",
                "verified": True,
                "receipt_sha256": "9" * 64,
            }
            if video:
                completion["duration_seconds"] = 1.0
            assets[asset_id] = completion
    return {"schema_version": "usfr-validation-fixtures/v1", "assets": assets}


class FakeTransport:
    def __init__(self, *, hard_failure_case: str | None = None) -> None:
        self.hard_failure_case = hard_failure_case
        self.jobs: dict[str, str] = {}
        self.approvals: list[tuple[str, str]] = []
        self.created: list[str] = []

    def job_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        del token
        if method == "POST" and path == "/api/v1/jobs":
            source = payload["slots"]["source_video"]["object_key"]
            case_id = source.split("/")[-2].upper()
            job_id = f"job-{case_id}"
            self.jobs[job_id] = case_id
            self.created.append(case_id)
            return {"job_id": job_id, "version": 1, "capability_token": f"token-{case_id}"}
        job_id = path.split("/")[4]
        case_id = self.jobs[job_id]
        if method == "POST" and path.endswith("/start"):
            return {"job_id": job_id, "version": 2, "state": "ANALYZING"}
        if method == "GET" and path.endswith("/scripts"):
            return {"job_id": job_id, "revisions": [{"revision": 1, "sha256": "1" * 64, "status": "CURRENT"}]}
        if method == "GET" and path.endswith("/storyboards"):
            return {"job_id": job_id, "revisions": [{"revision": 1, "sha256": "2" * 64, "status": "CURRENT"}]}
        if method == "POST" and "/scripts/1/approve" in path:
            self.approvals.append((case_id, "script"))
            return {"job_id": job_id, "version": 3, "state": "AWAITING_STORYBOARD_APPROVAL"}
        if method == "POST" and "/storyboards/1/approve" in path:
            self.approvals.append((case_id, "storyboard"))
            return {"job_id": job_id, "version": 4, "state": "GENERATING"}
        if method == "GET" and path.endswith("/result"):
            return {
                "job_id": job_id,
                "result": {
                    "object_key": f"final/{job_id}/result.mp4",
                    "sha256": (case_id.lower().encode().hex() + "f" * 64)[:64],
                },
            }
        if method == "GET" and path == f"/api/v1/jobs/{job_id}":
            return {"job_id": job_id, "version": 2, "state": "ANALYZING"}
        raise AssertionError((method, path, payload))

    def evaluate(
        self,
        *,
        case: dict[str, Any],
        job_id: str,
        final_ref: dict[str, Any],
        dependency_context: dict[str, str],
    ) -> dict[str, Any]:
        del job_id
        case_id = case["case_id"]
        expected = case["expected"]
        tags = set(case["coverage_tags"])
        generated_ui = expected["ui_route"] == "generated_ui_demo"
        readable = bool(tags & {"overlay_text", "readable_text"})
        hard = ["synthetic_hard_failure"] if case_id == self.hard_failure_case else []
        return {
            "total_score": 94.0,
            "factor_scores": {gate: 96.0 for gate in expected["hard_gates"]},
            "route_percent": 100.0,
            "timeline_percent": 100.0,
            "ui_ocr_percent": 100.0 if generated_ui else None,
            "ui_layout_percent": 100.0 if generated_ui else None,
            "text_ocr_percent": 100.0 if readable else None,
            "text_layout_percent": 100.0 if readable else None,
            "claim_failures": [],
            "hard_failures": hard,
            "media_probe": {"playable": True, "video_codec": "h264", "audio_codec": "aac"},
            "evaluator_receipt": {
                "verified": True,
                "evaluator": "fake-private-qc:v1",
                "model_sha256": dependency_context["model_sha256"],
                "request_sha256": "5" * 64,
                "response_sha256": "6" * 64,
                "receipt_sha256": "7" * 64,
                "source_sha256": case["source_fixture"]["sha256"],
                "final_sha256": final_ref["sha256"],
            },
        }


def _case(case_id: str) -> dict[str, Any]:
    return next(case for case in CATALOG["cases"] if case["case_id"] == case_id)


def test_run_case_honors_route_two_one_and_local_approval_counts() -> None:
    transport = FakeTransport()
    fixtures = _fixtures()
    for case_id, expected in (("P01", 2), ("M01", 1), ("A09", 0)):
        result = run_case(
            case=_case(case_id),
            fixture_manifest=fixtures,
            dependency_context=_context(),
            transport=transport,
        )
        assert result["checkpoint_status"] == "complete"
        assert sum(1 for seen, _kind in transport.approvals if seen == case_id) == expected


def test_incremental_runner_executes_changed_union_fixed_smoke_only() -> None:
    transport = FakeTransport()
    report = run_case_matrix(
        catalog=CATALOG,
        fixture_manifest=_fixtures(),
        dependency_context=_context(),
        transport=transport,
        mode="incremental",
        changed_tags={"generated_ui"},
        allow_paid=True,
        max_parallel=2,
    )
    expected = set(CATALOG["fixed_smoke_ids"]) | {
        case["case_id"]
        for case in CATALOG["cases"]
        if "generated_ui" in case["coverage_tags"]
    }
    assert set(report["selected_case_ids"]) == expected
    assert set(transport.created) == expected
    assert {item["case_id"] for item in report["cases"]} == expected


def test_same_run_checkpoint_resume_does_not_repeat_completed_paid_jobs() -> None:
    first_transport = FakeTransport()
    first = run_case_matrix(
        catalog=CATALOG,
        fixture_manifest=_fixtures(),
        dependency_context=_context(),
        transport=first_transport,
        mode="incremental",
        changed_tags=set(),
        allow_paid=True,
    )
    resumed_transport = FakeTransport()
    resumed = run_case_matrix(
        catalog=CATALOG,
        fixture_manifest=_fixtures(),
        dependency_context=_context(),
        transport=resumed_transport,
        mode="incremental",
        changed_tags=set(),
        allow_paid=True,
        checkpoint=first,
    )
    assert resumed_transport.created == []
    assert resumed["cases"] == first["cases"]


def test_immutable_full_matrix_requires_explicit_paid_permission_and_digest() -> None:
    with pytest.raises(MatrixRunError, match="paid validation permission"):
        run_case_matrix(
            catalog=CATALOG,
            fixture_manifest=_fixtures(),
            dependency_context=_context(),
            transport=FakeTransport(),
            mode="immutable_release",
            changed_tags=set(),
            allow_paid=False,
        )
    bad_context = _context()
    bad_context["bundle_sha256"] = "mutable"
    with pytest.raises(MatrixRunError, match="immutable bundle"):
        run_case_matrix(
            catalog=CATALOG,
            fixture_manifest=_fixtures(),
            dependency_context=bad_context,
            transport=FakeTransport(),
            mode="immutable_release",
            changed_tags=set(),
            allow_paid=True,
        )


def test_hard_gate_failure_stops_matrix_without_claiming_pass() -> None:
    transport = FakeTransport(hard_failure_case="P01")
    with pytest.raises(MatrixRunError, match="hard gate"):
        run_case_matrix(
            catalog=CATALOG,
            fixture_manifest=_fixtures(),
            dependency_context=_context(),
            transport=transport,
            mode="incremental",
            changed_tags=set(),
            allow_paid=True,
            max_parallel=1,
        )


def test_checkpoint_sink_receives_each_completed_case_before_fail_fast() -> None:
    snapshots: list[dict[str, Any]] = []
    with pytest.raises(MatrixRunError, match="hard gate"):
        run_case_matrix(
            catalog=CATALOG,
            fixture_manifest=_fixtures(),
            dependency_context=_context(),
            transport=FakeTransport(hard_failure_case="P01"),
            mode="incremental",
            changed_tags=set(),
            allow_paid=True,
            max_parallel=1,
            checkpoint_sink=lambda payload: snapshots.append(payload),
        )
    assert snapshots
    assert snapshots[0]["cases"][0]["case_id"] == "P01"
    assert snapshots[0]["cases"][0]["checkpoint_status"] == "complete"


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_http_transport_keeps_job_and_evaluator_credentials_separate() -> None:
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout))
        if request.full_url.endswith("/evaluate"):
            return _Response({"total_score": 90})
        return _Response({"job_id": "job-1"})

    transport = HttpMatrixTransport(
        api_base_url="https://jobs.internal",
        evaluator_url="https://qc.internal/evaluate",
        evaluator_token="qc-secret",
        opener=opener,
    )
    transport.job_request("GET", "/api/v1/jobs/job-1", token="job-capability")
    transport.evaluate(
        case=_case("P01"),
        job_id="job-1",
        final_ref={"object_key": "final/job-1/result.mp4", "sha256": "f" * 64},
        dependency_context=_context(),
    )
    job_request, evaluator_request = requests[0][0], requests[1][0]
    assert job_request.headers["Authorization"] == "Bearer job-capability"
    assert evaluator_request.headers["Authorization"] == "Bearer qc-secret"
    assert "job-capability" not in evaluator_request.data.decode("utf-8")


def test_runner_cli_is_available_without_importing_local_skills() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "validation" / "tools" / "run_case_matrix.py"),
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "--fixture-manifest" in completed.stdout
    assert "--evaluator-url" in completed.stdout
    assert ".codex" not in completed.stdout.casefold()


def test_matrix_runner_is_release_only_and_excluded_from_runtime_manifest() -> None:
    manifest = json.loads(
        (ROOT / "references" / "bundle_manifest.json").read_text(encoding="utf-8")
    )
    runtime = {item["path"] for item in manifest["runtime_files"]}
    release = {item["path"] for item in manifest["release_tools"]}
    path = "validation/tools/run_case_matrix.py"
    assert path in release
    assert path not in runtime


def test_quality_contract_documents_runner_paid_and_checkpoint_gates() -> None:
    contract = (ROOT / "references" / "quality-activation-contract.md").read_text(
        encoding="utf-8"
    )
    assert "run_case_matrix.py" in contract
    assert "USFR_VALIDATION_ALLOW_PAID" in contract
    assert "checkpoint" in contract
