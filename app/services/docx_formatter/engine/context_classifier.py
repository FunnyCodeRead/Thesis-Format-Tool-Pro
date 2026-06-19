from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.services.docx_formatter.engine.caption_detector import detect_caption_text
from app.services.docx_formatter.utils.text_utils import (
    heading_key,
    normalize_text,
    style_name,
)

ParagraphContext = Literal[
    "cover",
    "toc",
    "list_of_figures",
    "list_of_tables",
    "front_matter_heading",
    "list_item",
    "chapter_number",
    "chapter_title",
    "heading",
    "body_paragraph",
    "caption",
    "table_cell",
    "signature_line",
    "header_footer",
    "references",
    "layout_abnormal",
    "empty",
    "unknown",
]

MIN_BODY_TEXT_LENGTH = 24
COVER_PARAGRAPH_LIMIT = 25


@dataclass(frozen=True)
class ParagraphContextInfo:
    context: ParagraphContext
    reason: str
    text_preview: str
    style_name: str


def classify_paragraph_context(paragraph: Any, paragraph_index: int | None = None) -> ParagraphContextInfo:
    text = (getattr(paragraph, "text", "") or "").strip()
    preview = text_preview(text)
    current_style = style_name(paragraph)
    normalized_text = normalize_text(text)
    normalized_style = normalize_text(current_style).replace("_", " ")

    if not text:
        if _paragraph_contains_image(paragraph) and _is_cover_media_candidate(paragraph_index):
            return ParagraphContextInfo("cover", "early_cover_media", preview, current_style)
        return ParagraphContextInfo("empty", "empty_paragraph", preview, current_style)

    if _is_chapter_number_or_combined_title(normalized_text):
        return ParagraphContextInfo("chapter_number", "chapter_number_line", preview, current_style)

    if _is_chapter_title(text, normalized_text):
        return ParagraphContextInfo("chapter_title", "uppercase_chapter_title", preview, current_style)

    if _is_toc(normalized_text, normalized_style):
        return ParagraphContextInfo("toc", "toc_style_or_text", preview, current_style)

    if _is_list_of_figures(normalized_text):
        return ParagraphContextInfo("list_of_figures", "list_of_figures_text", preview, current_style)

    if _is_list_of_tables(normalized_text):
        return ParagraphContextInfo("list_of_tables", "list_of_tables_text", preview, current_style)

    if _is_front_matter_heading(normalized_text):
        return ParagraphContextInfo("front_matter_heading", "front_matter_heading_text", preview, current_style)

    if _is_caption(normalized_text, normalized_style):
        return ParagraphContextInfo("caption", "caption_style_or_text", preview, current_style)

    if _is_reference(normalized_text, normalized_style):
        return ParagraphContextInfo("references", "reference_style_or_text", preview, current_style)

    if _has_skipped_xml(paragraph):
        return ParagraphContextInfo("header_footer", "field_or_complex_xml", preview, current_style)

    if _is_cover_candidate(normalized_text, paragraph_index):
        return ParagraphContextInfo("cover", "early_short_cover_like_text", preview, current_style)

    if _is_signature_line(normalized_text):
        return ParagraphContextInfo("signature_line", "short_signature_line", preview, current_style)

    if _is_list_item(paragraph, text, normalized_style):
        return ParagraphContextInfo("list_item", "list_or_bullet_paragraph", preview, current_style)

    if heading_key(paragraph) is not None:
        return ParagraphContextInfo("heading", "word_heading_style", preview, current_style)

    if len(text) < MIN_BODY_TEXT_LENGTH:
        return ParagraphContextInfo("unknown", "too_short_for_body_rule", preview, current_style)

    return ParagraphContextInfo("body_paragraph", "default_body_paragraph", preview, current_style)


def should_apply_body_paragraph_rules(paragraph: Any, paragraph_index: int | None = None) -> bool:
    return classify_paragraph_context(paragraph, paragraph_index).context == "body_paragraph"


def text_preview(value: str, limit: int = 160) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}…"


def has_page_number_merged_with_body_text(paragraph: Any) -> bool:
    text = (getattr(paragraph, "text", "") or "").strip()
    normalized_text = normalize_text(text)

    if _has_toc_merged_page_number(text):
        return True

    known_bad_fragments = (
        "LANG VAN VUII",
        "LANG VAN VUIII",
    )
    if any(fragment in normalized_text for fragment in known_bad_fragments):
        return True

    if re.search(r"\b\d+(?:IV|V|VI|VII|VIII|IX|X)\b", normalized_text):
        return True

    if re.search(r"\b[A-ZÀ-ỸĐ]{2,}I{2,}\b", normalized_text):
        return True

    return bool(_SIGNATURE_ROMAN_SUFFIX_RE.search(text))


def _is_toc(normalized_text: str, normalized_style: str) -> bool:
    return (
        normalized_style.startswith("TOC")
        or normalized_text.startswith("MUC LUC")
        or normalized_text.startswith("TABLE OF CONTENTS")
        or bool(re.search(r"\.{5,}\s*\d+\s*$", normalized_text))
        or _looks_like_toc_entry(normalized_text)
    )


def _is_list_of_figures(normalized_text: str) -> bool:
    return normalized_text.startswith(("DANH MUC HINH", "DANH SACH HINH", "LIST OF FIGURES")) or (
        detect_caption_text(normalized_text).kind == "figure"
        and detect_caption_text(normalized_text).status != "body_reference"
        and _ends_with_page_number(normalized_text)
    )


