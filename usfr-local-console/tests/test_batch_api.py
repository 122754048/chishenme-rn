import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import HttpCommercialBatchDispatcher, create_app
from app.jobs import FileJobStore
from app.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    skill = tmp_path / "SKILL.md"
    skill.write_text("skill", encoding="utf-8")
    return Settings(
        host="127.0.0.1",
        port=8765,
        data_root=tmp_path / "data",
        skill_path=skill,
        skill_sha256=hashlib.sha256(b"skill").hexdigest(),
        runninghub_api_key=None,
    )


def _row(row_id: str) -> dict[str, object]:
    return {
        "row_id": row_id,
        "slots": {"source_video": f"uploads/batch/{row_id}/source.mp4"},
        "extensions": {"background_music": None},
        "output_language": "de",
        "opaque_audio_policy": {},
    }


class _BatchDispatcher:
    def __init__(self) -> None:
        self.submitted: list[list[dict[str, object]]] = []
        self.retried: list[tuple[str, str]] = []

    def preflight(self, rows):
        return [{"row_id": row["row_id"], "status": "ready", "route": "language_only"} for row in rows]

    def submit(self, rows):
        self.submitted.append(rows)
        return {"batch_id": "batch-01", "rows": [{"row_id": row["row_id"], "status": "queued"} for row in rows]}

    def get_batch(self, batch_id):
        return {"batch_id": batch_id, "rows": [{"row_id": "one", "status": "queued"}]}

    def retry_row(self, batch_id, row_id):
        self.retried.append((batch_id, row_id))
        return {"batch_id": batch_id, "row_id": row_id, "status": "resumed"}

    def result_index(self, batch_id):
        return {"batch_id": batch_id, "items": [{"row_id": "one", "result": None}]}


def test_batch_api_uses_only_an_injected_commercial_dispatcher(tmp_path):
    settings = _settings(tmp_path)
    dispatcher = _BatchDispatcher()
    app = create_app(
        settings=settings,
        store=FileJobStore(settings.data_root),
        batch_dispatcher=dispatcher,
        probe_duration=lambda _: 5,
    )
    client = TestClient(app)

    preflight = client.post("/api/batches/preflight", json={"rows": [_row("one"), _row("two")]})
    submitted = client.post("/api/batches", json={"rows": [_row("one"), _row("two")]})
    retried = client.post("/api/batches/batch-01/rows/one/retry")
    index = client.get("/api/batches/batch-01/results-index")

    assert preflight.status_code == 200
    assert [row["row_id"] for row in preflight.json()["rows"]] == ["one", "two"]
    assert submitted.status_code == 202
    assert dispatcher.submitted == [[_row("one"), _row("two")]]
    assert retried.json()["status"] == "resumed"
    assert dispatcher.retried == [("batch-01", "one")]
    assert index.json()["items"][0]["row_id"] == "one"


def test_unconfigured_console_refuses_commercial_batch_submission(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings=settings, store=FileJobStore(settings.data_root), probe_duration=lambda _: 5)

    response = TestClient(app).post("/api/batches", json={"rows": [_row("one")]})

    assert response.status_code == 503
    assert response.json()["code"] == "COMMERCIAL_BATCH_RUNTIME_NOT_CONFIGURED"


def test_batch_manifest_upload_accepts_json_and_csv_for_preflight(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(
        settings=settings,
        store=FileJobStore(settings.data_root),
        batch_dispatcher=_BatchDispatcher(),
        probe_duration=lambda _: 5,
    )
    client = TestClient(app)

    json_response = client.post(
        "/api/batches/manifest/preflight",
        files={"manifest": ("batch.json", json.dumps({"rows": [_row("json")]}), "application/json")},
    )
    csv_response = client.post(
        "/api/batches/manifest/preflight",
        files={
            "manifest": (
                "batch.csv",
                "row_id,source_video,output_language,background_music\n"
                "csv,uploads/batch/csv/source.mp4,de,\n",
                "text/csv",
            )
        },
    )

    assert json_response.status_code == 200
    assert json_response.json()["rows"] == [{"row_id": "json", "status": "ready", "route": "language_only"}]
    assert csv_response.status_code == 200
    assert csv_response.json()["rows"] == [{"row_id": "csv", "status": "ready", "route": "language_only"}]


def test_batch_manifest_upload_submits_only_to_injected_dispatcher(tmp_path):
    settings = _settings(tmp_path)
    dispatcher = _BatchDispatcher()
    app = create_app(
        settings=settings,
        store=FileJobStore(settings.data_root),
        batch_dispatcher=dispatcher,
        probe_duration=lambda _: 5,
    )

    response = TestClient(app).post(
        "/api/batches/manifest",
        files={"manifest": ("batch.json", json.dumps({"rows": [_row("one")]}), "application/json")},
    )

    assert response.status_code == 202
    assert response.json()["batch_id"] == "batch-01"
    assert dispatcher.submitted == [[_row("one")]]


def test_http_commercial_batch_dispatcher_builds_a_real_http_request():
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _size):
            return b'{"rows":[{"row_id":"one","status":"ready"}]}'

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    dispatcher = HttpCommercialBatchDispatcher("http://batch.test/api/batches", opener=opener)

    assert dispatcher.preflight([_row("one")]) == [{"row_id": "one", "status": "ready"}]
    assert captured["request"].full_url == "http://batch.test/api/batches/preflight"
    assert captured["request"].get_method() == "POST"
