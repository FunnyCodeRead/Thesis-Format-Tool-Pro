from __future__ import annotations

from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule, FixRule
from app.services.docx_formatter.engine.context_classifier import text_preview
from app.services.docx_formatter.rules.common_format import CommonFormatMixin


class HeaderFooterFormatRule(CommonFormatMixin, AnalyzeRule, FixRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        expected = _header_footer_expected_config(config)
        findings: list[Finding] = []

        for section_index, section in enumerate(doc.sections, start=1):
            findings.extend(
                self._part_findings(
                    part=section.header,
                    expected=expected,
                    section_index=section_index,
                    target="header",
                    part_label="Header",
                )
            )
            findings.extend(
                self._part_findings(
                    part=section.footer,
                    expected=expected,
                    section_index=section_index,
                    target="footer",
                    part_label="Footer",
                )
            )

        return findings

    def fix(self, doc: Any, config: dict[str, Any]) -> int:
        expected = _header_footer_expected_config(config)
        changes = 0

        for section in doc.sections:
            for part in (section.header, section.footer):
                for paragraph in part.paragraphs:
                    if not (paragraph.text or "").strip():
                        continue
                    changes += self.fix_run_format(paragraph, expected)

        return changes

    def _part_findings(
        self,
        *,
        part: Any,
        expected: dict[str, Any],
        section_index: int,
        target: str,
        part_label: str,
    ) -> list[Finding]:
        findings: list[Finding] = []

        for part_paragraph_index, paragraph in enumerate(part.paragraphs, start=1):
            preview = text_preview(paragraph.text)
            if not preview:
                continue

            findings.extend(
                self.analyze_run_format(
                    paragraph=paragraph,
                    expected=expected,
                    location=f"Section {section_index} {part_label}",
                    type_prefix="HEADER_FOOTER",
                    metadata={
                        "target": target,
                        "context": "header_footer",
                        "report_group_id": "header_footer_format",
                        "report_severity": "minor",
                        "auto_fixable": True,
                        "manual_review": False,
                        "section_index": section_index,
                        "part_paragraph_index": part_paragraph_index,
                        "text_preview": preview,
                        "style_name": part_label,
                    },
                )
            )

        return findings


def _header_footer_expected_config(config: dict[str, Any]) -> dict[str, Any]:
    paragraph_config = config.get("paragraph", {})
    part_config = config.get("header_footer_format", {})
    return {
        "font_name": part_config.get("font_name", paragraph_config.get("font_name", "Times New Roman")),
        "font_size": part_config.get("font_size", paragraph_config.get("font_size", 13)),
    }
