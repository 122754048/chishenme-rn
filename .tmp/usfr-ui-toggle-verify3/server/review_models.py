from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping

ReviewRoute = Literal["route_1", "route_2", "local_only"]
RevisionKind = Literal["script", "storyboard"]
RevisionStatus = Literal["CURRENT", "SUPERSEDED", "APPROVED"]
RevisionMode = Literal["direct_edit", "instruction", "regenerate"]


@dataclass(frozen=True)
class RevisionRequest:
    mode: RevisionMode
    expected_revision: int | None
    changed_cut_ids: tuple[str, ...]
    direct_patch: Mapping[str, Any] | None
    instruction: str | None


@dataclass(frozen=True)
class StoryboardCutRef:
    cut_id: str
    object_key: str
    sha256: str
    width: int
    height: int
    reused_from_revision: int | None = None


@dataclass(frozen=True)
class RevisionManifest:
    kind: RevisionKind
    revision: int
    object_key: str
    sha256: str
    inputs_sha256: str
    created_at: str = ""
    parent_revision: int | None = None
    changed_cut_ids: tuple[str, ...] = ()
    status: RevisionStatus = "CURRENT"
    request: RevisionRequest | None = None
    validation_sha256: str | None = None
    parent_script_sha256: str | None = None
    grid_object_key: str | None = None
    grid_sha256: str | None = None
    cut_images: tuple[StoryboardCutRef, ...] = field(default_factory=tuple)
    reused_cut_ids: tuple[str, ...] = field(default_factory=tuple)
    output_language: str | None = None

    @classmethod
    def script(cls, *, revision: int, object_key: str, sha256: str, inputs_sha256: str) -> "RevisionManifest":
        return cls("script", revision, object_key, sha256, inputs_sha256, status="APPROVED")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
