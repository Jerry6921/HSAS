from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .define_models import StrictModel


class PdfMetadata(StrictModel):
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    creator: str | None = None
    producer: str | None = None


class PdfAnalysis(StrictModel):
    status: Literal["complete", "partial", "failed"]
    extraction_method: Literal["pypdf"] = "pypdf"
    summary_kind: Literal["extractive"] = "extractive"
    analyzed_at: datetime
    page_count: int = Field(ge=0)
    pages_with_text: int = Field(ge=0)
    word_count: int = Field(ge=0)
    character_count: int = Field(ge=0)
    estimated_reading_minutes: int = Field(ge=0)
    estimation_basis_wpm: int = Field(default=200, ge=1)
    extracted_text_path: str | None = None
    extracted_text_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    extractive_summary: str | None = None
    keywords: list[str] = Field(default_factory=list)
    ocr_required: bool = False
    metadata: PdfMetadata = Field(default_factory=PdfMetadata)
    warnings: list[str] = Field(default_factory=list)
