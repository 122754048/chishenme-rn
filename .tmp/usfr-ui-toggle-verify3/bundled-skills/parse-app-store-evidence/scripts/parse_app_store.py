#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from io import BytesIO
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import socket
import sys
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from PIL import Image, UnidentifiedImageError
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow is required: python -m pip install Pillow") from exc


class EvidenceError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: dict[str, str] = {}
        self._script_id: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        values = {str(key).lower(): value for key, value in attrs}
        script_id = str(values.get("id") or "").strip()
        if script_id:
            self._script_id = script_id
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._script_id is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._script_id is not None:
            self.scripts[self._script_id] = "".join(self._parts)
            self._script_id = None
            self._parts = []


class GooglePageCollector(HTMLParser):
    """Collect only target-page metadata and explicit screenshot markers.

    Google Play pages contain hundreds of unrelated Googleusercontent images
    (reviews, recommendations, permissions).  The collector intentionally
    accepts only the page's app metadata and images marked as screenshots or
    the target icon; it never scans every URL in the document.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.canonical_url: str | None = None
        self.html_language: str | None = None
        self.title = ""
        self._in_title = False
        self._title_parts: list[str] = []
        self.semantic_name = ""
        self._in_semantic_name = False
        self._semantic_name_parts: list[str] = []
        self.json_ld: list[Mapping[str, Any]] = []
        self._in_json_ld = False
        self._json_ld_parts: list[str] = []
        self.screenshots: list[dict[str, str | None]] = []
        self.icon_candidates: list[str] = []
        self.form_factors: list[tuple[str, bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).lower(): value for key, value in attrs}
        lowered = tag.lower()
        if lowered == "html":
            language = str(values.get("lang") or "").strip()
            if language:
                self.html_language = language
        elif lowered == "title":
            self._in_title = True
            self._title_parts = []
        elif lowered == "script" and str(values.get("type") or "").strip().lower() == "application/ld+json":
            self._in_json_ld = True
            self._json_ld_parts = []
        elif lowered == "meta":
            key = str(values.get("property") or values.get("name") or "").strip().lower()
            content = str(values.get("content") or "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif lowered == "link":
            rel = str(values.get("rel") or "").strip().lower()
            href = str(values.get("href") or "").strip()
            if href and (rel == "canonical" or "canonical" in rel.split()):
                self.canonical_url = href
        elif str(values.get("itemprop") or "").strip().lower() == "name":
            content = str(values.get("content") or "").strip()
            if content:
                self.semantic_name = content
            else:
                self._in_semantic_name = True
                self._semantic_name_parts = []
        elif lowered in {"div", "button", "span", "li"}:
            label = str(values.get("aria-label") or "").strip()
            if label and _looks_like_form_factor(label):
                pressed = str(values.get("aria-pressed") or "").strip().lower() == "true"
                self.form_factors.append((label, pressed))
        elif lowered == "img":
            source = _image_source_from_attrs(values)
            if not source:
                return
            alt = str(values.get("alt") or "").strip().lower()
            screenshot_index = values.get("data-screenshot-index")
            if screenshot_index is not None or _looks_like_screenshot_alt(alt):
                self.screenshots.append(
                    {
                        "source": source,
                        "index": str(screenshot_index).strip() if screenshot_index is not None else None,
                        "device_family": str(
                            values.get("data-device-family")
                            or values.get("data-form-factor")
                            or values.get("data-device")
                            or ""
                        ).strip()
                        or None,
                    }
                )
            elif _looks_like_icon_alt(alt):
                self.icon_candidates.append(source)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._in_semantic_name:
            self._semantic_name_parts.append(data)
        if self._in_json_ld:
            self._json_ld_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_json_ld:
            raw = "".join(self._json_ld_parts).strip()
            if raw:
                try:
                    loaded = json.loads(raw)
                    values = loaded if isinstance(loaded, list) else [loaded]
                    self.json_ld.extend(item for item in values if isinstance(item, Mapping))
                except json.JSONDecodeError:
                    pass
            self._in_json_ld = False
            self._json_ld_parts = []
        if tag.lower() == "title" and self._in_title:
            self.title = "".join(self._title_parts).strip()
            self._in_title = False
            self._title_parts = []
        if self._in_semantic_name and tag.lower() not in {"html", "body"}:
            value = "".join(self._semantic_name_parts).strip()
            if value:
                self.semantic_name = value
            self._in_semantic_name = False
            self._semantic_name_parts = []


@dataclass(frozen=True)
class Artwork:
    media_role: str
    store_media_ordinal: int
    device_family: str | None
    device_family_ordinal: int | None
    source_url: str
    declared_width: int
    declared_height: int


APP_ID_PATTERN = re.compile(r"(?:^|/)id(?P<app_id>\d+)(?:/|$)", re.IGNORECASE)
GOOGLE_PACKAGE_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$"
)
ALLOWED_PAGE_TYPES = {"text/html", "text/plain"}
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
GOOGLE_MEDIA_HOSTS = {
    "play-lh.googleusercontent.com",
    "lh3.googleusercontent.com",
    "lh4.googleusercontent.com",
    "lh5.googleusercontent.com",
    "lh6.googleusercontent.com",
}


def app_id(url: str) -> str | None:
    match = APP_ID_PATTERN.search(urlsplit(url).path)
    return match.group("app_id") if match else None


def google_app_id(url: str) -> str | None:
    values = parse_qs(urlsplit(url).query, keep_blank_values=True).get("id", [])
    if len(values) != 1:
        return None
    candidate = str(values[0]).strip()
    return candidate if GOOGLE_PACKAGE_PATTERN.fullmatch(candidate) else None


def _provider_for_url(url: str) -> str:
    host = str(urlsplit(url).hostname or "").rstrip(".").lower()
    if host == "apps.apple.com":
        return "apple_app_store"
    if host == "play.google.com":
        return "google_play"
    raise EvidenceError("provide a direct official Apple App Store or Google Play App URL")


def validate_public_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in {None, 80, 443}
    ):
        raise EvidenceError("URL must be a plain public HTTP(S) URL on port 80 or 443")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise EvidenceError("URL cannot target a local host")
    try:
        records = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        raise EvidenceError("URL host could not be resolved") from exc
    addresses = {item[4][0].split("%", 1)[0] for item in records}
    if not addresses or any(not ipaddress.ip_address(raw).is_global for raw in addresses):
        raise EvidenceError("URL resolved to a non-public address")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))


def validate_apple_page_url(value: str) -> str:
    normalized = validate_public_url(value)
    host = str(urlsplit(normalized).hostname or "").rstrip(".").lower()
    if host != "apps.apple.com" or not app_id(normalized):
        raise EvidenceError("provide a direct Apple App Store App URL")
    return normalized


def validate_google_page_url(value: str) -> str:
    normalized = validate_public_url(value)
    parsed = urlsplit(normalized)
    host = str(parsed.hostname or "").rstrip(".").lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    valid_path = (
        len(path_parts) in {3, 4}
        and [part.lower() for part in path_parts[:3]] == ["store", "apps", "details"]
    )
    if host != "play.google.com" or not valid_path or not google_app_id(normalized):
        raise EvidenceError("provide a direct Google Play App URL with a valid package id")
    return normalized


def validate_store_page_url(value: str) -> str:
    normalized = validate_public_url(value)
    provider = _provider_for_url(normalized)
    if provider == "apple_app_store":
        return validate_apple_page_url(normalized)
    return validate_google_page_url(normalized)


def validate_apple_media_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    host = str(parsed.hostname or "").rstrip(".").lower()
    if (
        parsed.scheme.lower() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in {None, 443}
        or not (host == "mzstatic.com" or host.endswith(".mzstatic.com"))
    ):
        raise EvidenceError("Apple artwork must use the official HTTPS mzstatic CDN")
    return validate_public_url(urlunsplit(("https", parsed.netloc, parsed.path or "/", parsed.query, "")))


def validate_google_media_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    host = str(parsed.hostname or "").rstrip(".").lower()
    if (
        parsed.scheme.lower() != "https"
        or host not in GOOGLE_MEDIA_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in {None, 443}
        or not parsed.path
    ):
        raise EvidenceError("Google Play artwork must use an official HTTPS Googleusercontent CDN")
    return validate_public_url(urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, "")))


def _image_source_from_attrs(values: Mapping[str, str | None]) -> str:
    for key in ("src", "data-src", "data-original", "data-lazy-src"):
        value = str(values.get(key) or "").strip()
        if value:
            return value
    srcset = str(values.get("srcset") or "").strip()
    if srcset:
        return srcset.split(",", 1)[0].strip().split(" ", 1)[0]
    return ""


def _looks_like_form_factor(value: str) -> bool:
    lowered = value.strip().lower().replace("_", " ")
    return any(token in lowered for token in ("phone", "tablet", "chromebook", "watch", "wear", "tv", "car"))


def _looks_like_screenshot_alt(value: str) -> bool:
    lowered = value.strip().lower()
    return any(
        token in lowered
        for token in (
            "screenshot",
            "screen shot",
            "截屏",
            "截图",
            "スクリーンショット",
            "captura de pantalla",
            "captura de tela",
            "снимок экрана",
        )
    )


def _looks_like_icon_alt(value: str) -> bool:
    lowered = value.strip().lower()
    return any(
        token in lowered
        for token in (
            "icon",
            "图标",
            "アイコン",
            "icono",
            "ícono",
            "icône",
            "икон",
        )
    )


def _normalize_device_family(value: str) -> str:
    lowered = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    aliases = {
        "iphone": "phone",
        "android_phone": "phone",
        "phone_android": "phone",
        "android_tablet": "tablet",
        "tablet_android": "tablet",
        "wear_os": "wear_os",
        "wearos": "wear_os",
    }
    return aliases.get(lowered, lowered or "other")


def _normalize_language(value: str) -> str:
    cleaned = value.strip().replace("_", "-")
    if not cleaned:
        return ""
    pieces = cleaned.split("-")
    return "-".join([pieces[0].lower(), *[part.upper() if len(part) in {2, 3} else part for part in pieces[1:]]])


def _query_value(url: str, key: str) -> str:
    values = parse_qs(urlsplit(url).query, keep_blank_values=True).get(key, [])
    return str(values[0]).strip() if values else ""


def _google_artwork_request_url(value: str) -> str:
    """Ask Google's CDN for the original asset instead of a display thumbnail."""
    suffix = r"=(?:w\d+-h\d+|s\d+)(?:-[^/?#]*)?"
    if re.search(rf"{suffix}(?:$|[?])", value):
        return re.sub(rf"{suffix}(?=$|[?])", "=d", value)
    return value if value.endswith("=d") else f"{value}=d"


