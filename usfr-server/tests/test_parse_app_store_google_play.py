from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "bundled-skills"
    / "parse-app-store-evidence"
    / "scripts"
    / "parse_app_store.py"
)


def load_parser():
    spec = importlib.util.spec_from_file_location("parse_app_store", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GOOGLE_PAGE = b"""
<!doctype html>
<html lang="en">
  <head>
    <link rel="canonical" href="https://play.google.com/store/apps/details?id=com.example.social&amp;hl=en">
    <meta property="og:title" content="Example Social - Apps on Google Play">
    <meta property="og:image" content="https://play-lh.googleusercontent.com/icon-token">
    <meta name="appstore:bundle_id" content="com.example.social">
  </head>
  <body>
    <div aria-label="Phone" aria-pressed="true"></div>
    <img alt="Screenshot image" data-screenshot-index="0" data-device-family="phone"
         src="https://play-lh.googleusercontent.com/shot-one=w526-h296">
    <img alt="Screenshot image" data-screenshot-index="1" data-device-family="phone"
         src="https://play-lh.googleusercontent.com/shot-two=w526-h296">
  </body>
</html>
"""


def test_google_play_page_is_validated_and_parsed_into_common_shape():
    parser = load_parser()

    requested = parser.validate_store_page_url(
        "https://play.google.com/store/apps/details?id=com.example.social&hl=en&gl=US"
    )
    parsed = parser.parse_page(
        requested,
        requested,
        "text/html",
        GOOGLE_PAGE,
    )

    assert parsed["provider"] == "google_play"
    assert parsed["store_app_id"] == "com.example.social"
    assert parsed["name"] == "Example Social"
    assert parsed["storefront"] == "us"
    assert parsed["language"] == "en"
    assert parsed["icon"].source_url.startswith("https://play-lh.googleusercontent.com/")
    assert [item.device_family for item in parsed["screenshots"]] == ["phone", "phone"]
    assert [item.store_media_ordinal for item in parsed["screenshots"]] == [0, 1]


def test_google_and_apple_providers_emit_the_same_required_bundle_fields():
    parser = load_parser()
    required = {
        "contract",
        "contract_version",
        "provider",
        "requested_url",
        "final_url",
        "canonical_url",
        "store_app_id",
        "name",
        "storefront",
        "language",
        "page_sha256",
        "pixel_truth_mode",
        "icon",
        "screenshots",
        "screenshot_device_families",
        "warnings",
    }

    # The helper is intentionally provider-neutral; this test only requires
    # the new Google path to expose the same bundle surface as Apple.
    bundle = parser.build_bundle(
        requested_url="https://play.google.com/store/apps/details?id=com.example.social&hl=en&gl=US",
        final_url="https://play.google.com/store/apps/details?id=com.example.social&hl=en&gl=US",
        page_body=GOOGLE_PAGE,
        parsed=parser.parse_page(
            "https://play.google.com/store/apps/details?id=com.example.social&hl=en&gl=US",
            "https://play.google.com/store/apps/details?id=com.example.social&hl=en&gl=US",
            "text/html",
            GOOGLE_PAGE,
        ),
        media=[],
        metadata_only=True,
    )

    assert required <= bundle.keys()
    assert bundle["contract"] == "app-store-evidence"
    assert bundle["contract_version"] == 1
    assert "width" in bundle["icon"] and "height" in bundle["icon"]
    assert "declared_width" not in bundle["icon"]


def test_google_media_host_is_not_open_ended():
    parser = load_parser()

    with pytest.raises(parser.EvidenceError):
        parser.validate_google_media_url("https://evil.example/shot.png")


def test_google_slug_urls_are_supported_without_inventing_device_family():
    parser = load_parser()
    requested = parser.validate_store_page_url(
        "https://play.google.com/store/apps/details/Example_Social?id=com.example.social&hl=en"
    )
    page = GOOGLE_PAGE.replace(b'data-device-family="phone"', b'')
    parsed = parser.parse_page(requested, requested, "text/html", page)

    assert parsed["canonical_url"].startswith("https://play.google.com/store/apps/details")
    assert parsed["screenshot_device_families"] == ["other"]
    assert any("device family" in warning for warning in parsed["warnings"])


def test_google_page_language_comes_from_resolved_page_before_requested_hint():
    parser = load_parser()
    requested = parser.validate_store_page_url(
        "https://play.google.com/store/apps/details?id=com.example.social&hl=xx_YY&gl=ZZ"
    )
    parsed = parser.parse_page(requested, requested, "text/html", GOOGLE_PAGE)

    assert parsed["language"] == "en"
    assert parsed["storefront"] == "default"
    assert any("storefront" in warning for warning in parsed["warnings"])


def test_google_ds5_fallback_binds_original_screenshot_dimensions():
    parser = load_parser()
    page = b"""
    <html lang="en"><head>
      <link rel="canonical" href="https://play.google.com/store/apps/details?id=com.example.social&amp;hl=en">
      <meta property="og:title" content="Example Social - Apps on Google Play">
      <meta property="og:image" content="https://play-lh.googleusercontent.com/icon-token">
      <meta name="appstore:bundle_id" content="com.example.social">
    </head><body>
      <script>AF_initDataCallback({key: 'ds:5', data:[[null,["com.example.social"],[[[null,2,[1920,1080],[null,null,"https://play-lh.googleusercontent.com/shot-token"]]]]] ]});</script>
    </body></html>
    """
    url = "https://play.google.com/store/apps/details?id=com.example.social&hl=en&gl=US"
    parsed = parser.parse_page(url, url, "text/html", page)

    assert len(parsed["screenshots"]) == 1
    assert parsed["screenshots"][0].source_url.endswith("shot-token")
    assert (parsed["screenshots"][0].declared_width, parsed["screenshots"][0].declared_height) == (1080, 1920)


def test_google_localized_alt_markers_are_target_media_markers():
    parser = load_parser()
    page = GOOGLE_PAGE.replace(b'<html lang="en">', b'<html lang="zh-CN">').replace(
        b'Screenshot image', '截图图片'.encode('utf-8')
    ).replace(
        b' data-screenshot-index="0"', b''
    ).replace(b' data-screenshot-index="1"', b'')
    url = "https://play.google.com/store/apps/details?id=com.example.social&hl=zh_CN&gl=CN"
    parsed = parser.parse_page(url, url, "text/html", page)

    assert len(parsed["screenshots"]) == 2
    assert parsed["language"] == "zh-CN"
    assert parsed["storefront"] == "cn"
