from __future__ import annotations

from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule, FixRule
from app.services.docx_formatter.engine.context_classifier import classify_paragraph_context
from app.services.docx_formatter.rules.common_format import CommonFormatMixin
from app.services.docx_formatter.utils.text_utils import heading_key


class ListItemFormatRule(CommonFormatMixin, AnalyzeRule, FixRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        expected = _list_item_expected_config(config)
        findings: list[Finding] = []
        heading_path: list[str] = []

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            context = classify_paragraph_context(paragraph, paragraph_index)
            current_heading_key = heading_key(paragraph)
            if current_heading_key is not None and context.context == "heading":
                heading_path = _update_heading_path(
                    heading_path,
                    paragraph.text.strip(),
                    current_heading_key,
                )

            if context.context != "list_item":
                continue

            item_findings = self.analyze_common_format(
                paragraph=paragraph,
                expected=expected,
                location=f"Paragraph {paragraph_index}",
                type_prefix="LIST_ITEM",
                metadata={
                    "target": "paragraph",
                    "context": "list_item",
                    "report_group_id": "list_item",
                    "report_severity": "minor",
                    "auto_fixable": True,
                    "manual_review": False,
                    "section_index": None,
                    "paragraph_index": paragraph_index,
                    "heading_path": heading_path.copy(),
                    "text_preview": context.text_preview,
                    "style_name": context.style_name,
                },
            )
            findings.extend(_with_safe_list_suggestion(finding) for finding in item_findings)

        return findings

    def fix(self, doc: Any, config: dict[str, Any]) -> int:
        expected = _list_item_expected_config(config)
        changes = 0

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            if classify_paragraph_context(paragraph, paragraph_index).context != "list_item":
                continue

            changes += self.fix_common_format(paragraph, expected)

        return changes


def _list_item_expected_config(config: dict[str, Any]) -> dict[str, Any]:
    paragraph_config = config.get("paragraph", {})
    list_config = config.get("list_item", {})
    return {
        "font_name": list_config.get("font_name", paragraph_config.get("font_name", "Times New Roman")),
        "font_size": list_config.get("font_size", paragraph_config.get("font_size", 13)),
        "line_spacing": list_config.get("line_spacing", paragraph_config.get("line_spacing", 1.3)),
        "space_before_pt": list_config.get("space_before_pt", paragraph_config.get("space_before_pt", 6)),
        "space_after_pt": list_config.get("space_after_pt", paragraph_config.get("space_after_pt", 6)),
    }


def _with_safe_list_suggestion(finding: Finding) -> Finding:
    return Finding(
        type=finding.type,
        severity=finding.severity,
        location=finding.location,
        message=finding.message,
        current_value=finding.current_value,
        expected_value=finding.expected_value,
        suggestion="Áp dụng định dạng font, cỡ chữ, giãn dòng và khoảng cách đoạn cho bullet/list; giữ thụt lề bullet/number theo thiết lập danh sách của Word.",
        metadata={
            **finding.metadata,
            "auto_fixable": True,
            "manual_review": False,
        },
    )


def _update_heading_path(current: list[str], text: str, key: str) -> list[str]:
    if key == "heading_1":
        return [text]
    if key == "heading_2":
        return [*(current[:1] or []), text]
    if key == "heading_3":
        return [*(current[:2] or []), text]
    return current
