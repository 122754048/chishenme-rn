from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))
import seedance_submit  # noqa: E402
from seedance_submit import (  # noqa: E402
    PayloadError,
    _load_seedance20_snapshot,
    build_payload,
    request_sha256,
    validate_audit_artifact,
)


REQUIRED_DIGESTS = (
    "approved_storyboard_sha256",
    "source_fidelity_contract_sha256",
    "timeline_regions_sha256",
    "character_lock_sha256",
    "product_truth_sha256",
    "selling_point_mapping_sha256",
    "audio_contract_sha256",
    "continuity_manifest_sha256",
)


def base_artifact(payload: dict, script_digest: str) -> dict:
    prompt = seedance_submit._payload_prompt(payload)
    contract_pointer = "/contracts/source_fidelity_contract.json#/cuts/0"
    return {
        "auditor": "seedance-20",
        "status": "passed",
        "request_sha256": request_sha256(payload),
        "approved_script_sha256": script_digest,
        "compiled_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "compiler": {
            "skill": "seedance-20",
            "version": "6.6.0",
            "skill_sha256": "a" * 64,
            "professional_gate": True,
            "capability_check": True,
            "allocation_check": True,
            "reference_role_check": True,
            "directing_coherence_check": True,
            "anti_slop_check": True,
        },
        "contract_digests": {name: "b" * 64 for name in REQUIRED_DIGESTS},
        "factor_coverage_ledger": [
            {
                "factor_id": "cut:C01",
                "source_pointer": "/cuts/0",
                "carrier": "prompt_carried",
                "status": "passed",
                "prompt_span": {"start": 0, "end": 4},
                "payload_path": "$.content[0].text",
                "contract_pointer": contract_pointer,
            }
        ],
        "contract_index": {
            contract_pointer: "source_fidelity_contract_sha256",
        },
        "route_contract": {"excluded_factor_ids": []},
        "ambiguities": [],
        "unresolved_placeholders": [],
        "checks": {name: True for name in seedance_submit.REQUIRED_AUDIT_CHECKS},
    }


