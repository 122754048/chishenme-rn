"""Small byte-signature helpers for admitted image media."""

from __future__ import annotations


class UnsupportedImageFormat(ValueError):
    """Raised when encoded bytes are not an admitted image format."""


def detect_image_content_type(data: bytes) -> str:
    """Return the MIME type from encoded bytes, never from a filename."""

    if not isinstance(data, bytes) or not data:
        raise UnsupportedImageFormat("image bytes are empty")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise UnsupportedImageFormat("unsupported encoded image format")


__all__ = ["UnsupportedImageFormat", "detect_image_content_type"]
