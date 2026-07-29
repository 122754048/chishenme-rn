from __future__ import annotations

import json

from server.ui_sidecar_retention import finalize_ui_sidecar_requests


class _Response:
    status = 202

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"purge_after_ms": 86401000}'


def test_finalization_binds_each_sidecar_request_to_the_final_video_sha() -> None:
    requests = []

    def opener(request, *, timeout):
        requests.append((request, timeout))
        return _Response()

    finalize_ui_sidecar_requests(
        render_endpoint="http://127.0.0.1:47821/v1/render",
        api_token="private-token",
        request_sha256s=("a" * 64, "b" * 64),
        final_video_sha256="c" * 64,
        opener=opener,
    )

    assert [item[0].full_url for item in requests] == [
        "http://127.0.0.1:47821/v1/retention/finalized",
        "http://127.0.0.1:47821/v1/retention/finalized",
    ]
    assert all(item[0].get_header("Authorization") == "Bearer private-token" for item in requests)
    assert [json.loads(item[0].data.decode("utf-8")) for item in requests] == [
        {"request_sha256": "a" * 64, "final_video_sha256": "c" * 64},
        {"request_sha256": "b" * 64, "final_video_sha256": "c" * 64},
    ]
