import json
import hashlib
import sys
import tempfile
import threading
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
sys.path.insert(0, str(MODULE))

from config import ConfigurationError, load_settings  # noqa: E402
import seedance_submit as seedance_submit_module  # noqa: E402
from seedance_submit import (  # noqa: E402
    PayloadError,
    SeedanceApiError,
    YoudaoSeedanceClient,
    build_payload,
    prepare_youdao_assets,
    request_sha256,
    poll_delay_for_status,
    require_request_authorization,
    require_approved_request,
)


AUDIT_CONTRACT_DIGESTS = (
    "approved_storyboard_sha256",
    "source_fidelity_contract_sha256",
    "timeline_regions_sha256",
    "character_lock_sha256",
    "product_truth_sha256",
    "selling_point_mapping_sha256",
    "audio_contract_sha256",
    "continuity_manifest_sha256",
)


def complete_audit_artifact(
    payload,
    script_digest,
    *,
    ambiguities=None,
    input_contract_sha256=None,
):
    prompt = seedance_submit_module._payload_prompt(payload)
    contract_pointer = "/contracts/source_fidelity_contract.json#/cuts/0"
    artifact = {
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
        "contract_digests": {name: "b" * 64 for name in AUDIT_CONTRACT_DIGESTS},
        "factor_coverage_ledger": [
            {
                "factor_id": "cut:C01",
                "source_pointer": "/cuts/0",
                "carrier": "prompt_carried",
                "status": "passed",
                "prompt_span": {"start": 0, "end": len(prompt)},
                "payload_path": "$.content[0].text",
                "contract_pointer": contract_pointer,
            }
        ],
        "contract_index": {
            contract_pointer: "source_fidelity_contract_sha256",
        },
        "route_contract": {"excluded_factor_ids": []},
        "ambiguities": [] if ambiguities is None else ambiguities,
        "unresolved_placeholders": [],
        "checks": {name: True for name in seedance_submit_module.REQUIRED_AUDIT_CHECKS},
    }
    if input_contract_sha256 is not None:
        artifact["seedance_input_contract_sha256"] = input_contract_sha256
    return artifact


def write_runtime_fixtures(root: Path, artifact: dict, *, factor_ids=("cut:C01",)):
    contract = {
        "approved_script_sha256": artifact["approved_script_sha256"],
        "contract_digests": dict(artifact["contract_digests"]),
        "required_audit_checks": list(seedance_submit_module.REQUIRED_AUDIT_CHECKS),
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
        "---\nname: seedance-20\nmetadata:\n  version: \"6.6.0\"\n---\n"
    ).encode("utf-8")
    skill_path.write_bytes(skill_raw)
    artifact["compiler"]["version"] = "6.6.0"
    artifact["compiler"]["skill_sha256"] = hashlib.sha256(skill_raw).hexdigest()
    return contract_path, skill_path


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)


class YoudaoConfigTest(unittest.TestCase):
    def test_defaults_to_youdao_and_hides_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "seedance.env"
            env_file.write_text("YOUDAO_API_KEY=secret-value\n", encoding="utf-8")
            settings = load_settings(env_file, environ={})
        self.assertEqual(settings.seedance_api_provider, "youdao")
        self.assertEqual(settings.youdao_base_url, "https://openapi.youdao.com/llmgateway")
        self.assertEqual(settings.youdao_model, "seedance-2.0-fast")
        self.assertEqual(settings.youdao_resolution, "720p")
        self.assertEqual(settings.youdao_project_name, "default")
        self.assertNotIn("secret-value", repr(settings))

    def test_missing_youdao_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "seedance.env"
            env_file.write_text("SEEDANCE_API_PROVIDER=youdao\n", encoding="utf-8")
            settings = load_settings(env_file, environ={})
        with self.assertRaisesRegex(ConfigurationError, "YOUDAO_API_KEY"):
            settings.require_seedance()


