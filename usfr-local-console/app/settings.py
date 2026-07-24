from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


DEFAULT_SKILL_PATH = Path(__file__).resolve().parents[2] / "usfr-server" / "SKILL.md"


class SkillChangedError(RuntimeError):
    """Raised when the read-only Skill changes after console startup."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_root: Path
    skill_path: Path
    skill_sha256: str
    runninghub_api_key: str | None
    commercial_batch_api_url: str | None = None
    temporary_job_ttl_seconds: int = 86_400

    @classmethod
    def load(cls) -> "Settings":
        console_root = Path(__file__).resolve().parents[1]
        _load_dotenv(console_root / ".env")
        requested_host = os.environ.get("USFR_CONSOLE_HOST")
        if requested_host and requested_host != "127.0.0.1":
            raise ValueError("USFR_CONSOLE_HOST must be 127.0.0.1")

        configured_root = os.environ.get("USFR_CONSOLE_DATA_ROOT", "./data")
        data_root = Path(configured_root)
        if not data_root.is_absolute():
            data_root = (console_root / data_root).resolve()
        data_root.mkdir(parents=True, exist_ok=True)

        skill_path = Path(os.environ.get("USFR_SKILL_PATH", DEFAULT_SKILL_PATH)).resolve()
        if not skill_path.is_file():
            raise FileNotFoundError(f"USFR Skill file was not found: {skill_path}")

        port = int(os.environ.get("USFR_CONSOLE_PORT", "8765"))
        if not 1 <= port <= 65535:
            raise ValueError("USFR_CONSOLE_PORT must be between 1 and 65535")

        try:
            temporary_job_ttl_seconds = int(os.environ.get("USFR_CONSOLE_TEMP_TTL_SECONDS", "86400"))
        except ValueError as error:
            raise ValueError("USFR_CONSOLE_TEMP_TTL_SECONDS must be a positive integer") from error
        if temporary_job_ttl_seconds <= 0:
            raise ValueError("USFR_CONSOLE_TEMP_TTL_SECONDS must be a positive integer")

        commercial_batch_api_url = (os.environ.get("USFR_COMMERCIAL_BATCH_API_URL") or "").strip()
        if commercial_batch_api_url:
            parsed = urlsplit(commercial_batch_api_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
                raise ValueError("USFR_COMMERCIAL_BATCH_API_URL must be an HTTP(S) API URL without query or fragment")
            commercial_batch_api_url = commercial_batch_api_url.rstrip("/")

        return cls(
            host="127.0.0.1",
            port=port,
            data_root=data_root,
            skill_path=skill_path,
            skill_sha256=sha256_file(skill_path),
            runninghub_api_key=os.environ.get("RUNNINGHUB_API_KEY") or None,
            commercial_batch_api_url=commercial_batch_api_url or None,
            temporary_job_ttl_seconds=temporary_job_ttl_seconds,
        )

    @property
    def skill_baseline(self) -> dict[str, str]:
        return {
            "skill_path": str(self.skill_path),
            "skill_md_sha256": self.skill_sha256,
        }

    def assert_skill_unchanged(self) -> None:
        if sha256_file(self.skill_path) != self.skill_sha256:
            raise SkillChangedError(
                "The console is read-only toward the Skill; restart after reviewing the Skill change."
            )
