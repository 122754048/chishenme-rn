from __future__ import annotations

from collections.abc import Callable

from .batch_manifest import BatchManifestError, BatchRow, parse_batch_manifest


class BatchScheduler:
    CAPABILITY_QUEUES = (
        "probe_dynamics",
        "asr_localization",
        "storyboard_generation",
        "provider_poll",
        "assembly_qc",
    )

    def __init__(
        self,
        *,
        create_job: Callable[[BatchRow], str],
        resume_known_job: Callable[[str], None] | None = None,
    ) -> None:
        self._create_job = create_job
        self._resume_known_job = resume_known_job
        self._source_analysis_claims: set[tuple[str, str]] = set()

    def submit_rows(self, rows: list[BatchRow | dict[str, object]]) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for raw in rows:
            try:
                row = raw if isinstance(raw, BatchRow) else parse_batch_manifest([raw])[0]
                job_id = self._create_job(row)
            except (BatchManifestError, ValueError) as error:
                row_id = raw.row_id if isinstance(raw, BatchRow) else str(raw.get("row_id") or "") if isinstance(raw, dict) else ""
                results.append({"row_id": row_id, "status": "rejected", "error": str(error)})
            except Exception as error:
                results.append({"row_id": row.row_id, "status": "failed", "error": str(error)})
            else:
                results.append({"row_id": row.row_id, "status": "queued", "job_id": job_id})
        return results

    def claim_source_analysis(self, job_id: str, source_sha256: str) -> bool:
        key = (job_id, source_sha256)
        if key in self._source_analysis_claims:
            return False
        self._source_analysis_claims.add(key)
        return True

    def resume_row(self, job_id: str) -> None:
        if self._resume_known_job is None:
            raise ValueError("BATCH_RESUME_UNAVAILABLE")
        self._resume_known_job(job_id)