class YoudaoPayloadTest(unittest.TestCase):
    def test_state_aware_poll_schedule(self):
        self.assertLess(poll_delay_for_status("submitting", 0, 20), poll_delay_for_status("running", 0, 20))
        self.assertNotEqual(poll_delay_for_status("queued", 0, 20), poll_delay_for_status("running", 0, 20))

    def test_exact_payload_shape(self):
        payload = build_payload(
            "运动会现场，镜头跟随选手。",
            5,
            "9:16",
            ["asset://asset-one", "asset://asset-two"],
            [],
            provider="youdao",
            model="seedance-2.0-fast",
            resolution="720p",
        )
        self.assertEqual(
            payload,
            {
                "model": "seedance-2.0-fast",
                "content": [
                    {"type": "text", "text": "运动会现场，镜头跟随选手。"},
                    {
                        "type": "image_url",
                        "role": "reference_image",
                        "image_url": {"url": "asset://asset-one"},
                    },
                    {
                        "type": "image_url",
                        "role": "reference_image",
                        "image_url": {"url": "asset://asset-two"},
                    },
                ],
                "generate_audio": True,
                "ratio": "9:16",
                "duration": 5,
                "watermark": False,
                "resolution": "720p",
            },
        )

    def test_fast_model_rejects_1080p(self):
        with self.assertRaisesRegex(PayloadError, "480p or 720p"):
            build_payload(
                "test", 5, "9:16", [], [], provider="youdao",
                model="seedance-2.0-fast", resolution="1080p"
            )

    def test_duration_and_reference_video_contract(self):
        with self.assertRaisesRegex(PayloadError, "4 and 15"):
            build_payload("test", 3, "9:16", [], [], provider="youdao")
        with self.assertRaisesRegex(PayloadError, "reference_videos"):
            build_payload(
                "test", 5, "9:16", [], ["https://example.com/source.mp4"],
                provider="youdao"
            )

    def test_route_leakage_is_rejected_before_payload_returns(self):
        for leaked_marker in (
            "ui-demo",
            "generatedUiDemo",
            "opaqueAppTailCard",
            "tail-card",
            "renderedMedia",
            "mediaSha256",
            "qcReport",
            "excludedRegion",
        ):
            with self.subTest(leaked_marker=leaked_marker):
                with self.assertRaisesRegex(PayloadError, "route leakage"):
                    build_payload(
                        f"Use {leaked_marker} inside the generated shot",
                        5,
                        "9:16",
                        [],
                        [],
                        provider="youdao",
                    )

    def test_route_matching_preserves_legitimate_token_boundaries(self):
        for legitimate_text in (
            "show a detail video of the package texture",
            "keep the resource interval stable for the camera move",
        ):
            with self.subTest(legitimate_text=legitimate_text):
                payload = build_payload(
                    legitimate_text,
                    5,
                    "9:16",
                    [],
                    [],
                    provider="youdao",
                )
                self.assertEqual(payload["content"][0]["text"], legitimate_text)

    def test_approval_sha_is_enforced(self):
        payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
        digest = request_sha256(payload)
        self.assertEqual(require_approved_request(payload, digest), digest)
        with self.assertRaises(PayloadError):
            require_approved_request({**payload, "duration": 6}, digest)

    def test_internal_audit_digest_authorizes_exact_payload(self):
        payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
        digest = request_sha256(payload)
        self.assertEqual(
            require_request_authorization(payload, audited_sha256=digest),
            digest,
        )

    def test_internal_audit_digest_rejects_mutated_payload(self):
        payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
        digest = request_sha256(payload)
        with self.assertRaisesRegex(PayloadError, "changed since integrity audit"):
            require_request_authorization(
                {**payload, "duration": 6},
                audited_sha256=digest,
            )

    def test_legacy_explicit_approval_remains_compatible(self):
        payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
        digest = request_sha256(payload)
        self.assertEqual(
            require_request_authorization(payload, approved_sha256=digest),
            digest,
        )


