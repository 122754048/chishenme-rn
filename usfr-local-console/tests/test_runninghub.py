from pathlib import Path

from app.jobs import FileJobStore
from app.runninghub import HttpRunningHubTransport, RunningHubGateway
from app.slots import build_intake, validate_intake


class FakeTransport:
    def __init__(self):
        self.create_calls = 0
        self.query_calls: list[str] = []

    def create(self, request):
        self.create_calls += 1
        return {"task_id": "created-task", "status": "SUBMITTED"}

    def query(self, task_id):
        self.query_calls.append(task_id)
        return {"task_id": task_id, "status": "SUCCESS", "output_url": "https://provider.example/result.mp4"}

    def download(self, url):
        return b"video-result"


def create_job(store: FileJobStore, temp_dir: Path):
    temp_dir.mkdir(parents=True, exist_ok=True)
    source = temp_dir / "source.mp4"
    source.write_bytes(b"source")
    return store.create(
        validate_intake(build_intake(source_video=source, output_language="fr"), probe_duration=lambda _: 5)
    )


def test_submit_once_never_calls_create_twice_for_same_request(tmp_path):
    store = FileJobStore(tmp_path / "data")
    transport = FakeTransport()
    gateway = RunningHubGateway(store, transport)
    job = create_job(store, tmp_path)
    request = {"workflow_id": "123", "payload": {"prompt": "x"}}

    attempt = gateway.submit_once(job.job_id, job.version, request)
    recovered = gateway.submit_once(job.job_id, attempt.job_version, request)

    assert transport.create_calls == 1
    assert recovered.task_id == attempt.task_id


def test_restart_polls_known_task_without_creating_a_new_one(tmp_path):
    store = FileJobStore(tmp_path / "data")
    transport = FakeTransport()
    gateway = RunningHubGateway(store, transport)
    job = create_job(store, tmp_path)
    saved = gateway.record_known_attempt(
        job.job_id,
        job.version,
        request_sha256="a" * 64,
        task_id="known",
        status="RUNNING",
    )

    result = gateway.poll_existing(job.job_id, saved.version)

    assert transport.create_calls == 0
    assert transport.query_calls == ["known"]
    assert result.status == "SUCCESS"


def test_http_transport_uses_the_documented_runninghub_submit_and_query_contract():
    calls = []

    class Response:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, *_): return self.body

    def opener(request, timeout):
        calls.append(request)
        if request.full_url.endswith("/query"):
            return Response(b'{"taskId":"123","status":"SUCCESS","results":[{"url":"https://files.example/result.mp4"}]}')
        return Response(b'{"taskId":"123","status":"RUNNING"}')

    transport = HttpRunningHubTransport("private-key", opener=opener)
    created = transport.create({"workflow_id": "2080140197518823426", "payload": {"nodeInfoList": []}})
    queried = transport.query("123")

    assert created["task_id"] == "123"
    assert queried["output_url"] == "https://files.example/result.mp4"
    assert calls[0].full_url.endswith("/openapi/v2/run/ai-app/2080140197518823426")
    assert calls[1].full_url.endswith("/openapi/v2/query")
