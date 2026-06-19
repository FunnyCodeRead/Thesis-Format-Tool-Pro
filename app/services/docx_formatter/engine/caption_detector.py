from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.services.docx_formatter.utils.text_utils import normalize_text

CaptionKind = Literal["figure", "table"]
CaptionStatus = Literal["valid", "malformed", "missing_separator", "body_reference", "not_caption"]


@dataclass(frozen=True)
class CaptionDetection:
    kind: CaptionKind | None
    status: CaptionStatus
    number: str | None = None
    title: str | None = None
    reason: str | None = None
    normalized_text: str = ""

    @property
    def is_caption_like(self) -> bool:
        return self.kind is not None and self.status != "body_reference"

    @property
    def is_valid_caption(self) -> bool:
        return self.kind is not None and self.status == "valid"


_LABEL_TO_KIND: dict[str, CaptionKind] = {
    "HINH": "figure",
    "FIGURE": "figure",
    "BANG": "table",
    "TABLE": "table",
}

_STOP_PHRASES = {
    "TRINH BAY",
    "MO TA",
    "CHO THAY",
    "THE HIEN",
    "LIET KE",
    "DUOC DUNG",
    "LA",
    "GOM",
}


def detect_caption_text(text: str) -> CaptionDetection:
    normalized = _compact_normalized(text)
    match = re.match(r"^(HINH|FIGURE|BANG|TABLE)\s+(.+)$", normalized)
    if not match:
        return CaptionDetection(kind=None, status="not_caption", normalized_text=normalized)

    kind = _LABEL_TO_KIND[match.group(1)]
    rest = match.group(2).strip()

    deep_number = re.match(r"^(\d+(?:\.\d+){2,})\b\s*([.:])?\s*(.*)$", rest)
    if deep_number:
        return CaptionDetection(
            kind=kind,
            status="malformed",
            number=deep_number.group(1),
            title=_strip_page_number_tail(deep_number.group(3)),
            reason="number_too_deep",
            normalized_text=normalized,
        )

    valid = re.match(r"^(\d+\.\d+)([.:])\s+(.+)$", rest)
    if valid:
        return CaptionDetection(
            kind=kind,
            status="valid",
            number=valid.group(1),
            title=_strip_page_number_tail(valid.group(3)),
            normalized_text=normalized,
        )

    numbered_without_separator = re.match(r"^(\d+\.\d+)\s+(.+)$", rest)
    if numbered_without_separator:
        tail = numbered_without_separator.group(2).strip()
        if _starts_with_stop_phrase(tail):
            return CaptionDetection(
                kind=kind,
                status="body_reference",
                number=numbered_without_separator.group(1),
                title=_strip_page_number_tail(tail),
                reason="body_reference_after_number",
                normalized_text=normalized,
            )

        return CaptionDetection(
            kind=kind,
            status="missing_separator",
            number=numbered_without_separator.group(1),
            title=_strip_page_number_tail(tail),
            reason="missing_dot_or_colon_after_number",
            normalized_text=normalized,
        )

    any_number = re.match(r"^(\d+(?:\.\d+)*)\b\s*(.*)$", rest)
    if any_number:
        return CaptionDetection(
            kind=kind,
            status="malformed",
            number=any_number.group(1),
            title=_strip_page_number_tail(any_number.group(2)),
            reason="invalid_caption_number_shape",
            normalized_text=normalized,
        )

    return CaptionDetection(
        kind=kind,
        status="malformed",
        reason="missing_caption_number",
        normalized_text=normalized,
    )


def is_valid_caption_text(text: str) -> bool:
    return detect_caption_text(text).is_valid_caption


def is_caption_like_text(text: str) -> bool:
    return detect_caption_text(text).is_caption_like


def caption_label(kind: CaptionKind) -> str:
    return "Hình" if kind == "figure" else "Bảng"


def _starts_with_stop_phrase(value: str) -> bool:
    return any(value == phrase or value.startswith(f"{phrase} ") for phrase in _STOP_PHRASES)


def _strip_page_number_tail(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+\.{2,}\s*\d+\s*$", "", value).strip()


def _compact_normalized(value: str) -> str:
    normalized = normalize_text(value)
    return re.sub(r"\s+", " ", normalized).strip()