def _google_declared_dimensions(value: str, *, icon: bool = False) -> tuple[int, int]:
    match = re.search(r"=w(\d+)-h(\d+)(?:-[^/?#]*)?(?:$|[?])", value)
    if not match:
        match = re.search(r"[?&]w=(\d+).*?[?&]h=(\d+)(?:&|$)", value)
    if match:
        width, height = int(match.group(1)), int(match.group(2))
        if width > 0 and height > 0:
            return width, height
        raise EvidenceError("Google Play screenshot dimensions are invalid")
    if icon:
        return 512, 512
    raise EvidenceError("Google Play screenshot dimensions are missing from page metadata")


def _balanced_json_array(text: str, start: int) -> str | None:
    if start < 0 or start >= len(text) or text[start] != "[":
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _google_ds5_screenshots(body_text: str, package: str) -> list[tuple[str, int, int]]:
    """Read target-bound original screenshot records from Google's ds:5 data."""
    marker = re.compile(r"AF_initDataCallback\(\{key:\s*['\"]ds:5['\"]")
    for match in marker.finditer(body_text):
        script_end = body_text.find("</script>", match.end())
        segment = body_text[match.end() : script_end if script_end >= 0 else len(body_text)]
        data_start = segment.find("data:")
        if data_start < 0:
            continue
        array_start = segment.find("[", data_start)
        raw = _balanced_json_array(segment, array_start)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        def find_anchor(node: Any) -> tuple[list[Any], int] | None:
            if isinstance(node, list):
                for index, child in enumerate(node):
                    if child == [package]:
                        return node, index
                    found = find_anchor(child)
                    if found:
                        return found
            return None

        anchor = find_anchor(data)
        if not anchor:
            continue
        parent, index = anchor
        for sibling in parent[index + 1 : index + 7]:
            records: list[tuple[str, int, int]] = []

            def collect(node: Any) -> None:
                if isinstance(node, list):
                    if (
                        len(node) >= 4
                        and node[0] is None
                        and node[1] == 2
                        and isinstance(node[2], list)
                        and len(node[2]) == 2
                        and isinstance(node[3], list)
                        and len(node[3]) >= 3
                        and isinstance(node[3][2], str)
                    ):
                        height, width = node[2]
                        source = node[3][2].strip()
                        if (
                            isinstance(height, int)
                            and isinstance(width, int)
                            and height > 0
                            and width > 0
                            and source
                        ):
                            records.append((source, width, height))
                    for child in node:
                        collect(child)

            collect(sibling)
            if records:
                return records
    return []


