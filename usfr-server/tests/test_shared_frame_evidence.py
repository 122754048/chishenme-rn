from __future__ import annotations

from dataclasses import dataclass

from server.shared_frame_evidence import SharedFrameEvidenceStore, SharedFrameRef


class MemoryBackend:
    def __init__(self) -> None:
        self.rows = {}

    def get(self, key):
        return self.rows.get(key)

    def put_if_absent(self, key, value):
        self.rows.setdefault(key, value)
        return self.rows[key]


@dataclass
class Source:
    sha256: str = "a" * 64


class Decoder:
    def __init__(self) -> None:
        self.decode_calls = 0

    def decode_and_publish(self, source, *, timestamp_us, roi):
        self.decode_calls += 1
        return SharedFrameRef(
            object_key=f"temporary/frame-{self.decode_calls}.png",
            sha256="b" * 64,
            source_sha256=source.sha256,
            timestamp_us=timestamp_us,
            roi=roi,
        )


def test_same_timestamp_and_roi_are_decoded_once() -> None:
    decoder = Decoder()
    store = SharedFrameEvidenceStore(MemoryBackend(), decoder)
    first = store.get_or_create(Source(), timestamp_us=500_000, roi=None)
    second = store.get_or_create(Source(), timestamp_us=500_000, roi=None)

    assert first.object_key == second.object_key
    assert decoder.decode_calls == 1


def test_different_roi_gets_a_separate_evidence_object() -> None:
    decoder = Decoder()
    store = SharedFrameEvidenceStore(MemoryBackend(), decoder)
    store.get_or_create(Source(), timestamp_us=500_000, roi=None)
    store.get_or_create(Source(), timestamp_us=500_000, roi=(0, 0, 100, 100))

    assert decoder.decode_calls == 2