class YoudaoClientTest(unittest.TestCase):
    def test_auth_header_create_id_and_query_model(self):
        transport = FakeTransport([
            {"id": "task-123"},
            {"status": "queued"},
        ])
        client = YoudaoSeedanceClient("secret", request_json=transport)
        task_id = client.create_video({"model": "seedance-2.0-fast"})
        client.get_status(task_id)
        self.assertEqual(task_id, "task-123")
        self.assertEqual(transport.calls[0]["headers"]["x-api-key"], "secret")
        self.assertNotIn("Authorization", transport.calls[0]["headers"])
        self.assertTrue(
            transport.calls[1]["url"].endswith(
                "/api/v1/video/tasks/task-123?model=seedance-2.0-fast"
            )
        )

    def test_paid_create_video_never_retries_ambiguous_http_failure(self):
        for status_code in (429, 500):
            with self.subTest(status_code=status_code):
                transport = FakeTransport([
                    (status_code, {"message": "ambiguous create response"}),
                    {"id": "duplicate-task"},
                ])
                client = YoudaoSeedanceClient(
                    "secret", request_json=transport, sleep=lambda _: None
                )
                with self.assertRaisesRegex(SeedanceApiError, "not retried"):
                    client.create_video({"model": "seedance-2.0-fast"})
                self.assertEqual(len(transport.calls), 1)

    def test_paid_create_video_rejects_route_leakage_before_network(self):
        transport = FakeTransport([{"id": "must-not-be-created"}])
        client = YoudaoSeedanceClient("secret", request_json=transport)
        payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
        payload["content"][0]["text"] = "Render generatedUiDemo in Seedance"

        with self.assertRaisesRegex(PayloadError, "route leakage"):
            client.create_video(payload)

        self.assertEqual(transport.calls, [])

    def test_status_query_keeps_transient_retry_behavior(self):
        transport = FakeTransport([
            (500, {"message": "temporary"}),
            {"status": "queued"},
        ])
        client = YoudaoSeedanceClient(
            "secret", request_json=transport, sleep=lambda _: None
        )
        self.assertEqual(client.get_status("task-123"), {"status": "queued"})
        self.assertEqual(len(transport.calls), 2)

    def test_create_asset_never_retries_ambiguous_http_failure(self):
        for status_code in (429, 500):
            with self.subTest(status_code=status_code):
                transport = FakeTransport([
                    (status_code, {"message": "ambiguous asset response"}),
                    {"Result": {"id": "duplicate-asset"}},
                ])
                client = YoudaoSeedanceClient(
                    "secret", request_json=transport, sleep=lambda _: None
                )
                with self.assertRaisesRegex(SeedanceApiError, "not retried"):
                    client.register_asset(
                        "https://example.com/board.png", "board"
                    )
                self.assertEqual(len(transport.calls), 1)

    def test_asset_processing_to_active_and_manifest(self):
        transport = FakeTransport([
            {"Result": {"id": "asset-123"}},
            {"Result": {"Status": "Processing"}},
            {"Result": {"Status": "Active"}},
        ])
        client = YoudaoSeedanceClient(
            "secret", request_json=transport, sleep=lambda _: None
        )
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "youdao_assets.json"
            refs = prepare_youdao_assets(
                client,
                ["https://example.com/board.png"],
                manifest,
                poll_interval=0,
            )
            saved = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(refs, ["asset://asset-123"])
        self.assertEqual(saved[0]["status"], "Active")
        self.assertEqual(saved[0]["project_name"], "default")

    def test_asset_failed_stops(self):
        transport = FakeTransport([
            {"Result": {"id": "asset-bad"}},
            {"Result": {"Status": "Failed", "Message": "decode failed"}},
        ])
        client = YoudaoSeedanceClient("secret", request_json=transport)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SeedanceApiError, "decode failed"):
                prepare_youdao_assets(
                    client,
                    ["https://example.com/bad.png"],
                    Path(tmp) / "assets.json",
                )


