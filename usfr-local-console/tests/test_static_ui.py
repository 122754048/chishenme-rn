from pathlib import Path

from app.slots import FIXED_SLOT_IDS


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def test_index_has_all_seven_fixed_slot_controls_and_language_select():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    for slot in FIXED_SLOT_IDS:
        assert f'name="{slot}"' in page
    assert 'name="output_language"' in page
    assert 'name="background_music"' in page
    assert 'name="opaque_audio_policy"' in page


def test_browser_code_uses_only_relative_api_paths_and_never_mentions_api_keys():
    code = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'fetch("/api/' in code or "fetch('/api/" in code
    assert "http://" not in code
    assert "https://" not in code
    assert "RUNNINGHUB_API_KEY" not in code


def test_browser_renders_server_route_preview_and_uses_provider_poll_backoff():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    code = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'id="route-preview"' in page
    assert "function renderRoutePreview" in code
    assert "job.route_preview" in code
    assert "function providerPollDelay" in code
    assert 'id="timing-ledger"' in page
    assert "function renderTimingLedger" in code
    assert "preview.background_music" in code
    assert 'id="qa-receipt"' in page
    assert "function renderQaReceipt" in code


def test_browser_exposes_batch_manifest_preflight_submission_retry_and_result_index():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    code = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'id="batch-manifest"' in page
    assert 'id="batch-preflight"' in page
    assert 'id="batch-submit"' in page
    assert 'id="batch-rows"' in page
    assert 'batches/manifest/preflight' in code
    assert 'batches/manifest' in code
    assert 'results-index' in code
    assert '/retry' in code
