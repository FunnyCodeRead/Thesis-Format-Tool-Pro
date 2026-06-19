from __future__ import annotations

import re
from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule
from app.services.docx_formatter.engine.context_classifier import text_preview
from app.services.docx_formatter.utils.text_utils import normalize_text, style_name


class TocStructureRule(AnalyzeRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        toc_config = config.get("toc", {})
        if toc_config.get("enabled", True) is False:
            return []

        paragraphs = list(doc.paragraphs)
        first_chapter_index = _first_chapter_index(paragraphs)
        if first_chapter_index is None:
            return []

        toc_title_index = _toc_title_index(paragraphs)
        if toc_title_index is None:
            paragraph = paragraphs[first_chapter_index - 1]
            return [
                _manual_finding(
                    finding_type="TOC_MISSING_REVIEW",
                    severity="warning",
                    location=f"Paragraph {first_chapter_index}",
                    message="Tài liệu có chương nhưng chưa phát hiện mục lục.",
                    current_value=text_preview(paragraph.text),
                    expected_value="Tài liệu nên có mục lục trước phần nội dung chính nếu quy định yêu cầu.",
                    suggestion="Tạo mục lục bằng References > Table of Contents để Word cập nhật được số trang.",
                    metadata=_metadata(
                        paragraph=paragraph,
                        paragraph_index=first_chapter_index,
                        field="toc_structure",
                    ),
                )
            ]

        if _has_automatic_toc_field(doc):
            return []

        paragraph = paragraphs[toc_title_index - 1]
        return [
            _manual_finding(
                finding_type="TOC_NOT_AUTOMATIC_REVIEW",
                severity="warning",
                location=f"Paragraph {toc_title_index}",
                message="Mục lục có thể đang được gõ tay, chưa phải TOC field tự động.",
                current_value=text_preview(paragraph.text),
                expected_value="Mục lục nên được tạo bằng TOC field để cập nhật heading và số trang.",
                suggestion="Dùng References > Table of Contents hoặc Update Table trong Word thay vì gõ tay.",
                metadata=_metadata(
                    paragraph=paragraph,
                    paragraph_index=toc_title_index,
                    field="toc_structure",
                ),
            )
        ]


def _first_chapter_index(paragraphs: list[Any]) -> int | None:
    for paragraph_index, paragraph in enumerate(paragraphs, start=1):
        if re.match(r"^CHUONG\s+\d+\.?(?:\s+.*)?$", normalize_text(paragraph.text.strip())):
            return paragraph_index
    return None


def _toc_title_index(paragraphs: list[Any]) -> int | None:
    for paragraph_index, paragraph in enumerate(paragraphs, start=1):
        normalized = normalize_text(paragraph.text.strip())
        if normalized.startswith(("MUC LUC", "TABLE OF CONTENTS")):
            return paragraph_index
    return None


def _has_automatic_toc_field(doc: Any) -> bool:
    text = _package_xml_text(doc).upper()
    toc_markers = (
        "TOC \\\\O",
        "TOC \\\\H",
        "TOC \\\\U",
        "TOC \\\\Z",
        'W:INSTR=" TOC',
        "> TOC ",
        ">TOC ",
    )
    return any(marker in text for marker in toc_markers)


def _package_xml_text(doc: Any) -> str:
    chunks: list[str] = []
    try:
        parts = doc.part.package.parts
    except AttributeError:
        return ""

    for part in parts:
        partname = str(getattr(part, "partname", ""))
        if not partname.startswith("/word/") or not partname.endswith(".xml"):
            continue
        try:
            blob = part.blob
        except (AttributeError, ValueError):
            continue
        if isinstance(blob, bytes):
            chunks.append(blob.decode("utf-8", errors="ignore"))
    return "\n".join(chunks)


def _metadata(*, paragraph: Any, paragraph_index: int, field: str) -> dict[str, Any]:
    return {
        "target": "paragraph",
        "context": "toc",
        "report_group_id": "toc",
        "report_severity": "major",
        "paragraph_index": paragraph_index,
        "field": field,
        "text_preview": text_preview(paragraph.text),
        "style_name": style_name(paragraph),
    }


def _manual_finding(
    *,
    finding_type: str,
    severity: str,
    location: str,
    message: str,
    current_value: str | None,
    expected_value: str | None,
    suggestion: str,
    metadata: dict[str, Any],
) -> Finding:
    return Finding(
        type=finding_type,
        severity=severity,
        location=location,
        message=message,
        current_value=current_value,
        expected_value=expected_value,
        suggestion=suggestion,
        metadata={
            **metadata,
            "auto_fixable": False,
            "manual_review": True,
            "fix_action": {
                "type": "manual_review",
                "reason": "Mục lục là field/cấu trúc Word phức tạp nên chỉ report, không auto-fix.",
            },
        },
    )
