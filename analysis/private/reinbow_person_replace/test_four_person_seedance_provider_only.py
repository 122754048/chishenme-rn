from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "four_person_seedance_provider_only.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("four_person_seedance_provider_only", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_request_uses_four_images_and_no_binding_board() -> None:
    module = _load_module()
    payload, audit = module.build_request()

    assert len(payload["imageUrls"]) == 4
    assert payload["imageUrls"] == module.load_identity_urls()
    assert len(payload["videoUrls"]) == 1
    assert "@Image5" not in payload["prompt"]
    assert "binding map" not in payload["prompt"].casefold()
    assert audit["provider_only"] is True
    assert audit["primary_change_variable"] == "positive_state_binding_v3"
    assert audit["image_tag_order"] == ["@Image1", "@Image2", "@Image3", "@Image4"]
    assert payload["realPersonMode"] is True
    assert payload["conversionSlots"] == ["all"]
    assert len(payload["prompt"]) <= 1800


def test_current_request_is_locked_by_its_submission_receipt() -> None:
    module = _load_module()
    _, audit = module.build_request()

    assert audit["request_sha256"] in module.prior_submitted_request_hashes()
    assert (module.RUN_DIR / f"create_{audit['request_sha256']}.json").is_file()


def test_duplicate_submission_is_rejected(tmp_path: Path) -> None:
    module = _load_module()
    _, audit = module.build_request()
    (tmp_path / f"create_{audit['request_sha256']}.json").write_text("{}", encoding="utf-8")

    try:
        module.assert_not_previously_submitted(tmp_path, audit["request_sha256"])
    except RuntimeError as exc:
        assert str(exc) == "UNCHANGED_REQUEST_ALREADY_SUBMITTED"
    else:
        raise AssertionError("duplicate request hash was not rejected")
