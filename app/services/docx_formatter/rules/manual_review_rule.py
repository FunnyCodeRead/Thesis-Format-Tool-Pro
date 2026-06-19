from __future__ import annotations

from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule
from app.services.docx_formatter.engine.context_classifier import (
    classify_paragraph_context,
    has_page_number_merged_with_body_text,
)
from app.services.docx_formatter.utils.text_utils import heading_key


class ManualReviewRule(AnalyzeRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        findings: list[Finding] = []
        heading_path: list[str] = []

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            current_heading_key = heading_key(paragraph)
            if current_heading_key is not None:
                heading_path = _update_heading_path(heading_path, paragraph.text.strip(), current_heading_key)

            context = classify_paragraph_context(paragraph, paragraph_index)
            text = paragraph.text.strip()
            if not text:
                continue

            if has_page_number_merged_with_body_text(paragraph):
                group_id = "toc" if context.context == "toc" else "layout_abnormal"
                findings.append(
                    Finding(
                        type="PAGE_NUMBER_IN_BODY_ERROR",
                        severity="error",
                        location=f"Paragraph {paragraph_index}",
                        message="Page number appears to be merged into document body text.",
                        current_value=context.text_preview,
                        expected_value="Page numbers should be in the footer, not merged into body text.",
                        suggestion=(
                            "Review this location manually and move page numbering back to the footer if it "
                            "was converted into normal text."
                        ),
                        metadata={
                            "target": "paragraph",
                            "context": context.context,
                            "report_group_id": group_id,
                            "report_severity": "critical",
                            "auto_fixable": False,
                            "manual_review": True,
                            "rule_id": "PAGE_NUMBER_NOT_IN_BODY",
                            "rule_name": "Số trang không được nằm trong nội dung",
                            "section_index": None,
                            "paragraph_index": paragraph_index,
                            "field": "page_number_position",
                            "heading_path": heading_path.copy(),
                            "text_preview": context.text_preview,
                            "style_name": context.style_name,
                            "fix_action": {
                                "type": "manual_review",
                                "reason": "Cần xác định đây là lỗi text thật hay page number/footer bị convert.",
                            },
                        },
                    )
                )

        return findings


def _update_heading_path(current: list[str], text: str, key: str) -> list[str]:
    if key == "heading_1":
        return [text]
    if key == "heading_2":
        return [*(current[:1] or []), text]
    if key == "heading_3":
        return [*(current[:2] or []), text]
    return current