def write_runtime_fixtures(
    root: Path,
    artifact: dict,
    *,
    script_digest: str = "0" * 64,
    factor_ids: tuple[str, ...] = ("cut:C01",),
    contract_digests: dict[str, str] | None = None,
    required_checks: tuple[str, ...] | None = None,
    skill_version: str = "6.6.0",
    skill_name: str = "seedance-20",
) -> tuple[Path, Path]:
    digests = contract_digests or {name: "b" * 64 for name in REQUIRED_DIGESTS}
    checks = required_checks or tuple(seedance_submit.REQUIRED_AUDIT_CHECKS)
    contract = {
        "approved_script_sha256": script_digest,
        "contract_digests": digests,
        "required_audit_checks": list(checks),
        "required_factor_ids": list(factor_ids),
    }
    contract_path = root / "seedance_input_contract.json"
    contract_raw = json.dumps(
        contract, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    contract_path.write_bytes(contract_raw)
    artifact["seedance_input_contract_sha256"] = hashlib.sha256(contract_raw).hexdigest()

    skill_path = root / "seedance-20" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_raw = (
        "---\n"
        f"name: {skill_name}\n"
        "metadata:\n"
        f"  version: \"{skill_version}\"\n"
        "---\n"
    ).encode("utf-8")
    skill_path.write_bytes(skill_raw)
    artifact["compiler"]["skill"] = skill_name
    artifact["compiler"]["version"] = skill_version
    artifact["compiler"]["skill_sha256"] = hashlib.sha256(skill_raw).hexdigest()
    return contract_path, skill_path


def validate_artifact(
    artifact: dict,
    payload: dict | None = None,
    *,
    input_contract_path: Path | None = None,
    skill_file_path: Path | None = None,
) -> None:
    payload = payload or build_payload("test", 5, "9:16", [], [], provider="youdao")
    script_digest = "0" * 64
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.json"
        path.write_text(json.dumps(artifact), encoding="utf-8")
        kwargs = {}
        if input_contract_path is not None:
            kwargs["seedance_input_contract_path"] = input_contract_path
        if skill_file_path is not None:
            kwargs["seedance20_skill_file"] = skill_file_path
        validate_audit_artifact(
            payload,
            path,
            request_sha256(payload),
            script_digest,
            **kwargs,
        )


class SeedanceIntegrityGateV2Test(unittest.TestCase):
    def test_high_fidelity_compiler_requires_prompt_and_antislop_modules(self):
        payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
        artifact = base_artifact(payload, "0" * 64)
        artifact["compiler"].update(
            {
                "contract": "seedance20-prompt-compiler/v1",
                "profile": "high_fidelity_hybrid_v1",
                "loaded_modules": ["seedance-20"],
            }
        )
        with self.assertRaisesRegex(PayloadError, "seedance-prompt.*seedance-antislop"):
            validate_artifact(artifact, payload)

        artifact["compiler"]["loaded_modules"] = [
            "seedance-20",
            "seedance-prompt",
            "seedance-antislop",
        ]
        validate_artifact(artifact, payload)

    def setUp(self):
        self.payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
        self.script_digest = "0" * 64

    def test_rejects_missing_seedance20_compiler_provenance(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact.pop("compiler")
        with self.assertRaisesRegex(PayloadError, "seedance-20 compiler provenance"):
            validate_artifact(artifact)

    def test_rejects_missing_contract_digest(self):
        artifact = base_artifact(self.payload, self.script_digest)
        del artifact["contract_digests"]["product_truth_sha256"]
        with self.assertRaisesRegex(PayloadError, "contract digest"):
            validate_artifact(artifact)

    def test_rejects_unassigned_factor(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact["factor_coverage_ledger"][0]["carrier"] = "unassigned"
        with self.assertRaisesRegex(PayloadError, "factor coverage"):
            validate_artifact(artifact)

    def test_rejects_unresolved_placeholders(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact["unresolved_placeholders"] = ["{{VOICEOVER}}"]
        with self.assertRaisesRegex(PayloadError, "unresolved placeholders"):
            validate_artifact(artifact)

    def test_rejects_malformed_compiler_provenance(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact["compiler"]["skill_sha256"] = "A" * 64
        with self.assertRaisesRegex(PayloadError, "compiler provenance"):
            validate_artifact(artifact)

    def test_rejects_invalid_contract_digest_format(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact["contract_digests"]["audio_contract_sha256"] = "c" * 63
        with self.assertRaisesRegex(PayloadError, "contract digest"):
            validate_artifact(artifact)

    def test_rejects_empty_factor_coverage_ledger(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact["factor_coverage_ledger"] = []
        with self.assertRaisesRegex(PayloadError, "factor coverage"):
            validate_artifact(artifact)

    def test_rejects_failed_factor(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact["factor_coverage_ledger"][0]["status"] = "failed"
        with self.assertRaisesRegex(PayloadError, "factor coverage"):
            validate_artifact(artifact)

    def test_rejects_invalid_prompt_span(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact["factor_coverage_ledger"][0]["prompt_span"] = {"start": 1, "end": 99}
        with self.assertRaisesRegex(PayloadError, "factor coverage"):
            validate_artifact(artifact)

    def test_rejects_missing_factor_payload_or_contract_reference(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact["factor_coverage_ledger"][0].pop("contract_pointer")
        with self.assertRaisesRegex(PayloadError, "factor coverage"):
            validate_artifact(artifact)

    def test_requires_explicit_empty_ambiguity_list(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact.pop("ambiguities")
        with self.assertRaisesRegex(PayloadError, "zero ambiguity"):
            validate_artifact(artifact)

    def test_requires_explicit_empty_placeholder_list(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact.pop("unresolved_placeholders")
        with self.assertRaisesRegex(PayloadError, "unresolved placeholders"):
            validate_artifact(artifact)

    def test_scans_compiled_prompt_for_placeholders(self):
        payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
        payload["content"][0]["text"] = "Use {{VOICEOVER}} now"
        artifact = base_artifact(payload, self.script_digest)
        with self.assertRaisesRegex(PayloadError, "unresolved placeholders"):
            validate_artifact(artifact, payload)

    def test_rejects_route_leakage_in_prompt_or_payload(self):
        payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
        payload["content"][0]["text"] = "splice opaque_ui_demo"
        artifact = base_artifact(payload, self.script_digest)
        with self.assertRaisesRegex(PayloadError, "route leakage"):
            validate_artifact(artifact, payload)

    def test_rejects_route_leakage_hidden_in_nested_payload_keys(self):
        payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
        payload["content"][0]["renderedMedia"] = {
            "mediaSha256": "a" * 64,
            "qcReport": {"passed": True},
        }
        artifact = base_artifact(payload, self.script_digest)
        with self.assertRaisesRegex(PayloadError, "route leakage"):
            validate_artifact(artifact, payload)

    def test_rejects_route_leakage_naming_variants(self):
        for leaked_marker in (
            "ui_demo_video",
            "ui_operation_video",
            "ui-operation-video",
            "ui operation video",
            "uiDemoVideo",
            "ui-demo-video",
            "ui demo video",
            "tail_card_video",
            "appTailCardVideo",
            "app-tail-card-video",
            "app tail card video",
            "tail_video",
            "tail-video",
            "tail video",
            "source_interval",
            "source-interval",
            "source interval",
            "source_ui_keep",
            "source-ui-keep",
            "source ui keep",
            "source-ui-frames",
            "source ui frames",
            "transitionShell",
            "transition-shell",
            "transition shell",
            "opaque-ui-demo",
            "opaque ui demo",
            "generated-ui-demo",
            "generated ui demo",
            "generatedUiDemo",
            "excluded-app-end-card",
            "excluded app end card",
            "excludedAppEndCard",
            "omit-source-end-card",
            "omit source end card",
            "omitSourceEndCard",
            "excluded-region",
            "excluded region",
            "opaqueAppTailCard",
            "tailCard",
            "renderedMedia",
            "mediaSha256",
            "qcReport",
        ):
            with self.subTest(leaked_marker=leaked_marker):
                payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
                payload["content"][0]["text"] = f"use {leaked_marker}"
                artifact = base_artifact(payload, self.script_digest)
                with self.assertRaisesRegex(PayloadError, "route leakage"):
                    validate_artifact(artifact, payload)

    def test_route_excluded_false_mapping_does_not_authorize_factor(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact["factor_coverage_ledger"][0]["carrier"] = "route_excluded"
        artifact["factor_coverage_ledger"][0].pop("payload_path")
        artifact["route_contract"] = {
            "excluded_factor_ids": {"cut:C01": False}
        }
        with self.assertRaisesRegex(PayloadError, "route_excluded"):
            validate_artifact(artifact)

    def test_route_excluded_true_mapping_authorizes_without_payload_path(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact["factor_coverage_ledger"][0]["carrier"] = "route_excluded"
        artifact["factor_coverage_ledger"][0].pop("payload_path")
        artifact["factor_coverage_ledger"][0].pop("prompt_span")
        artifact["route_contract"] = {
            "excluded_factor_ids": {"cut:C01": True}
        }
        validate_artifact(artifact)

    def test_strict_factory_route_excluded_requires_canonical_direct_mapping(self):
        for route_contract, should_pass in (
            ({"cut:C01": True}, True),
            ({"excluded_factor_ids": {"cut:C01": True}}, False),
            ({"excluded_factor_ids": ["cut:C01"]}, False),
        ):
            with self.subTest(route_contract=route_contract):
                artifact = base_artifact(self.payload, self.script_digest)
                artifact["factor_coverage_ledger"][0]["carrier"] = "route_excluded"
                artifact["factor_coverage_ledger"][0].pop("payload_path")
                artifact["factor_coverage_ledger"][0].pop("prompt_span")
                artifact["route_contract"] = route_contract
                with tempfile.TemporaryDirectory() as tmp:
                    contract_path, skill_path = write_runtime_fixtures(
                        Path(tmp), artifact
                    )
                    if should_pass:
                        validate_artifact(
                            artifact,
                            input_contract_path=contract_path,
                            skill_file_path=skill_path,
                        )
                    else:
                        with self.assertRaisesRegex(PayloadError, "canonical"):
                            validate_artifact(
                                artifact,
                                input_contract_path=contract_path,
                                skill_file_path=skill_path,
                            )

    def test_factor_payload_path_must_resolve_in_exact_payload(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact["factor_coverage_ledger"][0]["payload_path"] = "$.content[9].text"
        with self.assertRaisesRegex(PayloadError, "factor coverage.*payload path"):
            validate_artifact(artifact)

    def test_factor_contract_pointer_must_resolve_in_contract_index(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact["factor_coverage_ledger"][0]["contract_pointer"] = (
            "/contracts/source_fidelity_contract.json#/cuts/99"
        )
        with self.assertRaisesRegex(PayloadError, "factor coverage.*contract pointer"):
            validate_artifact(artifact)

    def test_rejects_incomplete_frozen_factor_coverage(self):
        artifact = base_artifact(self.payload, self.script_digest)
        with tempfile.TemporaryDirectory() as tmp:
            contract_path, skill_path = write_runtime_fixtures(
                Path(tmp), artifact, factor_ids=("cut:C01", "cut:C02")
            )
            with self.assertRaisesRegex(PayloadError, "factor coverage"):
                validate_artifact(
                    artifact,
                    self.payload,
                    input_contract_path=contract_path,
                    skill_file_path=skill_path,
                )

    def test_rejects_extra_factor_not_in_frozen_contract(self):
        artifact = base_artifact(self.payload, self.script_digest)
        extra = dict(artifact["factor_coverage_ledger"][0])
        extra["factor_id"] = "cut:C02"
        artifact["factor_coverage_ledger"].append(extra)
        with tempfile.TemporaryDirectory() as tmp:
            contract_path, skill_path = write_runtime_fixtures(Path(tmp), artifact)
            with self.assertRaisesRegex(PayloadError, "factor coverage"):
                validate_artifact(
                    artifact,
                    self.payload,
                    input_contract_path=contract_path,
                    skill_file_path=skill_path,
                )

    def test_rejects_mutated_frozen_input_contract_bytes(self):
        artifact = base_artifact(self.payload, self.script_digest)
        with tempfile.TemporaryDirectory() as tmp:
            contract_path, skill_path = write_runtime_fixtures(Path(tmp), artifact)
            contract_path.write_bytes(contract_path.read_bytes() + b"\n")
            with self.assertRaisesRegex(PayloadError, "input contract"):
                validate_artifact(
                    artifact,
                    self.payload,
                    input_contract_path=contract_path,
                    skill_file_path=skill_path,
                )

    def test_rejects_non_exact_audit_check_key_set(self):
        artifact = base_artifact(self.payload, self.script_digest)
        artifact["checks"]["unexpected"] = True
        with tempfile.TemporaryDirectory() as tmp:
            contract_path, skill_path = write_runtime_fixtures(Path(tmp), artifact)
            with self.assertRaisesRegex(PayloadError, "audit checks"):
                validate_artifact(
                    artifact,
                    self.payload,
                    input_contract_path=contract_path,
                    skill_file_path=skill_path,
                )

    def test_rejects_mutated_contract_script_digest_or_check_schema(self):
        mutations = (
            {"approved_script_sha256": "1" * 64},
            {"contract_digests": {**{name: "b" * 64 for name in REQUIRED_DIGESTS}, "product_truth_sha256": "c" * 64}},
            {"required_audit_checks": list(seedance_submit.REQUIRED_AUDIT_CHECKS) + ["extra"]},
            {"required_audit_checks": list(reversed(seedance_submit.REQUIRED_AUDIT_CHECKS))},
            {"required_factor_ids": ["cut:C01", "cut:C01"]},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                artifact = base_artifact(self.payload, self.script_digest)
                with tempfile.TemporaryDirectory() as tmp:
                    contract_path, skill_path = write_runtime_fixtures(Path(tmp), artifact)
                    contract = json.loads(contract_path.read_text(encoding="utf-8"))
                    contract.update(mutation)
                    contract_path.write_text(
                        json.dumps(contract, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8",
                    )
                    artifact["seedance_input_contract_sha256"] = hashlib.sha256(
                        contract_path.read_bytes()
                    ).hexdigest()
                    with self.assertRaises(PayloadError):
                        validate_artifact(
                            artifact,
                            self.payload,
                            input_contract_path=contract_path,
                            skill_file_path=skill_path,
                        )

    def test_rejects_forbidden_or_unknown_audited_payload_fields(self):
        for mutation in (
            lambda payload: payload.update({"referenceVideos": []}),
            lambda payload: payload.update({"reference Audios": []}),
            lambda payload: payload.update({"mysteryField": True}),
            lambda payload: payload["content"][0].update({"mysteryNested": True}),
        ):
            with self.subTest(mutation=mutation):
                payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
                mutation(payload)
                artifact = base_artifact(payload, self.script_digest)
                with tempfile.TemporaryDirectory() as tmp:
                    contract_path, skill_path = write_runtime_fixtures(Path(tmp), artifact)
                    with self.assertRaises(PayloadError):
                        validate_artifact(
                            artifact,
                            payload,
                            input_contract_path=contract_path,
                            skill_file_path=skill_path,
                        )

    def test_rejects_non_fixed_audited_payload_parameters(self):
        mutations = (
            ("model", "seedance-2.0-fast"),
            ("resolution", "480p"),
            ("ratio", "16:9"),
            ("generate_audio", False),
            ("watermark", True),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
                payload[field] = value
                artifact = base_artifact(payload, self.script_digest)
                with tempfile.TemporaryDirectory() as tmp:
                    contract_path, skill_path = write_runtime_fixtures(Path(tmp), artifact)
                    with self.assertRaisesRegex(PayloadError, "fixed-B"):
                        validate_artifact(
                            artifact,
                            payload,
                            input_contract_path=contract_path,
                            skill_file_path=skill_path,
                        )

    def test_rejects_missing_or_mismatched_seedance20_snapshot(self):
        artifact = base_artifact(self.payload, self.script_digest)
        with tempfile.TemporaryDirectory() as tmp:
            contract_path, skill_path = write_runtime_fixtures(Path(tmp), artifact)
            skill_path.unlink()
            with self.assertRaisesRegex(PayloadError, "seedance-20"):
                validate_artifact(
                    artifact,
                    self.payload,
                    input_contract_path=contract_path,
                    skill_file_path=skill_path,
                )

    def test_snapshot_requires_delimited_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "SKILL.md"
            path.write_text(
                "body\nname: seedance-20\nmetadata:\n  version: \"6.6.0\"\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PayloadError, "frontmatter"):
                _load_seedance20_snapshot(path)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "SKILL.md"
            path.write_text(
                "---\nname: other\n---\n"
                "body name: seedance-20\nmetadata:\n  version: \"6.6.0\"\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PayloadError, "frontmatter"):
                _load_seedance20_snapshot(path)

        artifact = base_artifact(self.payload, self.script_digest)
        with tempfile.TemporaryDirectory() as tmp:
            contract_path, skill_path = write_runtime_fixtures(Path(tmp), artifact)
            skill_path.write_text(skill_path.read_text(encoding="utf-8") + "changed", encoding="utf-8")
            with self.assertRaisesRegex(PayloadError, "skill snapshot"):
                validate_artifact(
                    artifact,
                    self.payload,
                    input_contract_path=contract_path,
                    skill_file_path=skill_path,
                )


if __name__ == "__main__":
    unittest.main()