class ConcurrentAssetClient:
    project_name = "default"

    def __init__(self, barrier=None):
        self.barrier = barrier
        self.lock = threading.Lock()
        self.registered = []
        self.polled = []

    def register_asset(self, source_url, name):
        with self.lock:
            self.registered.append(source_url)
            asset_id = f"asset-{source_url.rsplit('/', 1)[-1]}"
        if self.barrier:
            self.barrier.wait(timeout=2)
        return asset_id

    def get_asset(self, asset_id):
        with self.lock:
            self.polled.append(asset_id)
        return {"Result": {"Status": "Active"}}

    def clock(self):
        return 0.0

    def sleep(self, seconds):
        raise AssertionError(f"unexpected sleep: {seconds}")


class YoudaoAssetPreparationConcurrencyTest(unittest.TestCase):
    def test_two_invocations_share_manifest_without_duplicate_registration(self):
        client_a = ConcurrentAssetClient()
        client_b = ConcurrentAssetClient()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "youdao_assets.json"
            barrier = threading.Barrier(2)
            outputs = []
            def run(client):
                barrier.wait(timeout=2)
                outputs.append(prepare_youdao_assets(
                    client,
                    ["https://example.com/shared.png", "https://example.com/other.png"],
                    manifest,
                    max_workers=2,
                ))
            threads = [threading.Thread(target=run, args=(client,)) for client in (client_a, client_b)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            saved = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(sum(len(c.registered) for c in (client_a, client_b)), 2)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual({item["source_url"] for item in saved}, {"https://example.com/shared.png", "https://example.com/other.png"})

    def test_cached_active_asset_is_not_registered_or_polled_again(self):
        client = ConcurrentAssetClient()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "youdao_assets.json"
            manifest.write_text(json.dumps([{
                "index": "1",
                "source_url": "https://example.com/a.png",
                "asset_id": "asset-cached",
                "asset_uri": "asset://asset-cached",
                "status": "Active",
                "project_name": "default",
            }]), encoding="utf-8")
            refs = prepare_youdao_assets(
                client, ["https://example.com/a.png"], manifest, max_workers=2
            )
        self.assertEqual(refs, ["asset://asset-cached"])
        self.assertEqual(client.registered, [])
        self.assertEqual(client.polled, [])

    def test_duplicate_source_url_is_registered_once_and_order_is_preserved(self):
        client = ConcurrentAssetClient()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "youdao_assets.json"
            refs = prepare_youdao_assets(
                client,
                ["https://example.com/a.png", "https://example.com/b.png",
                 "https://example.com/a.png"],
                manifest,
                max_workers=2,
            )
            saved = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertCountEqual(
            client.registered,
            ["https://example.com/a.png", "https://example.com/b.png"],
        )
        self.assertEqual(
            refs,
            ["asset://asset-a.png", "asset://asset-b.png", "asset://asset-a.png"],
        )
        self.assertEqual(
            [item["source_url"] for item in saved],
            ["https://example.com/a.png", "https://example.com/b.png"],
        )

    def test_independent_assets_are_prepared_concurrently(self):
        client = ConcurrentAssetClient(barrier=threading.Barrier(2))
        with tempfile.TemporaryDirectory() as tmp:
            refs = prepare_youdao_assets(
                client,
                ["https://example.com/a.png", "https://example.com/b.png"],
                Path(tmp) / "youdao_assets.json",
                max_workers=2,
            )
        self.assertCountEqual(refs, ["asset://asset-a.png", "asset://asset-b.png"])

    def test_audited_cache_only_asset_preparation_never_registers_or_polls(self):
        client = ConcurrentAssetClient()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(PayloadError, "cache"):
                prepare_youdao_assets(
                    client,
                    ["https://example.com/missing.png"],
                    Path(tmp) / "youdao_assets.json",
                    cache_only=True,
                )
        self.assertEqual(client.registered, [])
        self.assertEqual(client.polled, [])

    def test_audited_cache_only_requires_active_provenance(self):
        bad_items = (
            {"status": "Active", "asset_uri": "asset://asset-a", "project_name": "default"},
            {"status": "Active", "asset_id": "asset-a", "asset_uri": "asset://asset-b", "project_name": "default"},
            {"status": "Active", "asset_id": "asset-a", "asset_uri": "asset://asset-a", "project_name": "other"},
            {"status": "Processing", "asset_id": "asset-a", "asset_uri": "asset://asset-a", "project_name": "default"},
        )
        for item in bad_items:
            client = ConcurrentAssetClient()
            with self.subTest(item=item), tempfile.TemporaryDirectory() as tmp:
                manifest = Path(tmp) / "youdao_assets.json"
                manifest.write_text(
                    json.dumps([{**item, "source_url": "https://example.com/a.png"}]),
                    encoding="utf-8",
                )
                original = manifest.read_bytes()
                with self.assertRaisesRegex(PayloadError, "cache"):
                    prepare_youdao_assets(
                        client,
                        ["https://example.com/a.png"],
                        manifest,
                        cache_only=True,
                    )
                self.assertEqual(client.registered, [])
                self.assertEqual(client.polled, [])
                self.assertEqual(manifest.read_bytes(), original)

    def test_audited_cache_only_requires_exact_project_and_asset_uri(self):
        client = ConcurrentAssetClient()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "youdao_assets.json"
            manifest.write_text(
                json.dumps([{
                    "source_url": "https://example.com/a.png",
                    "status": "Active",
                    "asset_id": "asset-a",
                    "asset_uri": "asset://asset-a",
                    "project_name": "default",
                }]),
                encoding="utf-8",
            )
            self.assertEqual(
                prepare_youdao_assets(
                    client,
                    ["https://example.com/a.png"],
                    manifest,
                    cache_only=True,
                ),
                ["asset://asset-a"],
            )
        self.assertEqual(client.registered, [])
        self.assertEqual(client.polled, [])


class YoudaoCliAuthorizationTest(unittest.TestCase):
    def test_provider_payload_carries_review_revision_binding(self):
        bindings = {
            "output_language": "en",
            "approved_script_sha256": "a" * 64,
            "approved_storyboard_manifest_sha256": "b" * 64,
            "approved_storyboard_cut_sha256s": ["c" * 64, "d" * 64],
            "segment_plan_sha256": "e" * 64,
        }
        payload = build_payload("test", 5, "9:16", [], [], provider="youdao", review_bindings=bindings)
        self.assertEqual(payload["review_bindings"], bindings)
        self.assertEqual(request_sha256(payload), request_sha256(dict(payload)))

    class FakeSettings:
        seedance_api_provider = "youdao"
        youdao_api_key = "secret"
        youdao_base_url = "https://example.test"
        youdao_model = "seedance-2.0-fast"
        youdao_project_name = "default"
        youdao_resolution = "720p"

        def require_seedance(self):
            return None

    class FakeClient:
        last_response = {"id": "created"}
        last_status_response = {}

        def __init__(self, *args, **kwargs):
            pass

        def create_video(self, payload):
            return "task-1"

    def _run_main(self, output_dir, *authorization):
        prompt_file = output_dir / "prompt.txt"
        prompt_file.write_text("test", encoding="utf-8")
        authorization = list(authorization)
        if "--audited-request-sha256" in authorization and "--seedance-input-contract" not in authorization:
            audit_index = authorization.index("--audit-artifact") + 1
            audit_path = Path(authorization[audit_index])
            artifact_data = json.loads(audit_path.read_text(encoding="utf-8"))
            contract_path, skill_path = write_runtime_fixtures(output_dir, artifact_data)
            audit_path.write_text(json.dumps(artifact_data), encoding="utf-8")
            authorization.extend(
                [
                    "--seedance-input-contract", str(contract_path),
                    "--seedance20-skill-file", str(skill_path),
                ]
            )
        argv = [
            "seedance_submit.py",
            "--prompt-file", str(prompt_file),
            "--duration", "5",
            "--output-dir", str(output_dir),
        ]
        argv.extend(authorization)
        with patch.object(seedance_submit_module, "load_settings", return_value=self.FakeSettings()), \
             patch.object(seedance_submit_module, "YoudaoSeedanceClient", self.FakeClient), \
             patch.object(seedance_submit_module, "prepare_youdao_assets", return_value=[]), \
             patch.object(sys, "argv", argv):
            return seedance_submit_module.main()

    def _argv_for_main(self, output_dir, *authorization):
        prompt_file = output_dir / "prompt.txt"
        prompt_file.write_text("test", encoding="utf-8")
        argv = [
            "seedance_submit.py",
            "--prompt-file", str(prompt_file),
            "--duration", "5",
            "--output-dir", str(output_dir),
        ]
        argv.extend(authorization)
        return argv

    def test_audited_cli_records_internal_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
            digest = request_sha256(payload)
            script_digest = "0" * 64
            artifact = output_dir / "audit.json"
            artifact.write_text(
                json.dumps(complete_audit_artifact(payload, script_digest)),
                encoding="utf-8",
            )
            self._run_main(
                output_dir,
                "--audited-request-sha256", digest,
                "--audit-artifact", str(artifact),
                "--approved-script-sha256", script_digest,
            )
            integrity = json.loads((output_dir / "request_integrity.json").read_text())
        self.assertEqual(integrity["status"], "internally_audited")
        self.assertEqual(integrity["authorization"], "seedance_20_audit_artifact")

    def test_audited_cli_rejects_wrong_script_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
            digest = request_sha256(payload)
            artifact = output_dir / "audit.json"
            artifact.write_text(
                json.dumps(complete_audit_artifact(payload, "1" * 64)),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PayloadError, "approved script digest"):
                self._run_main(
                    output_dir,
                    "--audited-request-sha256", digest,
                    "--audit-artifact", str(artifact),
                    "--approved-script-sha256", "0" * 64,
                )

    def test_audited_cli_rejects_any_remaining_ambiguity(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
            digest = request_sha256(payload)
            script_digest = "0" * 64
            artifact = output_dir / "audit.json"
            artifact.write_text(
                json.dumps(
                    complete_audit_artifact(
                        payload,
                        script_digest,
                        ambiguities=["Cut 2 voiceover timing is unresolved"],
                    )
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PayloadError, "zero ambiguity"):
                self._run_main(
                    output_dir,
                    "--audited-request-sha256", digest,
                    "--audit-artifact", str(artifact),
                    "--approved-script-sha256", script_digest,
                )

    def test_legacy_cli_records_legacy_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
            digest = request_sha256(payload)
            self._run_main(output_dir, "--approved-request-sha256", digest)
            integrity = json.loads((output_dir / "request_integrity.json").read_text())
        self.assertEqual(integrity["status"], "user_approved")
        self.assertEqual(integrity["authorization"], "explicit_user_approval")

    def test_dry_run_preview_uses_internal_integrity_wording(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            prompt_file = output_dir / "prompt.txt"
            prompt_file.write_text("test", encoding="utf-8")
            argv = [
                "seedance_submit.py",
                "--prompt-file", str(prompt_file),
                "--duration", "5",
                "--output-dir", str(output_dir),
                "--dry-run",
            ]
            with patch.object(seedance_submit_module, "load_settings", return_value=self.FakeSettings()), \
                 patch.object(seedance_submit_module, "YoudaoSeedanceClient", self.FakeClient), \
                 patch.object(seedance_submit_module, "prepare_youdao_assets", return_value=[]), \
                 patch.object(sys, "argv", argv):
                seedance_submit_module.main()
            preview = json.loads((output_dir / "approval_preview.json").read_text())
        self.assertEqual(preview["status"], "internal_integrity_preview")

    def test_audited_cli_requires_frozen_input_contract_before_asset_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
            digest = request_sha256(payload)
            script_digest = "0" * 64
            artifact = output_dir / "audit.json"
            artifact.write_text(
                json.dumps(complete_audit_artifact(payload, script_digest)),
                encoding="utf-8",
            )
            argv = self._argv_for_main(
                output_dir,
                "--audited-request-sha256", digest,
                "--audit-artifact", str(artifact),
                "--approved-script-sha256", script_digest,
            )
            with patch.object(seedance_submit_module, "load_settings", return_value=self.FakeSettings()), \
                 patch.object(seedance_submit_module, "YoudaoSeedanceClient", self.FakeClient), \
                 patch.object(seedance_submit_module, "prepare_youdao_assets", return_value=[]) as prepare, \
                 patch.object(sys, "argv", argv):
                with self.assertRaisesRegex(PayloadError, "seedance-input-contract"):
                    seedance_submit_module.main()
            self.assertFalse(prepare.called)

    def test_audited_cli_rejects_mixed_authorization_before_asset_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
            digest = request_sha256(payload)
            script_digest = "0" * 64
            artifact = output_dir / "audit.json"
            artifact.write_text(
                json.dumps(complete_audit_artifact(payload, script_digest)),
                encoding="utf-8",
            )
            argv = self._argv_for_main(
                output_dir,
                "--audited-request-sha256", digest,
                "--approved-request-sha256", digest,
                "--audit-artifact", str(artifact),
                "--approved-script-sha256", script_digest,
            )
            with patch.object(seedance_submit_module, "load_settings", return_value=self.FakeSettings()), \
                 patch.object(seedance_submit_module, "YoudaoSeedanceClient", self.FakeClient), \
                 patch.object(seedance_submit_module, "prepare_youdao_assets", return_value=[]) as prepare, \
                 patch.object(sys, "argv", argv):
                with self.assertRaisesRegex(PayloadError, "exactly one"):
                    seedance_submit_module.main()
            self.assertFalse(prepare.called)

    def test_audited_cli_uses_cache_only_asset_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
            digest = request_sha256(payload)
            script_digest = "0" * 64
            artifact_data = complete_audit_artifact(payload, script_digest)
            contract_path, skill_path = write_runtime_fixtures(output_dir, artifact_data)
            artifact = output_dir / "audit.json"
            artifact.write_text(json.dumps(artifact_data), encoding="utf-8")
            argv = self._argv_for_main(
                output_dir,
                "--audited-request-sha256", digest,
                "--audit-artifact", str(artifact),
                "--approved-script-sha256", script_digest,
                "--seedance-input-contract", str(contract_path),
                "--seedance20-skill-file", str(skill_path),
            )
            with patch.object(seedance_submit_module, "load_settings", return_value=self.FakeSettings()), \
                 patch.object(seedance_submit_module, "YoudaoSeedanceClient", self.FakeClient), \
                 patch.object(seedance_submit_module, "prepare_youdao_assets", return_value=[]) as prepare, \
                 patch.object(sys, "argv", argv):
                seedance_submit_module.main()
            self.assertTrue(prepare.call_args.kwargs.get("cache_only"))

    def test_dry_run_rejects_authorization_before_asset_preparation(self):
        payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
        digest = request_sha256(payload)
        for flag in ("--audited-request-sha256", "--approved-request-sha256"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as tmp:
                output_dir = Path(tmp)
                argv = self._argv_for_main(
                    output_dir,
                    "--dry-run",
                    flag,
                    digest,
                )
                with patch.object(seedance_submit_module, "load_settings", return_value=self.FakeSettings()), \
                     patch.object(seedance_submit_module, "YoudaoSeedanceClient", self.FakeClient), \
                     patch.object(seedance_submit_module, "prepare_youdao_assets", return_value=[]) as prepare, \
                     patch.object(sys, "argv", argv):
                    with self.assertRaisesRegex(PayloadError, "dry-run"):
                        seedance_submit_module.main()
                self.assertFalse(prepare.called)

    def test_resume_rejects_new_request_flags_before_asset_preparation(self):
        payload = build_payload("test", 5, "9:16", [], [], provider="youdao")
        digest = request_sha256(payload)
        extras = (
            ("--audited-request-sha256", digest),
            ("--approved-request-sha256", digest),
            ("--audit-artifact", "audit.json"),
            ("--approved-script-sha256", "0" * 64),
            ("--seedance-input-contract", "contract.json"),
        )
        for flag, value in extras:
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as tmp:
                output_dir = Path(tmp)
                argv = self._argv_for_main(
                    output_dir,
                    "--resume-task-id", "known-task",
                    flag,
                    value,
                )
                with patch.object(seedance_submit_module, "load_settings", return_value=self.FakeSettings()), \
                     patch.object(seedance_submit_module, "YoudaoSeedanceClient", self.FakeClient), \
                     patch.object(seedance_submit_module, "prepare_youdao_assets", return_value=[]) as prepare, \
                     patch.object(sys, "argv", argv):
                    with self.assertRaisesRegex(PayloadError, "resume"):
                        seedance_submit_module.main()
                self.assertFalse(prepare.called)

    def test_plain_resume_does_not_create_new_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            argv = self._argv_for_main(output_dir, "--resume-task-id", "known-task")
            with patch.object(seedance_submit_module, "load_settings", return_value=self.FakeSettings()), \
                 patch.object(seedance_submit_module, "YoudaoSeedanceClient", self.FakeClient), \
                 patch.object(self.FakeClient, "create_video", wraps=self.FakeClient.create_video) as create, \
                 patch.object(seedance_submit_module, "prepare_youdao_assets", return_value=[]) as prepare, \
                 patch.object(sys, "argv", argv):
                seedance_submit_module.main()
            self.assertEqual(json.loads((output_dir / "create_response.json").read_text())["resume_task_id"], "known-task")
            self.assertEqual(
                json.loads((output_dir / "status.json").read_text())["status"],
                "known_task",
            )
            create.assert_not_called()
            prepare.assert_not_called()

    def test_plain_resume_does_not_require_new_request_prompt_or_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            argv = [
                "seedance_submit.py",
                "--output-dir", str(output_dir),
                "--resume-task-id", "known-task",
            ]
            with patch.object(seedance_submit_module, "load_settings", return_value=self.FakeSettings()), \
                 patch.object(seedance_submit_module, "YoudaoSeedanceClient", self.FakeClient), \
                 patch.object(self.FakeClient, "create_video", wraps=self.FakeClient.create_video) as create, \
                 patch.object(seedance_submit_module, "prepare_youdao_assets", return_value=[]) as prepare, \
                 patch.object(sys, "argv", argv):
                seedance_submit_module.main()
            self.assertEqual(
                json.loads((output_dir / "create_response.json").read_text())["resume_task_id"],
                "known-task",
            )
            create.assert_not_called()
            prepare.assert_not_called()

    def test_resume_and_dry_run_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            argv = self._argv_for_main(
                output_dir,
                "--resume-task-id", "known-task",
                "--dry-run",
            )
            with patch.object(seedance_submit_module, "load_settings", return_value=self.FakeSettings()), \
                 patch.object(seedance_submit_module, "YoudaoSeedanceClient", self.FakeClient), \
                 patch.object(seedance_submit_module, "prepare_youdao_assets", return_value=[]) as prepare, \
                 patch.object(sys, "argv", argv):
                with self.assertRaisesRegex(PayloadError, "resume.*dry-run"):
                    seedance_submit_module.main()
            prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
