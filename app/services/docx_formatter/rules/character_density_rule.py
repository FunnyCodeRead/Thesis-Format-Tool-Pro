from __future__ import annotations

from typing import Any

from docx.oxml.ns import qn

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule
from app.services.docx_formatter.engine.context_classifier import classify_paragraph_context


class CharacterDensityRule(AnalyzeRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        density_config = config.get("character_density", {})
        if density_config.get("enabled", True) is False:
            return []

        findings: list[Finding] = []
        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            text = paragraph.text.strip()
            if not text:
                continue

            issues = _paragraph_density_issues(paragraph)
            if not issues:
                continue

            context = classify_paragraph_context(paragraph, paragraph_index)
            findings.append(
                Finding(
                    type="CHARACTER_DENSITY_REVIEW",
                    severity="warning",
                    location=f"Paragraph {paragraph_index}",
                    message="Character spacing or text scale is not normal.",
                    current_value=", ".join(sorted(set(issues))),
                    expected_value="Normal character spacing and 100% text scale.",
                    suggestion="Chọn đoạn văn và đặt lại Font > Advanced: Scale 100%, Spacing Normal.",
                    metadata={
                        "target": "paragraph",
                        "context": context.context,
                        "report_group_id": "character_density",
                        "report_severity": "major",
                        "paragraph_index": paragraph_index,
                        "field": "character_density",
                        "text_preview": context.text_preview,
                        "style_name": context.style_name,
                        "auto_fixable": False,
                        "manual_review": True,
                        "fix_action": {
                            "type": "manual_review",
                            "reason": "Cần kiểm tra mật độ chữ thủ công; hệ thống không tự can thiệp vào text scale/character spacing.",
                        },
                    },
                )
            )

        return findings


def _paragraph_density_issues(paragraph: Any) -> list[str]:
    issues: list[str] = []
    for run in paragraph.runs:
        if not run.text.strip():
            continue

        r_pr = getattr(run._r, "rPr", None)
        if r_pr is None:
            continue

        spacing = r_pr.find(qn("w:spacing"))
        if spacing is not None:
            value = spacing.get(qn("w:val"))
            if value not in {None, "0"}:
                issues.append(f"character spacing={value}")

        scale = r_pr.find(qn("w:w"))
        if scale is not None:
            value = scale.get(qn("w:val"))
            if value not in {None, "100"}:
                issues.append(f"text scale={value}%")

    return issues