def _is_list_of_tables(normalized_text: str) -> bool:
    return normalized_text.startswith(("DANH MUC BANG", "DANH SACH BANG", "LIST OF TABLES")) or (
        detect_caption_text(normalized_text).kind == "table"
        and detect_caption_text(normalized_text).status != "body_reference"
        and _ends_with_page_number(normalized_text)
    )


def _is_front_matter_heading(normalized_text: str) -> bool:
    return normalized_text in {
        "LOI CAM ON",
        "LOI CAM DOAN",
        "LOI NOI DAU",
        "LOI MO DAU",
        "TOM TAT",
        "ABSTRACT",
        "NHAN XET CUA GIANG VIEN HUONG DAN",
        "NHAN XET CUA GIANG VIEN PHAN BIEN",
    }


def _is_caption(normalized_text: str, normalized_style: str) -> bool:
    detection = detect_caption_text(normalized_text)
    if detection.status == "body_reference":
        return False
    if detection.status == "valid":
        return True
    return "CAPTION" in normalized_style and detection.status != "not_caption"


def _is_chapter_number_or_combined_title(normalized_text: str) -> bool:
    return bool(re.match(r"^CHUONG\s+\d+\.?", normalized_text))


def _is_chapter_title(text: str, normalized_text: str) -> bool:
    if len(normalized_text) < 6 or len(normalized_text) > 90:
        return False
    if not re.search(r"[A-Z]", normalized_text):
        return False
    if normalized_text.startswith(("CHUONG ", "MUC LUC", "DANH MUC ", "LOI ")):
        return False
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and text.upper() == text


def _is_reference(normalized_text: str, normalized_style: str) -> bool:
    return "BIBLIOGRAPHY" in normalized_style or normalized_text.startswith(
        ("REFERENCES", "TAI LIEU THAM KHAO")
    )


def _is_signature_line(normalized_text: str) -> bool:
    if normalized_text in {
        "TRAN TRONG",
        "SINH VIEN",
        "GIANG VIEN HUONG DAN",
        "GVHD",
        "NGUOI THUC HIEN",
    }:
        return True

    if len(normalized_text) > 36:
        return False

    signature_words = normalized_text.split()
    if len(signature_words) < 2 or len(signature_words) > 5:
        return False

    return all(word.isalpha() and len(word) >= 2 for word in signature_words)


def _is_cover_candidate(normalized_text: str, paragraph_index: int | None) -> bool:
    if paragraph_index is None or paragraph_index > COVER_PARAGRAPH_LIMIT:
        return False

    if normalized_text.startswith(
        (
            "DAI HOC",
            "TRUONG",
            "KHOA ",
            "BO MON",
            "DO AN",
            "KHOA LUAN",
            "BAO CAO",
            "BIA PHU",
            "BIA LOT",
            "DE TAI",
            "LOGO",
            "ANH SINH VIEN",
            "HINH ANH SINH VIEN",
            "SINH VIEN",
            "LOP",
            "GIANG VIEN",
            "GVHD",
        )
    ):
        return True

    return False


def _is_cover_media_candidate(paragraph_index: int | None) -> bool:
    return paragraph_index is not None and paragraph_index <= COVER_PARAGRAPH_LIMIT


def _is_list_item(paragraph: Any, text: str, normalized_style: str) -> bool:
    if _has_numbering_properties(paragraph):
        return True

    if "LIST" in normalized_style or "BULLET" in normalized_style or "NUMBER" in normalized_style:
        return True

    stripped = text.lstrip()
    return stripped.startswith(("•", "·", "●", "▪", "▫", "- "))


def _has_numbering_properties(paragraph: Any) -> bool:
    p_pr = getattr(getattr(paragraph, "_p", None), "pPr", None)
    return getattr(p_pr, "numPr", None) is not None


def _paragraph_contains_image(paragraph: Any) -> bool:
    xml = getattr(getattr(paragraph, "_p", None), "xml", "")
    return "<w:drawing" in xml or "<w:pict" in xml


def _has_skipped_xml(paragraph: Any) -> bool:
    xml = getattr(getattr(paragraph, "_p", None), "xml", "")
    skipped_xml_markers = ("<w:hyperlink", "<w:fldChar", "<w:instrText", "<m:oMath", "<m:oMathPara")
    return any(marker in xml for marker in skipped_xml_markers)


def _has_toc_merged_page_number(text: str) -> bool:
    return bool(re.search(r"\.{5,}\s*\d+[ivxlcdm]+\s*$", text.strip(), re.IGNORECASE))


def _looks_like_toc_entry(normalized_text: str) -> bool:
    if len(normalized_text) > 180 or not _ends_with_page_number(normalized_text):
        return False

    if re.match(r"^(LOI|CHUONG|CHAPTER|PHAN|MUC)\b", normalized_text):
        return True

    return bool(re.match(r"^\d+(?:\.\d+)*\s+\S", normalized_text))


def _ends_with_page_number(normalized_text: str) -> bool:
    return bool(re.search(r"\s\d+\s*$", normalized_text))


_SIGNATURE_ROMAN_SUFFIX_RE = re.compile(
    r"\b[A-ZÀ-ỸĐ][A-Za-zÀ-ỹĐđ]+(?:\s+[A-ZÀ-ỸĐ][A-Za-zÀ-ỹĐđ]+){1,4}(?:ii|iii|iv|v|vi|vii|viii|ix|x)\b$",
    re.IGNORECASE,
)
