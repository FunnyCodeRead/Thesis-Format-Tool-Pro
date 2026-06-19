from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.services.docx_formatter.engine.caption_detector import (
    CaptionDetection,
    CaptionKind,
    detect_caption_text,
)
from app.services.docx_formatter.engine.context_classifier import (
    ParagraphContext,
    classify_paragraph_context,
    text_preview,
)
from app.services.docx_formatter.utils.text_utils import normalize_text, style_name

GeneratedListRegion = Literal["list_of_figures", "list_of_tables"]


@dataclass(frozen=True)
class ParagraphStructure:
    index: int
    paragraph: Any
    context: ParagraphContext
    reason: str
    text: str
    normalized_text: str
    text_preview: str
    style_name: str
    current_chapter: str | None
    chapter_number: str | None = None
    heading_number: str | None = None
    heading_chapter: str | None = None
    caption: CaptionDetection = field(
        default_factory=lambda: CaptionDetection(kind=None, status="not_caption")
    )
    generated_list_region: GeneratedListRegion | None = None


@dataclass(frozen=True)
class CaptionIndexEntry:
    kind: CaptionKind
    number: str
    title: str
    paragraph_index: int
    context: str


class DocumentStructureIndex:
    def __init__(self, paragraphs: list[ParagraphStructure]) -> None:
        self.paragraphs = paragraphs
        self.by_index = {paragraph.index: paragraph for paragraph in paragraphs}
        self.body_captions: dict[tuple[CaptionKind, str], CaptionIndexEntry] = {}
        self.generated_list_entries: dict[GeneratedListRegion, list[CaptionIndexEntry]] = {
            "list_of_figures": [],
            "list_of_tables": [],
        }

        for paragraph in paragraphs:
            caption = paragraph.caption
            if caption.kind is None or caption.number is None or caption.title is None:
                continue
            if caption.status != "valid":
                continue

            entry = CaptionIndexEntry(
                kind=caption.kind,
                number=caption.number,
                title=caption.title,
                paragraph_index=paragraph.index,
                context=paragraph.context,
            )
            if paragraph.generated_list_region is not None:
                self.generated_list_entries[paragraph.generated_list_region].append(entry)
            else:
                self.body_captions[(caption.kind, caption.number)] = entry

    @classmethod
    def build(cls, doc: Any) -> "DocumentStructureIndex":
        paragraphs: list[ParagraphStructure] = []
        current_chapter: str | None = None
        active_generated_list: GeneratedListRegion | None = None

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            text = (getattr(paragraph, "text", "") or "").strip()
            normalized_text = normalize_text(text)
            caption = detect_caption_text(text)
            context_info = classify_paragraph_context(paragraph, paragraph_index)

            chapter_number = detect_chapter_number(normalized_text)
            if chapter_number is not None:
                current_chapter = chapter_number
                active_generated_list = None

            region_title = generated_list_region_from_title(normalized_text)
            if region_title is not None:
                active_generated_list = region_title

            if active_generated_list is not None and _should_leave_generated_list(normalized_text):
                active_generated_list = None

            context = context_info.context
            reason = context_info.reason
            generated_list_region: GeneratedListRegion | None = None
            if active_generated_list is not None and _belongs_to_generated_list(
                active_generated_list,
                caption,
                normalized_text,
                region_title is not None,
            ):
                context = active_generated_list
                reason = "generated_list_region"
                generated_list_region = active_generated_list if region_title is None else None
            elif caption.status == "valid":
                context = "caption"
                reason = "valid_caption"
            elif caption.status in {"malformed", "missing_separator"} and context in {
                "list_of_figures",
                "list_of_tables",
            }:
                generated_list_region = context  # type: ignore[assignment]

            heading_number = detect_numbered_heading(normalized_text)
            heading_chapter = heading_number.split(".", 1)[0] if heading_number else None

            paragraphs.append(
                ParagraphStructure(
                    index=paragraph_index,
                    paragraph=paragraph,
                    context=context,
                    reason=reason,
                    text=text,
                    normalized_text=normalized_text,
                    text_preview=text_preview(text),
                    style_name=style_name(paragraph),
                    current_chapter=current_chapter,
                    chapter_number=chapter_number,
                    heading_number=heading_number,
                    heading_chapter=heading_chapter,
                    caption=caption,
                    generated_list_region=generated_list_region,
                )
            )

        return cls(paragraphs)

    def paragraph(self, paragraph_index: int) -> ParagraphStructure | None:
        return self.by_index.get(paragraph_index)

    def body_caption(self, kind: CaptionKind, number: str) -> CaptionIndexEntry | None:
        return self.body_captions.get((kind, number))


def detect_chapter_number(normalized_text: str) -> str | None:
    match = re.match(r"^CHUONG\s+(\d+)\.?(?:\s+.*)?$", normalized_text)
    return match.group(1) if match else None


def detect_numbered_heading(normalized_text: str) -> str | None:
    match = re.match(r"^(\d+(?:\.\d+){1,3})\.?\s+\S", normalized_text)
    return match.group(1) if match else None


def generated_list_region_from_title(normalized_text: str) -> GeneratedListRegion | None:
    if normalized_text.startswith(("DANH MUC HINH", "DANH SACH HINH", "LIST OF FIGURES")):
        return "list_of_figures"
    if normalized_text.startswith(("DANH MUC BANG", "DANH SACH BANG", "LIST OF TABLES")):
        return "list_of_tables"
    return None


def normalized_title_key(value: str | None) -> str:
    if not value:
        return ""
    normalized = normalize_text(value)
    normalized = re.sub(r"\.{2,}\s*\d+\s*$", "", normalized)
    normalized = re.sub(r"[^A-Z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _belongs_to_generated_list(
    active_region: GeneratedListRegion,
    caption: CaptionDetection,
    normalized_text: str,
    is_region_title: bool,
) -> bool:
    if is_region_title:
        return True
    if caption.kind == "figure" and active_region == "list_of_figures":
        return True
    if caption.kind == "table" and active_region == "list_of_tables":
        return True
    return _looks_like_generated_list_entry(normalized_text)


def _should_leave_generated_list(normalized_text: str) -> bool:
    if not normalized_text:
        return False
    if detect_chapter_number(normalized_text) is not None:
        return True
    return normalized_text.startswith(
        (
            "MUC LUC",
            "LOI ",
            "TAI LIEU THAM KHAO",
            "REFERENCES",
            "PHU LUC",
            "APPENDIX",
        )
    )


def _looks_like_generated_list_entry(normalized_text: str) -> bool:
    if len(normalized_text) <= 12:
        return False
    return bool(re.search(r"\s\d+\s*$", normalized_text))
