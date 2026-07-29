"""Lightweight application service backed only by the ephemeral JobStore."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any, Mapping

from .errors import ReplicationError, ReviewNotApplicableError
from .review_models import RevisionManifest, RevisionRequest
from .review_workflow import downstream_invalidations


class ReplicationService:
    """Review and Provider authority for one temporary video-generation job."""

    def __init__(self, *, job_store: Any, review_ttl_seconds: int = 3600) -> None:
        if job_store is None:
            raise ValueError("job_store is required")
        if isinstance(review_ttl_seconds, bool) or not isinstance(review_ttl_seconds, int) or review_ttl_seconds <= 0:
            raise ValueError("review_ttl_seconds must be positive")
        self.job_store = job_store
        self.review_ttl_seconds = review_ttl_seconds

    def _snapshot(self, job_id: str):
        snapshot = self.job_store.get_job(job_id)
        if snapshot is None:
            raise ReplicationError("JOB_GONE", "job is no longer available", http_status=410)
        return snapshot

    def _review_snapshot(self, job_id: str):
        snapshot = self._snapshot(job_id)
        if snapshot.review_route == "local_only":
            raise ReviewNotApplicableError()
        return snapshot

    def list_script_revisions(self, job_id: str) -> tuple[RevisionManifest, ...]:
        self._review_snapshot(job_id)
        return self.job_store.list_revisions(job_id, "script")

    def list_storyboard_revisions(self, job_id: str) -> tuple[RevisionManifest, ...]:
        self._review_snapshot(job_id)
        return self.job_store.list_revisions(job_id, "storyboard")

    def request_script_revision(self, job_id: str, *, expected_version: int, request: RevisionRequest):
        del request
        self._review_snapshot(job_id)
        return self.job_store.cas_transition(
            job_id=job_id,
            expected_version=expected_version,
            command="request_script_revision",
            updates={
                "review_route": "route_2",
                "approved_storyboard_sha256": None,
                "current_storyboard_revision": None,
                "state": "SCRIPT_AWAITING_APPROVAL",
            },
            invalidate=downstream_invalidations("script"),
            ttl_seconds=self.review_ttl_seconds,
        )

    def complete_script_revision(self, job_id: str, *, expected_version: int, manifest: RevisionManifest):
        self._review_snapshot(job_id)
        return self.job_store.append_revision(
            job_id=job_id,
            kind="script",
            expected_version=expected_version,
            manifest=manifest,
            invalidate_downstream=True,
            ttl_seconds=self.review_ttl_seconds,
        )

    def approve_script_revision(
        self,
        job_id: str,
        *,
        revision: int,
        expected_version: int,
        expected_sha256: str,
        line_contracts: Sequence[Mapping[str, Any]] | None = None,
        source_content_timeline_sha256: str | None = None,
        visible_text_locks: Sequence[Mapping[str, Any]] | None = None,
        visible_text_locks_sha256: str | None = None,
    ):
        self._review_snapshot(job_id)
        if (line_contracts is None) != (source_content_timeline_sha256 is None):
            raise ReplicationError(
                "INVALID_INPUT",
                "line_contracts and source_content_timeline_sha256 must be supplied together",
            )
        if (visible_text_locks is None) != (visible_text_locks_sha256 is None):
            raise ReplicationError(
                "INVALID_INPUT",
                "visible_text_locks and visible_text_locks_sha256 must be supplied together",
            )
        if source_content_timeline_sha256 is not None and visible_text_locks is None:
            raise ReplicationError(
                "INVALID_INPUT",
                "frozen timeline script approval requires visible_text_locks and visible_text_locks_sha256",
            )
        if source_content_timeline_sha256 is None and visible_text_locks is not None:
            raise ReplicationError(
                "INVALID_INPUT",
                "visible_text_locks require source_content_timeline_sha256",
            )
        list_artifacts = getattr(self.job_store, "list_artifacts", None)
        artifacts = list_artifacts(job_id) if callable(list_artifacts) else ()
        source_audio_kinds = {
            str(getattr(item, "kind", "") or "")
            for item in artifacts
        } & {"performance_audio_source_contract", "audio_lyrics_beat_contract"}
        if source_audio_kinds and source_audio_kinds != {
            "performance_audio_source_contract",
            "audio_lyrics_beat_contract",
        }:
            raise ReplicationError(
                "INVALID_INPUT",
                "source-audio evidence artifacts must be present as an atomic pair",
            )
        if source_audio_kinds and line_contracts is None:
            raise ReplicationError(
                "INVALID_INPUT",
                "source-audio script approval requires line_contracts and source_content_timeline_sha256",
            )
        script_approval = None
        if line_contracts is not None:
            try:
                from scripts.line_contract import validate_line_contracts

                canonical_lines = validate_line_contracts(line_contracts)
                raw = json.dumps(
                    canonical_lines,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            except Exception as exc:
                raise ReplicationError(
                    "INVALID_INPUT",
                    "line_contracts must be canonical confirmed line contracts",
                    details={"reason": str(exc)},
                ) from exc
            try:
                from server.visible_text_contract import canonicalize_visible_text_locks, visible_text_locks_sha256 as locks_sha256

                canonical_visible_text_locks = canonicalize_visible_text_locks(visible_text_locks or [])
                canonical_visible_text_locks_sha256 = locks_sha256(canonical_visible_text_locks)
            except Exception as exc:
                raise ReplicationError(
                    "INVALID_INPUT",
                    "visible_text_locks must be canonical visible text locks",
                    details={"reason": str(exc)},
                ) from exc
            if visible_text_locks_sha256 != canonical_visible_text_locks_sha256:
                raise ReplicationError(
                    "INVALID_INPUT",
                    "visible_text_locks_sha256 does not match canonical visible_text_locks",
                )
            script_approval = {
                "contract": "approved-script-lines/v1",
                "revision": revision,
                "script_sha256": expected_sha256,
                "source_content_timeline_sha256": source_content_timeline_sha256,
                "line_contracts": canonical_lines,
                "line_contracts_sha256": hashlib.sha256(raw).hexdigest(),
                "visible_text_locks": canonical_visible_text_locks,
                "visible_text_locks_sha256": canonical_visible_text_locks_sha256,
            }
        return self.job_store.approve_revision(
            job_id=job_id,
            kind="script",
            revision=revision,
            expected_version=expected_version,
            expected_sha256=expected_sha256,
            script_approval=script_approval,
            ttl_seconds=self.review_ttl_seconds,
        )

    def request_storyboard_revision(self, job_id: str, *, expected_version: int, request: RevisionRequest):
        del request
        self._review_snapshot(job_id)
        return self.job_store.cas_transition(
            job_id=job_id,
            expected_version=expected_version,
            command="request_storyboard_revision",
            updates={},
            invalidate=downstream_invalidations("storyboard"),
            ttl_seconds=self.review_ttl_seconds,
        )

    def complete_storyboard_revision(self, job_id: str, *, expected_version: int, manifest: RevisionManifest):
        self._review_snapshot(job_id)
        return self.job_store.append_revision(
            job_id=job_id,
            kind="storyboard",
            expected_version=expected_version,
            manifest=manifest,
            invalidate_downstream=True,
            ttl_seconds=self.review_ttl_seconds,
        )

    def approve_storyboard_revision(self, job_id: str, *, revision: int, expected_version: int, expected_sha256: str):
        self._review_snapshot(job_id)
        return self.job_store.approve_revision(
            job_id=job_id,
            kind="storyboard",
            revision=revision,
            expected_version=expected_version,
            expected_sha256=expected_sha256,
            ttl_seconds=self.review_ttl_seconds,
        )

    def touch_review_ttl(self, job_id: str):
        self._review_snapshot(job_id)
        return self.job_store.touch_review_ttl(job_id, self.review_ttl_seconds)

    def begin_provider_attempt(
        self,
        *,
        job_id: str,
        expected_version: int,
        operation: str,
        request_sha256: str,
        segment_id: str | None = None,
        segment_plan_sha256: str | None = None,
    ):
        return self.job_store.begin_provider_attempt(
            job_id=job_id,
            expected_version=expected_version,
            operation=operation,
            request_sha256=request_sha256,
            segment_id=segment_id,
            segment_plan_sha256=segment_plan_sha256,
        )

    def update_provider_attempt(self, *, job_id: str, expected_version: int, attempt: Any):
        return self.job_store.update_provider_attempt(
            job_id=job_id,
            expected_version=expected_version,
            attempt=attempt,
            ttl_seconds=self.review_ttl_seconds,
        )

    def current_authority(self, job_id: str) -> Mapping[str, Any]:
        snapshot = self._snapshot(job_id)
        return {
            "approved_script_sha256": snapshot.approved_script_sha256,
            "approved_storyboard_sha256": snapshot.approved_storyboard_sha256,
            "slots_manifest": snapshot.slots_manifest,
        }


__all__ = ["ReplicationService"]
