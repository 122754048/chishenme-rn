from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def app_evidence_required(execution_map: Mapping[str, object]) -> bool:
    app_evidence = execution_map.get("app_evidence")
    if isinstance(app_evidence, Mapping):
        return app_evidence.get("required") is True
    regions = execution_map.get("regions") or []
    if not isinstance(regions, list):
        return False
    return any(
        isinstance(region, Mapping) and region.get("media_origin") in {"generated", "generated_ui"}
        for region in regions
    )


def cache_key_for_app_store(
    url: str,
    purpose: tuple[str, ...],
    *,
    store_locale: str = "und",
    parser_version: str = "official-store-v1",
) -> str:
    normalized = _normalize_store_url(url)
    normalized_locale = _normalized_identity(store_locale, field="store_locale")
    normalized_parser_version = _normalized_identity(parser_version, field="parser_version")
    payload = {
        "url": normalized,
        "purpose": sorted(set(purpose)),
        "store_locale": normalized_locale,
        "parser_version": normalized_parser_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_target_truth(
    *,
    slots: Mapping[str, object],
    app_evidence: Mapping[str, object] | None,
) -> dict[str, object]:
    facts: dict[str, dict[str, object]] = {}
    for slot_id, source in slots.items():
        if not isinstance(source, Mapping):
            continue
        sha256 = source.get("sha256")
        if isinstance(sha256, str) and sha256:
            facts[str(slot_id)] = {"source_sha256": sha256, "status": "verified_input"}
    app_evidence = app_evidence or {}
    allowed_claims = _strings(app_evidence.get("allowed_claims"))
    blocked_claims = _strings(app_evidence.get("blocked_claims"))
    return {
        "schema_version": 1,
        "facts": facts,
        "app_evidence_bundle_sha256": app_evidence.get("bundle_sha256"),
        "allowed_claims": allowed_claims,
        "blocked_claims": blocked_claims,
    }


class AppEvidenceCache:
    """Small local index used only by the console adapter's evidence resolver."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def get_or_resolve(
        self,
        *,
        url: str,
        purpose: tuple[str, ...],
        store_locale: str = "und",
        parser_version: str = "official-store-v1",
        resolver: Callable[[], Mapping[str, object]],
    ) -> dict[str, object]:
        key = cache_key_for_app_store(
            url,
            purpose,
            store_locale=store_locale,
            parser_version=parser_version,
        )
        path = self.root / f"{key}.json"
        if path.is_file():
            return _validated_app_evidence_bundle(json.loads(path.read_text(encoding="utf-8")))
        bundle = dict(resolver())
        bundle = _validated_app_evidence_bundle(bundle)
        bundle["cache_key"] = key
        bundle["normalized_url"] = _normalize_store_url(url)
        bundle["purpose"] = sorted(set(purpose))
        bundle["store_locale"] = _normalized_identity(store_locale, field="store_locale")
        bundle["parser_version"] = _normalized_identity(parser_version, field="parser_version")
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root, delete=False) as output:
            json.dump(bundle, output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            temporary = Path(output.name)
        temporary.replace(path)
        return bundle


def _normalize_store_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower()
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((parsed.scheme.lower(), host, parsed.path, query, ""))


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _normalized_identity(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"APP_EVIDENCE_{field.upper()}_INVALID")
    return value.strip().casefold()


def _validated_app_evidence_bundle(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("APP_EVIDENCE_BUNDLE_INVALID")
    bundle = dict(value)
    required_strings = ("bundle_sha256", "canonical_url", "app_id")
    if any(not isinstance(bundle.get(field), str) or not bundle[field] for field in required_strings):
        raise ValueError("APP_EVIDENCE_BUNDLE_INVALID")
    digest = str(bundle["bundle_sha256"])
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("APP_EVIDENCE_BUNDLE_INVALID")
    screenshots = bundle.get("screenshots")
    icon = bundle.get("icon")
    if (
        not isinstance(screenshots, list)
        or not screenshots
        or any(
            not isinstance(item, Mapping)
            or not _is_sha256(item.get("sha256"))
            or not isinstance(item.get("source"), str)
            or not item["source"]
            for item in screenshots
        )
        or not isinstance(icon, Mapping)
        or not _is_sha256(icon.get("sha256"))
        or not isinstance(icon.get("source"), str)
        or not icon["source"]
    ):
        raise ValueError("APP_EVIDENCE_BUNDLE_INVALID")
    return bundle


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)
