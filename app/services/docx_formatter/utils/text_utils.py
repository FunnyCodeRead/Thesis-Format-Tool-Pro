from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    without_marks = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return without_marks.upper().strip()


def style_name(paragraph: Any) -> str:
    style = getattr(paragraph, "style", None)
    return getattr(style, "name", "") or ""


def heading_key(paragraph: Any) -> str | None:
    normalized_style = normalize_text(style_name(paragraph)).replace("_", " ")

    if normalized_style.startswith("HEADING 1"):
        return "heading_1"
    if normalized_style.startswith("HEADING 2"):
        return "heading_2"
    if normalized_style.startswith("HEADING 3"):
        return "heading_3"

    return None


def is_uppercase_text(value: str) -> bool:
    letters = [char for char in value if char.isalpha()]
    return bool(letters) and value.upper() == value


def should_skip_paragraph(paragraph: Any) -> bool:
    text = paragraph.text.strip()
    if not text:
        return True

    normalized_style = normalize_text(style_name(paragraph))
    normalized_text = normalize_text(text)

    if "CAPTION" in normalized_style and not _looks_like_caption_body_reference(normalized_text):
        return True
    if _looks_like_valid_caption(normalized_text):
        return True

    if normalized_style.startswith("TOC") or normalized_text.startswith(("MUC LUC", "TABLE OF CONTENTS")):
        return True

    if "BIBLIOGRAPHY" in normalized_style or normalized_text.startswith(("REFERENCES", "TAI LIEU THAM KHAO")):
        return True

    xml = paragraph._p.xml
    skipped_xml_markers = ("<w:hyperlink", "<w:fldChar", "<w:instrText", "<m:oMath", "<m:oMathPara")
    return any(marker in xml for marker in skipped_xml_markers)


def _looks_like_valid_caption(normalized_text: str) -> bool:
    return bool(
        normalized_text.startswith(("FIGURE ", "TABLE ", "HINH ", "BANG "))
        and re.match(r"^(FIGURE|TABLE|HINH|BANG)\s+\d+\.\d+[\.:]\s+\S", normalized_text)
    )


def _looks_like_caption_body_reference(normalized_text: str) -> bool:
    return bool(
        re.match(
            r"^(FIGURE|TABLE|HINH|BANG)\s+\d+\.\d+\s+(TRINH BAY|MO TA|CHO THAY|THE HIEN|LIET KE|DUOC DUNG|LA|GOM)\b",
            normalized_text,
        )
    )
