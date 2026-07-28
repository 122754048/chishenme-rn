from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Mapping


# Production workers inject a packaged config path or environment variables.
# Never make an operator's home directory a deployment dependency.
DEFAULT_ENV_FILE: Path | None = None


def resolve_env_file(
    value: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Resolve an explicit worker config path without a local-home fallback."""

    if value is not None and str(value).strip():
        return Path(value).expanduser()
    source = os.environ if environ is None else environ
    configured = source.get("SEEDANCE_ENV_FILE")
    if configured and configured.strip():
        return Path(configured).expanduser()
    return None


class ConfigurationError(RuntimeError):
    pass


def _parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


@dataclass(frozen=True)
class Settings:
    runninghub_api_key: str = field(repr=False)
    runninghub_base_url: str
    runninghub_seedance_api_key: str = field(repr=False)
    runninghub_seedance_create_url: str
    runninghub_seedance_query_url: str
    runninghub_seedance_upload_url: str
    seedance_api_provider: str

    def require_runninghub(self) -> None:
        if not self.runninghub_api_key:
            raise ConfigurationError("Missing configuration: RUNNINGHUB_API_KEY")

    def require_seedance(self) -> None:
        if self.seedance_api_provider != "runninghub_standard":
            raise ConfigurationError("SEEDANCE_API_PROVIDER must be runninghub_standard")
        if not self.runninghub_seedance_api_key:
            raise ConfigurationError("Missing configuration: RUNNINGHUB_SEEDANCE_API_KEY")


def load_settings(
    path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    effective_env = os.environ if environ is None else environ
    resolved = resolve_env_file(path, effective_env)
    file_values = _parse_env(resolved) if resolved is not None else {}
    merged = {**file_values, **dict(effective_env)}

    def value(primary: str, alias: str = "", default: str = "") -> str:
        return merged.get(primary) or (merged.get(alias) if alias else "") or default

    provider = value("SEEDANCE_API_PROVIDER", default="runninghub_standard").lower()

    return Settings(
        runninghub_api_key=value("RUNNINGHUB_API_KEY"),
        runninghub_base_url=value(
            "RUNNINGHUB_BASE_URL",
            default="https://www.runninghub.ai",
        ),
        runninghub_seedance_api_key=value("RUNNINGHUB_SEEDANCE_API_KEY"),
        runninghub_seedance_create_url=value(
            "RUNNINGHUB_SEEDANCE_CREATE_URL",
            default="https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
        ),
        runninghub_seedance_query_url=value(
            "RUNNINGHUB_SEEDANCE_QUERY_URL",
            default="https://www.runninghub.cn/openapi/v2/query",
        ),
        runninghub_seedance_upload_url=value(
            "RUNNINGHUB_SEEDANCE_UPLOAD_URL",
            default="https://www.runninghub.cn/openapi/v2/media/upload/binary",
        ),
        seedance_api_provider=provider,
    )


def build_redacted_provider_preflight(
    path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Report canonical provider configuration readiness without exposing values."""

    effective_env = os.environ if environ is None else environ
    resolved = resolve_env_file(path, effective_env)
    settings = load_settings(path, environ=effective_env)

    return {
        "env_file": (
            "explicit"
            if path is not None and str(path).strip()
            else "injected"
            if resolved is not None
            else "none"
        ),
        "runninghub_api_key": "present" if settings.runninghub_api_key else "missing",
        "runninghub_seedance_api_key": "present" if settings.runninghub_seedance_api_key else "missing",
        "runninghub_base_url": "present" if settings.runninghub_base_url else "missing",
        "seedance_api_provider": (
            "runninghub_standard"
            if settings.seedance_api_provider == "runninghub_standard"
            else "unsupported"
        ),
    }
