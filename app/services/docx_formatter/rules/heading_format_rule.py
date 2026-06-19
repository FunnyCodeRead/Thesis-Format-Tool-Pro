from __future__ import annotations

from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule, FixRule
from app.services.docx_formatter.engine.context_classifier import classify_paragraph_context
from app.services.docx_formatter.rules.common_format import CommonFormatMixin
from app.services.docx_formatter.utils.text_utils import heading_key, is_uppercase_text, should_skip_paragraph


class HeadingFormatRule(CommonFormatMixin, AnalyzeRule, FixRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        heading_configs = config.get("headings", {})
        findings: list[Finding] = []
        heading_path: list[str] = []

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            if should_skip_paragraph(paragraph):
                continue

            key = heading_key(paragraph)
            if key is None or key not in heading_configs:
                continue

            context = classify_paragraph_context(paragraph, paragraph_index)
            if context.context != "heading":
                continue

            heading_path = _update_heading_path(heading_path, paragraph.text.strip(), key)
            expected = heading_configs[key]
            location = f"Paragraph {paragraph_index} ({key.replace('_', ' ').title()})"
            metadata = {
                "target": "heading",
                "context": "heading",
                "report_group_id": "heading",
                "report_severity": "major",
                "auto_fixable": True,
                "section_index": None,
                "paragraph_index": paragraph_index,
                "heading": key,
                "heading_path": heading_path.copy(),
                "text_preview": context.text_preview,
                "style_name": context.style_name,
            }

            findings.extend(
                self.analyze_common_format(
                    paragraph=paragraph,
                    expected=expected,
                    location=location,
                    type_prefix=key.upper(),
                    metadata=metadata,
                )
            )

            if expected.get("uppercase") is True and not is_uppercase_text(paragraph.text):
                findings.append(
                    Finding(
                        type=f"{key.upper()}_UPPERCASE_ERROR",
                        severity="warning",
                        location=location,
                        message="Heading chưa viết hoa theo yêu cầu.",
                        current_value="chưa viết hoa",
                        expected_value="viết hoa",
                        suggestion="Đặt heading ở dạng chữ hoa theo mẫu trình bày.",
                        metadata={
                            **metadata,
                            "field": "uppercase",
                            "fix_action": {"type": "set_all_caps", "value": True},
                        },
                    )
                )

        return findings

    def fix(self, doc: Any, config: dict[str, Any]) -> int:
        heading_configs = config.get("headings", {})
        changes = 0

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            if should_skip_paragraph(paragraph):
                continue

            key = heading_key(paragraph)
            if key is None or key not in heading_configs:
                continue
            if classify_paragraph_context(paragraph, paragraph_index).context != "heading":
                continue

            changes += self.fix_common_format(paragraph, heading_configs[key])

        return changes


def _update_heading_path(current: list[str], text: str, key: str) -> list[str]:
    if key == "heading_1":
        return [text]
    if key == "heading_2":
        return [*(current[:1] or []), text]
    if key == "heading_3":
        return [*(current[:2] or []), text]
    return current
