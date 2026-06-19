from __future__ import annotations

from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule, FixRule
from app.services.docx_formatter.engine.context_classifier import (
    classify_paragraph_context,
    should_apply_body_paragraph_rules,
)
from app.services.docx_formatter.rules.common_format import CommonFormatMixin
from app.services.docx_formatter.utils.text_utils import heading_key


class ParagraphFormatRule(CommonFormatMixin, AnalyzeRule, FixRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        paragraph_config = config.get("paragraph", {})
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

            if context.context != "body_paragraph":
                continue

            findings.extend(
                self.analyze_common_format(
                    paragraph=paragraph,
                    expected=paragraph_config,
                    location=f"Paragraph {paragraph_index}",
                    type_prefix="PARAGRAPH",
                    metadata={
                        "target": "paragraph",
                        "context": context.context,
                        "report_group_id": "body_paragraph",
                        "report_severity": "major",
                        "auto_fixable": True,
                        "section_index": None,
                        "paragraph_index": paragraph_index,
                        "heading_path": heading_path.copy(),
                        "text_preview": context.text_preview,
                        "style_name": context.style_name,
                    },
                )
            )

        return findings

    def fix(self, doc: Any, config: dict[str, Any]) -> int:
        paragraph_config = config.get("paragraph", {})
        changes = 0

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            if not should_apply_body_paragraph_rules(paragraph, paragraph_index):
                continue

            changes += self.fix_common_format(paragraph, paragraph_config)

        return changes


def _update_heading_path(current: list[str], text: str, key: str) -> list[str]:
    if key == "heading_1":
        return [text]
    if key == "heading_2":
        return [*(current[:1] or []), text]
    if key == "heading_3":
        return [*(current[:2] or []), text]
    return current
