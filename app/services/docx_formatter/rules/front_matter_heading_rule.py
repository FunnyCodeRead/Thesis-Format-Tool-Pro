from __future__ import annotations

from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule, FixRule
from app.services.docx_formatter.engine.context_classifier import classify_paragraph_context
from app.services.docx_formatter.rules.common_format import CommonFormatMixin
from app.services.docx_formatter.utils.text_utils import is_uppercase_text


class FrontMatterHeadingRule(CommonFormatMixin, AnalyzeRule, FixRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        expected = _front_matter_expected_config(config)
        findings: list[Finding] = []

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            context = classify_paragraph_context(paragraph, paragraph_index)
            if context.context != "front_matter_heading":
                continue

            metadata = {
                "target": "heading",
                "context": "front_matter_heading",
                "report_group_id": "front_matter",
                "report_severity": "minor",
                "auto_fixable": True,
                "manual_review": False,
                "section_index": None,
                "paragraph_index": paragraph_index,
                "heading_path": [],
                "text_preview": context.text_preview,
                "style_name": context.style_name,
            }
            item_findings = self.analyze_common_format(
                paragraph=paragraph,
                expected=expected,
                location=f"Paragraph {paragraph_index}",
                type_prefix="FRONT_MATTER_HEADING",
                metadata=metadata,
            )
            findings.extend(_with_safe_front_matter_suggestion(finding) for finding in item_findings)

            if expected.get("uppercase") is True and not is_uppercase_text(paragraph.text):
                findings.append(
                    _with_safe_front_matter_suggestion(
                        Finding(
                            type="FRONT_MATTER_HEADING_UPPERCASE_ERROR",
                            severity="warning",
                            location=f"Paragraph {paragraph_index}",
                            message="Tiêu đề phần đầu chưa viết hoa theo yêu cầu.",
                            current_value="chưa viết hoa",
                            expected_value="viết hoa",
                            suggestion="Đặt tiêu đề phần đầu ở dạng chữ hoa theo mẫu trình bày.",
                            metadata={
                                **metadata,
                                "field": "uppercase",
                                "fix_action": {"type": "set_all_caps", "value": True},
                            },
                        )
                    )
                )

        return findings

    def fix(self, doc: Any, config: dict[str, Any]) -> int:
        expected = _front_matter_expected_config(config)
        changes = 0

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            context = classify_paragraph_context(paragraph, paragraph_index)
            if context.context != "front_matter_heading":
                continue

            changes += self.fix_common_format(paragraph, expected)

        return changes


def _front_matter_expected_config(config: dict[str, Any]) -> dict[str, Any]:
    paragraph_config = config.get("paragraph", {})
    front_matter_config = config.get("front_matter_heading", {})
    return {
        "font_name": front_matter_config.get("font_name", paragraph_config.get("font_name", "Times New Roman")),
        "font_size": front_matter_config.get("font_size", paragraph_config.get("font_size", 13)),
        "bold": front_matter_config.get("bold", True),
        "uppercase": front_matter_config.get("uppercase", True),
        "alignment": front_matter_config.get("alignment", "CENTER"),
        "space_after_pt": front_matter_config.get("space_after_pt", paragraph_config.get("space_after_pt", 6)),
    }


def _with_safe_front_matter_suggestion(finding: Finding) -> Finding:
    return Finding(
        type=finding.type,
        severity=finding.severity,
        location=finding.location,
        message=finding.message,
        current_value=finding.current_value,
        expected_value=finding.expected_value,
        suggestion="Áp dụng định dạng tiêu đề phần đầu theo mẫu riêng; không trộn với heading chương.",
        metadata={
            **finding.metadata,
            "auto_fixable": True,
            "manual_review": False,
        },
    )
