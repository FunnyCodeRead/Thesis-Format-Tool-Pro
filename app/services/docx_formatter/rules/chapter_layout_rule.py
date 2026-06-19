from __future__ import annotations

import re
from typing import Any

from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule
from app.services.docx_formatter.engine.context_classifier import text_preview
from app.services.docx_formatter.rules.common_format import CommonFormatMixin
from app.services.docx_formatter.utils.text_utils import normalize_text


class ChapterLayoutRule(CommonFormatMixin, AnalyzeRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        chapter_config = config.get("chapter_layout", {})
        if chapter_config.get("enabled", True) is False:
            return []

        findings: list[Finding] = []
        paragraphs = list(doc.paragraphs)

        for paragraph_index, paragraph in enumerate(paragraphs, start=1):
            text = paragraph.text.strip()
            normalized_text = normalize_text(text)
            chapter_match = re.match(r"^CHUONG\s+(\d+)\.?\s*(.*)$", normalized_text)
            if not chapter_match:
                continue

            chapter_no = chapter_match.group(1)
            trailing_title = chapter_match.group(2).strip()
            chapter_label = f"CHƯƠNG {chapter_no}."
            context = {
                "target": "heading",
                "context": "chapter_number",
                "report_group_id": "chapter_layout",
                "report_severity": "critical",
                "paragraph_index": paragraph_index,
                "field": "chapter_layout",
                "text_preview": text_preview(text),
                "style_name": getattr(getattr(paragraph, "style", None), "name", ""),
            }

            if trailing_title:
                findings.append(
                    _manual_finding(
                        finding_type="CHAPTER_NUMBER_NOT_SEPARATED_REVIEW",
                        severity="error",
                        location=f"Paragraph {paragraph_index}",
                        message="Số chương và tiêu đề chương đang nằm cùng một đoạn.",
                        current_value=text_preview(text),
                        expected_value=f"{chapter_label} nằm trên một dòng căn giữa; tiêu đề chương nằm dòng dưới, viết hoa và căn giữa.",
                        suggestion="Tách số chương thành một dòng riêng và đặt tiêu đề chương ở dòng ngay bên dưới.",
                        metadata=context,
                    )
                )

            if text_preview(text) != chapter_label and not trailing_title:
                findings.append(
                    _manual_finding(
                        finding_type="CHAPTER_NUMBER_LABEL_REVIEW",
                        severity="warning",
                        location=f"Paragraph {paragraph_index}",
                        message="Dòng số chương chưa đúng mẫu trình bày.",
                        current_value=text_preview(text),
                        expected_value=chapter_label,
                        suggestion="Kiểm tra lại dòng số chương theo mẫu: CHƯƠNG 1.",
                        metadata=context,
                    )
                )

            alignment = self._effective_alignment(paragraph)
            if alignment is not None and alignment != WD_ALIGN_PARAGRAPH.CENTER:
                findings.append(
                    _manual_finding(
                        finding_type="CHAPTER_NUMBER_ALIGNMENT_REVIEW",
                        severity="warning",
                        location=f"Paragraph {paragraph_index}",
                        message="Dòng số chương chưa căn giữa.",
                        current_value=self._alignment_label(alignment),
                        expected_value="căn giữa",
                        suggestion="Căn giữa dòng số chương.",
                        metadata={**context, "field": "alignment"},
                    )
                )

            if not _paragraph_is_bold(self, paragraph):
                findings.append(
                    _manual_finding(
                        finding_type="CHAPTER_NUMBER_BOLD_REVIEW",
                        severity="warning",
                        location=f"Paragraph {paragraph_index}",
                        message="Dòng số chương chưa in đậm.",
                        current_value="không",
                        expected_value="có",
                        suggestion="Đặt dòng số chương ở dạng chữ đậm.",
                        metadata={**context, "field": "bold"},
                    )
                )

            if not trailing_title:
                findings.extend(
                    self._title_findings(
                        paragraphs=paragraphs,
                        chapter_paragraph_index=paragraph_index,
                        chapter_no=chapter_no,
                    )
                )

        return findings

    def _title_findings(
        self,
        *,
        paragraphs: list[Any],
        chapter_paragraph_index: int,
        chapter_no: str,
    ) -> list[Finding]:
        title_index, title_paragraph = _next_non_empty_paragraph(paragraphs, chapter_paragraph_index)
        context = {
            "target": "heading",
            "context": "chapter_title",
            "report_group_id": "chapter_layout",
            "report_severity": "critical",
            "paragraph_index": title_index or chapter_paragraph_index,
            "field": "chapter_layout",
            "text_preview": text_preview(title_paragraph.text if title_paragraph is not None else ""),
            "style_name": getattr(getattr(title_paragraph, "style", None), "name", "") if title_paragraph else "",
        }

        if title_paragraph is None:
            return [
                _manual_finding(
                    finding_type="CHAPTER_TITLE_MISSING_REVIEW",
                    severity="error",
                    location=f"Paragraph {chapter_paragraph_index}",
                    message="Thiếu dòng tiêu đề chương ngay sau số chương.",
                    current_value=None,
                    expected_value=f"Tiêu đề chương {chapter_no} nằm ngay dưới dòng CHƯƠNG {chapter_no}.",
                    suggestion="Thêm tiêu đề chương ở dòng ngay bên dưới số chương.",
                    metadata={**context, "paragraph_index": chapter_paragraph_index},
                )
            ]

        title_text = title_paragraph.text.strip()
        normalized_title = normalize_text(title_text)
        if re.match(r"^CHUONG\s+\d+\.?", normalized_title):
            return [
                _manual_finding(
                    finding_type="CHAPTER_TITLE_MISSING_REVIEW",
                    severity="error",
                    location=f"Paragraph {chapter_paragraph_index}",
                    message="Thiếu dòng tiêu đề chương ngay sau số chương.",
                    current_value=text_preview(title_text),
                    expected_value=f"Tiêu đề chương {chapter_no} nằm ngay dưới dòng CHƯƠNG {chapter_no}.",
                    suggestion="Thêm tiêu đề chương ở dòng ngay bên dưới số chương.",
                    metadata={**context, "paragraph_index": chapter_paragraph_index},
                )
            ]

        findings: list[Finding] = []
        if not _is_uppercase(title_text):
            findings.append(
                _manual_finding(
                    finding_type="CHAPTER_TITLE_UPPERCASE_REVIEW",
                    severity="warning",
                    location=f"Paragraph {title_index}",
                    message="Tiêu đề chương chưa viết hoa.",
                    current_value=text_preview(title_text),
                    expected_value="Tiêu đề chương viết hoa toàn bộ.",
                    suggestion="Kiểm tra và chuyển tiêu đề chương sang chữ in hoa nếu đúng với mẫu trường.",
                    metadata={**context, "field": "uppercase"},
                )
            )

        alignment = self._effective_alignment(title_paragraph)
        if alignment is not None and alignment != WD_ALIGN_PARAGRAPH.CENTER:
            findings.append(
                _manual_finding(
                    finding_type="CHAPTER_TITLE_ALIGNMENT_REVIEW",
                    severity="warning",
                    location=f"Paragraph {title_index}",
                    message="Tiêu đề chương chưa căn giữa.",
                    current_value=self._alignment_label(alignment),
                    expected_value="căn giữa",
                    suggestion="Căn giữa tiêu đề chương.",
                    metadata={**context, "field": "alignment"},
                )
            )

        if not _paragraph_is_bold(self, title_paragraph):
            findings.append(
                _manual_finding(
                    finding_type="CHAPTER_TITLE_BOLD_REVIEW",
                    severity="warning",
                    location=f"Paragraph {title_index}",
                    message="Tiêu đề chương chưa in đậm.",
                    current_value="không",
                    expected_value="có",
                    suggestion="Đặt tiêu đề chương ở dạng chữ đậm.",
                    metadata={**context, "field": "bold"},
                )
            )

        return findings


def _next_non_empty_paragraph(paragraphs: list[Any], chapter_paragraph_index: int) -> tuple[int | None, Any | None]:
    for index in range(chapter_paragraph_index, len(paragraphs)):
        paragraph = paragraphs[index]
        if paragraph.text.strip():
            return index + 1, paragraph
    return None, None


def _paragraph_is_bold(rule: CommonFormatMixin, paragraph: Any) -> bool:
    runs = [run for run in paragraph.runs if run.text.strip()]
    if not runs:
        return False
    return all(rule._effective_run_bold(run, paragraph) for run in runs)


def _is_uppercase(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and text.upper() == text


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
                "reason": "Cần kiểm tra layout chương thủ công; hệ thống không tự tách hoặc sửa chữ nội dung.",
            },
        },
    )
