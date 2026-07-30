"""Drive selected USFR validation cases through the existing Jobs API."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from scripts.validation_catalog import select_cases
    from validation.tools.validate_case_results import case_dependency_fingerprint
except ModuleNotFoundError:  # Direct execution of this packaged release tool.
    package_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(package_root))
    from scripts.validation_catalog import select_cases
    from validation.tools.validate_case_results import case_dependency_fingerprint


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTEXT_FIELDS = (
    "bundle_sha256",
    "capability_sha256",
    "model_sha256",
    "provider_sha256",
    "prompt_compiler_sha256",
)
_UPLOAD_FIELDS = {
    "object_key",
    "object_uri",
    "uri",
    "sha256",
    "size_bytes",
    "content_type",
    "duration_seconds",
    "etag",
    "status",
}


class MatrixRunError(RuntimeError):
    pass


class MatrixTransport(Protocol):
    def job_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> dict[str, Any]: ...

    def evaluate(
        self,
        *,
        case: dict[str, Any],
        job_id: str,
        final_ref: dict[str, Any],
        dependency_context: dict[str, str],
    ) -> dict[str, Any]: ...


class HttpMatrixTransport:
    """Private HTTPS transport for the existing Jobs API and QC evaluator."""

    def __init__(
        self,
        *,
        api_base_url: str,
        evaluator_url: str,
        evaluator_token: str,
        timeout_seconds: float = 60.0,
        opener: Any = urlopen,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.evaluator_url = evaluator_url
        self.evaluator_token = evaluator_token
        self.timeout_seconds = timeout_seconds
        self.opener = opener
        if not self.api_base_url.startswith(("http://", "https://")):
            raise MatrixRunError("Jobs API base URL must be HTTP(S)")
        if not self.evaluator_url.startswith("https://"):
            raise MatrixRunError("validation evaluator URL must use private HTTPS")
        if not evaluator_token:
            raise MatrixRunError("validation evaluator token is required")

    def _json_request(
        self,
        *,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None,
        bearer: str | None,
    ) -> dict[str, Any]:
        data = _canonical(payload) if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MatrixRunError(f"validation HTTP request failed: {method} {url}") from exc
        if not isinstance(decoded, dict):
            raise MatrixRunError("validation HTTP response must be a JSON object")
        return decoded

    def job_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/api/v1/jobs"):
            raise MatrixRunError("matrix runner may call only the Jobs API")
        return self._json_request(
            method=method,
            url=f"{self.api_base_url}{path}",
            payload=payload,
            bearer=token,
        )

    def evaluate(
        self,
        *,
        case: dict[str, Any],
        job_id: str,
        final_ref: dict[str, Any],
        dependency_context: dict[str, str],
    ) -> dict[str, Any]:
        return self._json_request(
            method="POST",
            url=self.evaluator_url,
            payload={
                "schema_version": "usfr-validation-evaluation-request/v1",
                "case": case,
                "job_id": job_id,
                "final_ref": final_ref,
                "dependency_context": dependency_context,
            },
            bearer=self.evaluator_token,
        )

def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _validate_context(value: Mapping[str, Any]) -> dict[str, str]:
    context: dict[str, str] = {}
    for field in _CONTEXT_FIELDS:
        digest = value.get(field)
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise MatrixRunError(f"{field} must identify an immutable bundle dependency")
        context[field] = digest
    return context


def _fixture_assets(fixture_manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    if (
        fixture_manifest.get("schema_version") != "usfr-validation-fixtures/v1"
        or not isinstance(fixture_manifest.get("assets"), Mapping)
    ):
        raise MatrixRunError("validation fixture manifest is invalid")
    return fixture_manifest["assets"]


def _completion(
    record: Mapping[str, Any], assets: Mapping[str, Any], *, case_id: str
) -> dict[str, Any]:
    asset_id = record.get("asset_id")
    asset = assets.get(asset_id)
    if not isinstance(asset, Mapping):
        raise MatrixRunError(f"{case_id}: fixture asset is not published: {asset_id}")
    if asset.get("verified") is not True or not isinstance(
        asset.get("receipt_sha256"), str
    ):
        raise MatrixRunError(f"{case_id}: fixture asset has no verified receipt")
    if asset.get("sha256") != record.get("sha256"):
        raise MatrixRunError(f"{case_id}: fixture asset SHA does not match catalog")
    return {key: asset[key] for key in _UPLOAD_FIELDS if key in asset}


def _slots(
    case: Mapping[str, Any], fixture_manifest: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id = str(case.get("case_id"))
    assets = _fixture_assets(fixture_manifest)
    source = case.get("source_fixture")
    if not isinstance(source, Mapping):
        raise MatrixRunError(f"{case_id}: source fixture is invalid")
    slots: dict[str, Any] = {
        "source_video": _completion(source, assets, case_id=case_id)
    }
    receipt_inputs: list[dict[str, Any]] = [dict(assets[source["asset_id"]])]
    for replacement in case.get("replacement_fixtures") or []:
        if not isinstance(replacement, Mapping):
            raise MatrixRunError(f"{case_id}: replacement fixture is invalid")
        slot = replacement.get("slot")
        asset_id = replacement.get("asset_id")
        if slot == "output_language":
            continue
        if slot == "app_store_url":
            slots[slot] = {"url": asset_id, "sha256": replacement.get("sha256")}
            continue
        completion = _completion(replacement, assets, case_id=case_id)
        if slot in {"new_product_image", "new_model_image", "ui_screenshot"}:
            existing = slots.get(slot)
            if existing is None:
                slots[slot] = [completion]
            else:
                existing.append(completion)
        else:
            slots[str(slot)] = completion
        receipt_inputs.append(dict(assets[asset_id]))
    receipt = {
        "verified": True,
        "receipt_sha256": hashlib.sha256(_canonical(receipt_inputs)).hexdigest(),
        "source_sha256": source.get("sha256"),
        "replacement_sha256": [
            item.get("sha256") for item in case.get("replacement_fixtures") or []
        ],
    }
    return slots, receipt


def _latest_revision(
    *,
    transport: MatrixTransport,
    path: str,
    token: str,
    deadline: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        payload = transport.job_request("GET", path, token=token)
        revisions = payload.get("revisions") if isinstance(payload, Mapping) else None
        if isinstance(revisions, list) and revisions:
            rows = [row for row in revisions if isinstance(row, Mapping)]
            if rows:
                return dict(max(rows, key=lambda row: int(row.get("revision", 0))))
        time.sleep(poll_interval_seconds)
    raise MatrixRunError(f"timed out waiting for review artifact: {path}")


def _approve(
    *,
    transport: MatrixTransport,
    job_id: str,
    kind: str,
    version: int,
    token: str,
    deadline: float,
    poll_interval_seconds: float,
) -> int:
    collection = "scripts" if kind == "script" else "storyboards"
    revision = _latest_revision(
        transport=transport,
        path=f"/api/v1/jobs/{job_id}/{collection}",
        token=token,
        deadline=deadline,
        poll_interval_seconds=poll_interval_seconds,
    )
    number = revision.get("revision")
    digest = revision.get("sha256")
    if not isinstance(number, int) or not isinstance(digest, str):
        raise MatrixRunError(f"{job_id}: {kind} revision is invalid")
    snapshot = transport.job_request(
        "POST",
        f"/api/v1/jobs/{job_id}/{collection}/{number}/approve",
        payload={"expected_version": version, "expected_sha256": digest},
        token=token,
    )
    next_version = snapshot.get("version") if isinstance(snapshot, Mapping) else None
    if not isinstance(next_version, int):
        raise MatrixRunError(f"{job_id}: {kind} approval returned no version")
    return next_version


def run_case(
    *,
    case: Mapping[str, Any],
    fixture_manifest: Mapping[str, Any],
    dependency_context: Mapping[str, Any],
    transport: MatrixTransport,
    timeout_seconds: float = 1800.0,
    poll_interval_seconds: float = 0.25,
) -> dict[str, Any]:
    context = _validate_context(dependency_context)
    case_dict = dict(case)
    case_id = str(case_dict.get("case_id"))
    slots, fixture_receipt = _slots(case_dict, fixture_manifest)
    started = time.monotonic()
    created = transport.job_request(
        "POST",
        "/api/v1/jobs",
        payload={"slots": slots, "output_language": case_dict.get("output_language")},
    )
    job_id = created.get("job_id") if isinstance(created, Mapping) else None
    token = created.get("capability_token") if isinstance(created, Mapping) else None
    version = created.get("version") if isinstance(created, Mapping) else None
    if not isinstance(job_id, str) or not isinstance(token, str) or not isinstance(version, int):
        raise MatrixRunError(f"{case_id}: create job response is invalid")
    snapshot = transport.job_request(
        "POST",
        f"/api/v1/jobs/{job_id}/start",
        payload={"expected_version": version},
        token=token,
    )
    version = snapshot.get("version") if isinstance(snapshot, Mapping) else None
    if not isinstance(version, int):
        raise MatrixRunError(f"{case_id}: start response is invalid")
    deadline = started + timeout_seconds
    approvals = int(case_dict.get("expected", {}).get("approval_count", -1))
    if approvals == 2:
        version = _approve(
            transport=transport,
            job_id=job_id,
            kind="script",
            version=version,
            token=token,
            deadline=deadline,
            poll_interval_seconds=poll_interval_seconds,
        )
    if approvals in {1, 2}:
        version = _approve(
            transport=transport,
            job_id=job_id,
            kind="storyboard",
            version=version,
            token=token,
            deadline=deadline,
            poll_interval_seconds=poll_interval_seconds,
        )
    if approvals not in {0, 1, 2}:
        raise MatrixRunError(f"{case_id}: approval count is invalid")

    final_ref: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        result_payload = transport.job_request(
            "GET", f"/api/v1/jobs/{job_id}/result", token=token
        )
        candidate = result_payload.get("result") if isinstance(result_payload, Mapping) else None
        if isinstance(candidate, Mapping) and candidate:
            final_ref = dict(candidate)
            break
        snapshot = transport.job_request(
            "GET", f"/api/v1/jobs/{job_id}", token=token
        )
        if snapshot.get("state") == "FAILED":
            raise MatrixRunError(f"{case_id}: job failed before final result")
        time.sleep(poll_interval_seconds)
    if final_ref is None:
        raise MatrixRunError(f"{case_id}: timed out waiting for final result")
    final_sha = final_ref.get("sha256")
    if not isinstance(final_sha, str) or _SHA256.fullmatch(final_sha) is None:
        raise MatrixRunError(f"{case_id}: final result has no MP4 SHA-256")
    evaluation = transport.evaluate(
        case=case_dict,
        job_id=job_id,
        final_ref=final_ref,
        dependency_context=context,
    )
    if not isinstance(evaluation, Mapping):
        raise MatrixRunError(f"{case_id}: evaluator response is invalid")
    elapsed = max(0.001, time.monotonic() - started)
    return {
        "case_id": case_id,
        "execution_status": "executed",
        "dependency_fingerprint": case_dependency_fingerprint(case_dict, context),
        "fixture_receipt": fixture_receipt,
        "final_sha256": final_sha,
        **dict(evaluation),
        "active_seconds": float(evaluation.get("active_seconds", elapsed)),
        "provider_seconds": float(evaluation.get("provider_seconds", 0.0)),
        "approval_wait_seconds": 0.0,
        "checkpoint_status": "complete",
    }


def run_case_matrix(
    *,
    catalog: Mapping[str, Any],
    fixture_manifest: Mapping[str, Any],
    dependency_context: Mapping[str, Any],
    transport: MatrixTransport,
    mode: str,
    changed_tags: set[str],
    allow_paid: bool,
    max_parallel: int = 1,
    checkpoint: Mapping[str, Any] | None = None,
    checkpoint_sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    context = _validate_context(dependency_context)
    cases = catalog.get("cases")
    smoke = catalog.get("fixed_smoke_ids")
    if not isinstance(cases, list) or not isinstance(smoke, list):
        raise MatrixRunError("validation catalog is invalid")
    if isinstance(max_parallel, bool) or not isinstance(max_parallel, int) or not 1 <= max_parallel <= 8:
        raise MatrixRunError("max_parallel must be between 1 and 8")
    if mode == "immutable_release":
        if not allow_paid:
            raise MatrixRunError("immutable release requires explicit paid validation permission")
        selected = select_cases(
            cases,
            smoke_ids=set(smoke),
            full=True,
            immutable_bundle_sha256=context["bundle_sha256"],
        )
    elif mode == "incremental":
        selected = select_cases(
            cases,
            smoke_ids=set(smoke),
            changed_tags=set(changed_tags),
        )
    else:
        raise MatrixRunError("mode must be incremental or immutable_release")
    if any(int(case.get("expected", {}).get("generated_regions", 0)) > 0 for case in selected) and not allow_paid:
        raise MatrixRunError("selected cases require explicit paid validation permission")
    selected_ids = [case["case_id"] for case in selected]
    matrix_run_sha256 = hashlib.sha256(
        _canonical(
            {
                "mode": mode,
                "selected_case_ids": selected_ids,
                "dependency_context": context,
            }
        )
    ).hexdigest()
    resumed: dict[str, dict[str, Any]] = {}
    if isinstance(checkpoint, Mapping) and checkpoint.get("matrix_run_sha256") == matrix_run_sha256:
        for result in checkpoint.get("cases") or []:
            if (
                isinstance(result, Mapping)
                and result.get("case_id") in selected_ids
                and result.get("checkpoint_status") == "complete"
            ):
                case = next(item for item in selected if item["case_id"] == result["case_id"])
                if result.get("dependency_fingerprint") == case_dependency_fingerprint(case, context):
                    resumed[result["case_id"]] = dict(result)
    pending = [case for case in selected if case["case_id"] not in resumed]
    completed = dict(resumed)

    def snapshot() -> dict[str, Any]:
        return {
            "schema_version": "usfr-case-matrix-results/v1",
            "mode": mode,
            "matrix_run_sha256": matrix_run_sha256,
            "dependency_context": context,
            "selected_case_ids": selected_ids,
            "cases": [
                completed[case_id] for case_id in selected_ids if case_id in completed
            ],
        }

    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = {
            executor.submit(
                run_case,
                case=case,
                fixture_manifest=fixture_manifest,
                dependency_context=context,
                transport=transport,
            ): case["case_id"]
            for case in pending
        }
        for future in as_completed(futures):
            case_id = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                for other in futures:
                    other.cancel()
                if isinstance(exc, MatrixRunError):
                    raise
                raise MatrixRunError(f"{case_id}: matrix execution failed") from exc
            completed[case_id] = result
            if checkpoint_sink is not None:
                checkpoint_sink(snapshot())
            if result.get("hard_failures"):
                for other in futures:
                    other.cancel()
                raise MatrixRunError(f"{case_id}: hard gate failure stopped the matrix")
    return snapshot()


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


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run selected USFR validation cases through the existing Jobs API."
    )
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--fixture-manifest", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--evaluator-url", required=True)
    parser.add_argument("--mode", choices=("incremental", "immutable_release"), default="incremental")
    parser.add_argument("--changed-tag", action="append", default=[])
    parser.add_argument("--max-parallel", type=int, default=2)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    fixtures = json.loads(args.fixture_manifest.read_text(encoding="utf-8"))
    context = json.loads(args.context.read_text(encoding="utf-8"))
    checkpoint_path = args.checkpoint or args.output.with_name(
        f"{args.output.name}.checkpoint.json"
    )
    checkpoint = None
    if checkpoint_path.is_file():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    transport = HttpMatrixTransport(
        api_base_url=args.api_base_url,
        evaluator_url=args.evaluator_url,
        evaluator_token=os.getenv("USFR_VALIDATION_EVALUATOR_TOKEN", ""),
    )
    report = run_case_matrix(
        catalog=catalog,
        fixture_manifest=fixtures,
        dependency_context=context,
        transport=transport,
        mode=args.mode,
        changed_tags=set(args.changed_tag),
        allow_paid=_truthy(os.getenv("USFR_VALIDATION_ALLOW_PAID")),
        max_parallel=args.max_parallel,
        checkpoint=checkpoint,
        checkpoint_sink=lambda payload: _write_json_atomic(checkpoint_path, payload),
    )
    _write_json_atomic(args.output, report)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
