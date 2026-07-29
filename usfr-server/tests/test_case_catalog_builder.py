from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from validation.tools.build_case_catalog import (
    CatalogBuildError,
    build_published_catalog,
    load_publisher,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _catalog() -> dict[str, Any]:
    return {
        "schema_version": "usfr-validation-catalog/v1",
        "fixed_smoke_ids": ["P01", "P02"],
        "cases": [
            {
                "case_id": "P01",
                "category": "physical_product",
                "presentation": "unboxing",
                "route": "route_2",
                "output_language": "en",
                "source_fixture": {"asset_id": "fixtures/shared/source.mp4", "sha256": "1" * 64},
                "replacement_fixtures": [
                    {"slot": "new_product_image", "asset_id": "fixtures/p01/product.png", "sha256": "2" * 64}
                ],
                "toolchain_sha256": "3" * 64,
                "fixture_fingerprint": "4" * 64,
                "coverage_tags": ["physical_product", "unboxing"],
                "expected": {"approval_count": 2, "generated_regions": 1, "ui_route": "source_ui_keep", "tail_route": "omit_source_end_card", "hard_gates": ["product_identity"]},
            },
            {
                "case_id": "P02",
                "category": "physical_product",
                "presentation": "shared source",
                "route": "route_1",
                "output_language": "ja",
                "source_fixture": {"asset_id": "fixtures/shared/source-copy.mp4", "sha256": "5" * 64},
                "replacement_fixtures": [
                    {"slot": "app_store_url", "asset_id": "https://play.google.com/store/apps/details?id=example.app", "sha256": "6" * 64}
                ],
                "toolchain_sha256": "7" * 64,
                "fixture_fingerprint": "8" * 64,
                "coverage_tags": ["physical_product", "shared"],
                "expected": {"approval_count": 1, "generated_regions": 1, "ui_route": "source_ui_keep", "tail_route": "omit_source_end_card", "hard_gates": ["timeline_exact"]},
            },
        ],
    }


class Publisher:
    def __init__(self, *, local_key: bool = False, bad_sha: bool = False) -> None:
        self.local_key = local_key
        self.bad_sha = bad_sha
        self.calls: list[dict[str, Any]] = []

    def publish(self, **request: Any) -> dict[str, Any]:
        self.calls.append(request)
        key = (
            "C:/validation/result.mp4"
            if self.local_key
            else request["object_key"]
        )
        return {
            "object_key": key,
            "sha256": "0" * 64 if self.bad_sha else request["sha256"],
            "size_bytes": request["size_bytes"],
            "content_type": request["content_type"],
            "duration_seconds": request.get("duration_seconds"),
            "status": "completed",
            "verified": True,
            "receipt_sha256": "9" * 64,
        }


def _probe(_path: Path) -> dict[str, Any]:
    return {"duration_seconds": 12.5, "width": 720, "height": 1280, "fps": 30.0}


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "private-input"
    (root / "fixtures/shared").mkdir(parents=True)
    (root / "fixtures/p01").mkdir(parents=True)
    video = b"same-video-bytes"
    (root / "fixtures/shared/source.mp4").write_bytes(video)
    (root / "fixtures/shared/source-copy.mp4").write_bytes(video)
    (root / "fixtures/p01/product.png").write_bytes(b"png-bytes")
    return root


def test_builder_hashes_probes_publishes_and_deduplicates_bytes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    publisher = Publisher()
    catalog, fixtures = build_published_catalog(
        catalog=_catalog(),
        input_roots=[root],
        publisher=publisher,
        probe_video=_probe,
    )
    assert len(publisher.calls) == 2
    first, second = catalog["cases"]
    assert first["source_fixture"]["sha256"] == _sha(b"same-video-bytes")
    assert first["source_fixture"]["asset_id"] == second["source_fixture"]["asset_id"]
    assert first["fixture_fingerprint"] != "4" * 64
    assert second["replacement_fixtures"][0]["sha256"] == _sha(
        second["replacement_fixtures"][0]["asset_id"].encode("utf-8")
    )
    asset = fixtures["assets"][first["source_fixture"]["asset_id"]]
    assert asset["duration_seconds"] == 12.5
    assert asset["content_type"] == "video/mp4"
    encoded = json.dumps({"catalog": catalog, "fixtures": fixtures})
    assert str(root) not in encoded
    assert "fixtures/shared/source.mp4" not in encoded


def test_builder_rejects_video_over_30_seconds(tmp_path: Path) -> None:
    with pytest.raises(CatalogBuildError, match="30 seconds"):
        build_published_catalog(
            catalog=_catalog(),
            input_roots=[_root(tmp_path)],
            publisher=Publisher(),
            probe_video=lambda _path: {"duration_seconds": 30.001},
        )


def test_builder_rejects_missing_fixture(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "fixtures/p01/product.png").unlink()
    with pytest.raises(CatalogBuildError, match="not found"):
        build_published_catalog(
            catalog=_catalog(), input_roots=[root], publisher=Publisher(), probe_video=_probe
        )


@pytest.mark.parametrize("publisher", (Publisher(local_key=True), Publisher(bad_sha=True)))
def test_builder_rejects_untrusted_publisher_receipt(
    tmp_path: Path, publisher: Publisher
) -> None:
    with pytest.raises(CatalogBuildError, match="publisher receipt"):
        build_published_catalog(
            catalog=_catalog(),
            input_roots=[_root(tmp_path)],
            publisher=publisher,
            probe_video=_probe,
        )


def test_builder_rejects_path_escape_from_fixture_root(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["cases"][0]["source_fixture"]["asset_id"] = "../outside.mp4"
    with pytest.raises(CatalogBuildError, match="relative fixture"):
        build_published_catalog(
            catalog=catalog,
            input_roots=[_root(tmp_path)],
            publisher=Publisher(),
            probe_video=_probe,
        )


@pytest.mark.parametrize(
    "spec",
    ("C:/private/publisher.py:build", "../publisher:build", ".codex.skills:build"),
)
def test_publisher_factory_rejects_workstation_or_path_specs(spec: str) -> None:
    with pytest.raises(CatalogBuildError, match="packaged module:function"):
        load_publisher(spec)


def test_builder_cli_and_release_manifest_are_available() -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "validation" / "tools" / "build_case_catalog.py"
    completed = subprocess.run(
        [sys.executable, "-B", str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "--publisher-factory" in completed.stdout
    manifest = json.loads(
        (root / "references" / "bundle_manifest.json").read_text(encoding="utf-8")
    )
    runtime = {item["path"] for item in manifest["runtime_files"]}
    release = {item["path"] for item in manifest["release_tools"]}
    path = "validation/tools/build_case_catalog.py"
    assert path in release
    assert path not in runtime


def test_quality_contract_documents_private_fixture_builder() -> None:
    root = Path(__file__).resolve().parents[1]
    contract = (root / "references" / "quality-activation-contract.md").read_text(
        encoding="utf-8"
    )
    assert "build_case_catalog.py" in contract
    assert "private object" in contract
    assert "30 seconds" in contract
