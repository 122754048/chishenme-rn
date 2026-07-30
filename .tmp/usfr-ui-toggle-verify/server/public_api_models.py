from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, HttpUrl, model_validator


SUPPORTED_OUTPUT_LANGUAGES = ("en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh")


class PublicJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_video: HttpUrl
    new_product_images: tuple[HttpUrl, ...] = ()
    new_model_images: tuple[HttpUrl, ...] = ()
    ui_screenshots: tuple[HttpUrl, ...] = ()
    app_store_url: HttpUrl | None = None
    ui_operation_video: HttpUrl | None = None
    tail_video: HttpUrl | None = None
    audio: HttpUrl | None = None
    output_language: Literal["en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh"] | None = None

    @model_validator(mode="after")
    def require_change_input(self) -> "PublicJobCreate":
        if not any(
            (
                self.new_product_images,
                self.new_model_images,
                self.ui_screenshots,
                self.app_store_url,
                self.ui_operation_video,
                self.tail_video,
                self.audio,
                self.output_language,
            )
        ):
            raise ValueError("at least one change input is required")
        return self

    def canonical_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True, exclude_defaults=True)


class PublicReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "revise"]
    content: str | None = None

    @model_validator(mode="after")
    def validate_content(self) -> "PublicReviewRequest":
        content = self.content.strip() if isinstance(self.content, str) else None
        if self.action == "revise" and not content:
            raise ValueError("content is required when action is revise")
        if self.action == "approve" and content is not None:
            raise ValueError("content is not allowed when action is approve")
        self.content = content
        return self


__all__ = ["PublicJobCreate", "PublicReviewRequest", "SUPPORTED_OUTPUT_LANGUAGES"]
