from pathlib import Path


def test_delivered_video_uses_its_direct_final_url_without_job_history():
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "function renderDelivery(job)" in source
    assert "job.final_video_url" in source
    assert "renderDelivery(job);" in source