def fetch(url: str, *, validator, accept: str, allowed_types: set[str], max_bytes: int, timeout: float, max_redirects: int) -> tuple[str, str, str, bytes]:
    requested = validator(url)
    current = requested
    opener = build_opener(NoRedirect())
    for redirect_index in range(max_redirects + 1):
        current = validator(current)
        request = Request(current, method="GET", headers={"Accept": accept, "User-Agent": "CodexAppStoreEvidence/1"})
        try:
            response = opener.open(request, timeout=timeout)
            headers: Mapping[str, str] = response.headers
            body = response.read(max_bytes + 1)
            response.close()
        except HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location")
                if not location or redirect_index >= max_redirects:
                    raise EvidenceError("resource exceeded the safe redirect limit") from exc
                current = urljoin(current, location)
                continue
            raise EvidenceError(f"resource returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise EvidenceError("resource could not be fetched safely") from exc
        if len(body) > max_bytes:
            raise EvidenceError("resource exceeded the configured byte limit")
        content_type = str(headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].lower()
        if content_type not in allowed_types:
            raise EvidenceError(f"unsupported content type: {content_type}")
        return requested, current, content_type, body
    raise EvidenceError("resource exceeded the safe redirect limit")


def target_payload(server_data: Any, requested_app_id: str) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if not isinstance(server_data, Mapping) or not isinstance(server_data.get("data"), list):
        raise EvidenceError("Apple serialized product data is invalid")
    for record in server_data["data"]:
        if not isinstance(record, Mapping):
            continue
        intent, payload = record.get("intent"), record.get("data")
        if isinstance(intent, Mapping) and str(intent.get("id") or "") == requested_app_id and isinstance(payload, Mapping):
            return intent, payload
    raise EvidenceError("page did not contain the requested target App")


def artwork_url(value: Any) -> tuple[str, int, int]:
    if not isinstance(value, Mapping):
        raise EvidenceError("artwork metadata is missing")
    template = str(value.get("template") or "").strip()
    width, height = int(value.get("width") or 0), int(value.get("height") or 0)
    if not template or width <= 0 or height <= 0:
        raise EvidenceError("artwork metadata is incomplete")
    variants = value.get("variants") if isinstance(value.get("variants"), list) else []
    formats = [str(item.get("format") or "").lower() for item in variants if isinstance(item, Mapping)]
    extension = next(("png" if item == "png" else "webp" if item == "webp" else "jpg" for item in formats if item in {"png", "webp", "jpeg", "jpg"}), "jpg")
    url = template.replace("{w}", str(width)).replace("{h}", str(height)).replace("{c}", str(value.get("crop") or "")).replace("{f}", extension)
    if "{" in url or "}" in url:
        raise EvidenceError("artwork URL contains unsupported placeholders")
    return validate_apple_media_url(url), width, height


def device_family(key: str, shelf: Mapping[str, Any]) -> str:
    metadata = shelf.get("contentsMetadata")
    platform = metadata.get("platform") if isinstance(metadata, Mapping) else None
    raw = str(platform.get("appPlatform") or "").strip().lower() if isinstance(platform, Mapping) else ""
    aliases = {"iphone": "phone", "pad": "tablet", "ipad": "tablet"}
    if raw:
        return aliases.get(raw, raw)
    tokens = [token for token in re.split(r"[^a-z0-9.-]+", str(shelf.get("id") or key).lower()) if token]
    for marker in ("media", "platform", "screenshots", "screenshot", "gallery"):
        if marker in tokens and tokens.index(marker) + 1 < len(tokens):
            value = tokens[tokens.index(marker) + 1]
            return aliases.get(value, value)
    return "other"


def media_shelves(payload: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    mapping = payload.get("shelfMapping")
    if not isinstance(mapping, Mapping):
        return []
    ordered: list[str] = []
    orderings = payload.get("shelfOrderings")
    if isinstance(orderings, Mapping):
        for name in ("notPurchasedOrdering", "purchasedOrdering", "notPurchasedOrdering_Compact", "purchasedOrdering_Compact"):
            values = orderings.get(name)
            if isinstance(values, list):
                for item in values:
                    if str(item) not in ordered:
                        ordered.append(str(item))
    for key in mapping:
        if str(key) not in ordered:
            ordered.append(str(key))
    shelves: list[tuple[str, Mapping[str, Any]]] = []
    for key in ordered:
        shelf = mapping.get(key)
        if not isinstance(shelf, Mapping):
            continue
        metadata = shelf.get("contentsMetadata")
        shelf_id = str(shelf.get("id") or key).lower()
        items = shelf.get("items")
        if (shelf_id.startswith("product_media_") or (isinstance(metadata, Mapping) and str(metadata.get("type") or "") == "productMedia")) and isinstance(items, list) and any(isinstance(item, Mapping) and isinstance(item.get("screenshot"), Mapping) for item in items):
            shelves.append((device_family(key, shelf), shelf))
    return shelves


def parse_apple_page(requested_url: str, final_url: str, content_type: str, body: bytes) -> dict[str, Any]:
    requested_id, final_id = app_id(requested_url), app_id(final_url)
    if not requested_id or requested_id != final_id:
        raise EvidenceError("final Apple URL did not preserve the requested App ID")
    collector = ScriptCollector()
    collector.feed(body.decode("utf-8"))
    serialized = collector.scripts.get("serialized-server-data")
    if content_type not in ALLOWED_PAGE_TYPES or not serialized:
        raise EvidenceError("official Apple product data is missing")
    intent, payload = target_payload(json.loads(serialized), requested_id)
    storefront, language = str(intent.get("storefront") or "").strip().lower(), str(intent.get("language") or "").strip()
    lockup = payload.get("lockup")
    if not storefront or not language or not isinstance(lockup, Mapping) or str(lockup.get("adamId") or "") != requested_id:
        raise EvidenceError("target App identity or locale metadata is incomplete")
    canonical = str(payload.get("canonicalURL") or "").strip()
    if app_id(canonical) != requested_id or str(urlsplit(canonical).hostname or "").lower() != "apps.apple.com":
        raise EvidenceError("canonical URL did not match the requested App ID")
    name = str(lockup.get("title") or "").strip()
    if not name:
        raise EvidenceError("target App name is missing")
    icon = None
    if isinstance(lockup.get("icon"), Mapping):
        url, width, height = artwork_url(lockup["icon"])
        icon = Artwork("app_icon", 0, None, None, url, width, height)
    screenshots: list[Artwork] = []
    global_ordinal, families = 0, []
    for family, shelf in media_shelves(payload):
        if family not in families:
            families.append(family)
        family_ordinal = 0
        for item in shelf.get("items", []):
            shot = item.get("screenshot") if isinstance(item, Mapping) else None
            if isinstance(shot, Mapping):
                url, width, height = artwork_url(shot)
                screenshots.append(Artwork("app_screenshot", global_ordinal, family, family_ordinal, url, width, height))
                global_ordinal += 1
                family_ordinal += 1
    return {"provider": "apple_app_store", "store_app_id": requested_id, "name": name, "bundle_id": str(lockup.get("bundleId") or "").strip() or None, "storefront": storefront, "language": language, "canonical_url": canonical, "icon": icon, "screenshots": screenshots, "screenshot_device_families": families}


def _google_name(collector: GooglePageCollector) -> str:
    structured = next(
        (
            item
            for item in collector.json_ld
            if str(item.get("@type") or "").lower()
            in {"softwareapplication", "mobileapplication", "application"}
        ),
        {},
    )
    raw = (
        collector.semantic_name
        or collector.meta.get("appstore:name")
        or str(structured.get("name") or "").strip()
        or collector.meta.get("og:title")
        or collector.meta.get("twitter:title")
        or collector.meta.get("name")
        or collector.title
    ).strip()
    if not raw:
        raise EvidenceError("target App name is missing")
    cleaned = re.sub(r"\s+-\s+Apps on Google Play\s*$", "", raw, flags=re.IGNORECASE).strip()
    if cleaned == raw and re.search(r"\s+-\s+.*(?:Google Play|Play Store)", raw, re.IGNORECASE):
        cleaned = re.split(r"\s+-\s+", raw, maxsplit=1)[0].strip()
    return cleaned or raw


def _google_structured_image(collector: GooglePageCollector) -> str:
    for item in collector.json_ld:
        kind = str(item.get("@type") or "").lower()
        if kind not in {"softwareapplication", "mobileapplication", "application"}:
            continue
        image = item.get("image")
        if isinstance(image, str) and image.strip():
            return image.strip()
        if isinstance(image, list):
            for candidate in image:
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
    return ""


def _google_family_for_screenshot(
    item: Mapping[str, str | None], _collector: GooglePageCollector
) -> str:
    explicit = str(item.get("device_family") or "").strip()
    if explicit:
        return _normalize_device_family(explicit)
    # The visible Google form-factor selector is not a reliable parent for
    # the static screenshot gallery (it can belong to reviews/device filters).
    # Preserve the unknown value instead of inferring phone/tablet from it.
    return "other"


def parse_google_page(requested_url: str, final_url: str, content_type: str, body: bytes) -> dict[str, Any]:
    requested_id, final_id = google_app_id(requested_url), google_app_id(final_url)
    if not requested_id or requested_id != final_id:
        raise EvidenceError("final Google Play URL did not preserve the requested package id")
    if content_type not in ALLOWED_PAGE_TYPES:
        raise EvidenceError("official Google Play product data is missing")

    body_text = body.decode("utf-8")
    collector = GooglePageCollector()
    collector.feed(body_text)
    declared_bundle = (
        collector.meta.get("appstore:bundle_id")
        or collector.meta.get("appstore:store_id")
        or ""
    ).strip()
    if declared_bundle and declared_bundle != requested_id:
        raise EvidenceError("page did not contain the requested target App")

    canonical = (collector.canonical_url or "").strip()
    if not canonical:
        canonical = urlunsplit(
            (
                "https",
                "play.google.com",
                "/store/apps/details",
                f"id={requested_id}",
                "",
            )
        )
    try:
        canonical = validate_google_page_url(canonical)
    except EvidenceError as exc:
        raise EvidenceError("canonical URL did not match the requested Google Play package id") from exc
    canonical_id = google_app_id(canonical)
    canonical_parts = [part for part in urlsplit(canonical).path.split("/") if part]
    canonical_path_ok = (
        len(canonical_parts) in {3, 4}
        and [part.lower() for part in canonical_parts[:3]] == ["store", "apps", "details"]
    )
    if (
        str(urlsplit(canonical).hostname or "").rstrip(".").lower() != "play.google.com"
        or not canonical_path_ok
        or canonical_id != requested_id
    ):
        raise EvidenceError("canonical URL did not match the requested Google Play package id")

    warnings: list[str] = []
    storefront_raw = _query_value(requested_url, "gl") or _query_value(final_url, "gl")
    if storefront_raw and re.fullmatch(r"[A-Za-z]{2}", storefront_raw) and storefront_raw.upper() not in {"XX", "ZZ"}:
        storefront = storefront_raw.lower()
    else:
        storefront = "default"
        if storefront_raw:
            warnings.append("Google Play storefront parameter was not a two-letter country code")
        else:
            warnings.append("Google Play page did not expose an explicit storefront; preserved as default")
    language = _normalize_language(
        collector.html_language
        or _query_value(canonical, "hl")
        or _query_value(final_url, "hl")
        or _query_value(requested_url, "hl")
        or "en"
    )
    if not storefront or not language:
        raise EvidenceError("target App storefront or locale metadata is incomplete")

    icon_candidates: list[str] = []
    for value in (
        collector.meta.get("og:image"),
        collector.meta.get("twitter:image"),
        _google_structured_image(collector),
        *collector.icon_candidates,
    ):
        candidate = str(value or "").strip()
        if candidate and candidate not in icon_candidates:
            icon_candidates.append(candidate)
    icon = None
    for candidate in icon_candidates:
        try:
            validated = validate_google_media_url(candidate)
        except EvidenceError:
            continue
        width, height = _google_declared_dimensions(validated, icon=True)
        icon = Artwork("app_icon", 0, None, None, validated, width, height)
        break
    if icon_candidates and icon is None:
        raise EvidenceError("Google Play icon metadata did not bind to official artwork")

    screenshots: list[Artwork] = []
    raw_screenshots = list(collector.screenshots)
    ds_screenshots = _google_ds5_screenshots(body_text, requested_id)
    if ds_screenshots:
        if raw_screenshots and len(ds_screenshots) == len(raw_screenshots):
            # The DOM owns target binding/order; ds:5 supplies original
            # dimensions and unsized CDN tokens for pixel truth.
            for item, (source, width, height) in zip(raw_screenshots, ds_screenshots):
                item["source"] = source
                item["declared_width"] = str(width)
                item["declared_height"] = str(height)
        elif not raw_screenshots:
            raw_screenshots = [
                {
                    "source": source,
                    "index": str(index),
                    "device_family": None,
                    "declared_width": str(width),
                    "declared_height": str(height),
                }
                for index, (source, width, height) in enumerate(ds_screenshots)
            ]
    indexed: list[tuple[int, dict[str, str | None]]] = []
    if raw_screenshots and all(str(item.get("index") or "").isdigit() for item in raw_screenshots):
        indexed = sorted((int(str(item["index"])), item) for item in raw_screenshots)
        indexes = [index for index, _ in indexed]
        if len(set(indexes)) != len(indexes):
            raise EvidenceError("Google Play screenshot indexes are duplicated")
        raw_screenshots = [item for _, item in indexed]

    families: list[str] = []
    unknown_family = False
    for global_ordinal, item in enumerate(raw_screenshots):
        source = str(item.get("source") or "").strip()
        if not source:
            raise EvidenceError("Google Play screenshot metadata is missing an image URL")
        source = validate_google_media_url(source)
        declared_width = str(item.get("declared_width") or "").strip()
        declared_height = str(item.get("declared_height") or "").strip()
        if declared_width.isdigit() and declared_height.isdigit():
            width, height = int(declared_width), int(declared_height)
        else:
            width, height = _google_declared_dimensions(source)
        family = _google_family_for_screenshot(item, collector)
        unknown_family = unknown_family or family == "other"
        if family not in families:
            families.append(family)
        family_ordinal = sum(1 for existing in screenshots if existing.device_family == family)
        screenshots.append(
            Artwork(
                "app_screenshot",
                global_ordinal,
                family,
                family_ordinal,
                source,
                width,
                height,
            )
        )

    if unknown_family:
        warnings.append("Google Play did not bind screenshots to a device family; preserved as other")
    bundle = {
        "provider": "google_play",
        "store_app_id": requested_id,
        "name": _google_name(collector),
        "bundle_id": declared_bundle or requested_id,
        "storefront": storefront,
        "language": language,
        "canonical_url": canonical,
        "icon": icon,
        "screenshots": screenshots,
        "screenshot_device_families": families,
        "warnings": warnings,
        "description": collector.meta.get("og:description")
        or collector.meta.get("description")
        or str(
            next(
                (
                    item.get("description")
                    for item in collector.json_ld
                    if isinstance(item.get("description"), str)
                ),
                "",
            )
        ),
    }
    return bundle


def parse_page(requested_url: str, final_url: str, content_type: str, body: bytes) -> dict[str, Any]:
    provider = _provider_for_url(requested_url)
    if provider == "google_play":
        return parse_google_page(requested_url, final_url, content_type, body)
    return parse_apple_page(requested_url, final_url, content_type, body)


def download_artwork(art: Artwork, output_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    host = str(urlsplit(art.source_url).hostname or "").rstrip(".").lower()
    is_google = host in GOOGLE_MEDIA_HOSTS
    media_url = _google_artwork_request_url(art.source_url) if is_google else art.source_url
    validator = validate_google_media_url if is_google else validate_apple_media_url
    _, final, content_type, body = fetch(media_url, validator=validator, accept="image/webp,image/png,image/jpeg,*/*;q=0.1", allowed_types=ALLOWED_IMAGE_TYPES, max_bytes=args.max_media_bytes, timeout=args.timeout, max_redirects=args.max_redirects)
    try:
        with Image.open(BytesIO(body)) as image:
            image.verify()
        with Image.open(BytesIO(body)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError) as exc:
        raise EvidenceError("official artwork is not a valid image") from exc
    if art.media_role == "app_icon" and width != height:
        raise EvidenceError("official App icon must be square")
    extension = {"image/png": ".png", "image/webp": ".webp"}.get(content_type, ".jpg")
    base = "icon_000" if art.media_role == "app_icon" else f"screenshot_{art.store_media_ordinal:03d}"
    relative = Path("media") / f"{base}{extension}"
    path = output_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    record = asdict(art)
    record.update({"final_url": final, "content_type": content_type, "width": width, "height": height, "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "file_path": relative.as_posix()})
    record.pop("declared_width")
    record.pop("declared_height")
    return record


def build_bundle(
    *,
    requested_url: str,
    final_url: str,
    page_body: bytes,
    parsed: Mapping[str, Any],
    media: list[dict[str, Any]],
    metadata_only: bool,
) -> dict[str, Any]:
    """Normalize either provider's parsed data into contract v1."""
    icon_art = parsed.get("icon")
    icon_record = None
    if metadata_only and isinstance(icon_art, Artwork):
        icon_record = asdict(icon_art)
        icon_record["width"] = icon_record.pop("declared_width")
        icon_record["height"] = icon_record.pop("declared_height")
    elif not metadata_only:
        icon_record = next((item for item in media if item.get("media_role") == "app_icon"), None)
    if metadata_only:
        screenshots = [
            {
                **{
                    key: value
                    for key, value in asdict(item).items()
                    if key not in {"declared_width", "declared_height"}
                },
                "width": item.declared_width,
                "height": item.declared_height,
            }
            for item in parsed.get("screenshots", [])
            if isinstance(item, Artwork)
        ]
    else:
        screenshots = [
            item for item in media if item.get("media_role") == "app_screenshot"
        ]
    has_icon = icon_art is not None
    has_screenshots = bool(parsed.get("screenshots"))
    mode = (
        "metadata_only"
        if metadata_only or not has_icon and not has_screenshots
        else "icon_only"
        if has_icon and not has_screenshots
        else "replacement_pixels"
    )
    bundle = {
        "contract": "app-store-evidence",
        "contract_version": 1,
        "provider": parsed["provider"],
        "requested_url": requested_url,
        "final_url": final_url,
        "canonical_url": parsed["canonical_url"],
        "store_app_id": parsed["store_app_id"],
        "name": parsed["name"],
        "bundle_id": parsed.get("bundle_id"),
        "storefront": parsed["storefront"],
        "language": parsed["language"],
        "page_sha256": hashlib.sha256(page_body).hexdigest(),
        "pixel_truth_mode": mode,
        "icon": icon_record,
        "screenshots": screenshots,
        "screenshot_device_families": list(parsed.get("screenshot_device_families") or []),
        "warnings": [
            *[str(item) for item in parsed.get("warnings") or [] if item],
            *(["media download skipped by caller"] if metadata_only and (has_icon or has_screenshots) else []),
        ],
    }
    if parsed.get("description"):
        bundle["description"] = str(parsed["description"])
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse an official Apple App Store or Google Play product URL into a validated evidence bundle.")
    parser.add_argument("url")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-redirects", type=int, default=5)
    parser.add_argument("--max-page-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--max-media-bytes", type=int, default=20 * 1024 * 1024)
    # Google Play can publish more than thirty ordered screenshots across a
    # product page; keep a finite budget but do not reject common pages merely
    # because Apple's older default was smaller.
    parser.add_argument("--max-media-count", type=int, default=60)
    args = parser.parse_args()
    try:
        normalized_url = validate_store_page_url(args.url)
        requested, final, content_type, body = fetch(normalized_url, validator=validate_store_page_url, accept="text/html,text/plain;q=0.8,*/*;q=0.1", allowed_types=ALLOWED_PAGE_TYPES, max_bytes=args.max_page_bytes, timeout=args.timeout, max_redirects=args.max_redirects)
        parsed = parse_page(requested, final, content_type, body)
        artworks = ([parsed["icon"]] if parsed["icon"] else []) + parsed["screenshots"]
        if len(artworks) > args.max_media_count:
            raise EvidenceError("official media count exceeds the ingestion budget; refusing to truncate")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        media = [] if args.metadata_only else [download_artwork(item, args.output_dir, args) for item in artworks]
        bundle = build_bundle(requested_url=requested, final_url=final, page_body=body, parsed=parsed, media=media, metadata_only=args.metadata_only)
        output = args.output_dir / "app_store_evidence_bundle.json"
        output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(str(output))
        return 0
    except (EvidenceError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
