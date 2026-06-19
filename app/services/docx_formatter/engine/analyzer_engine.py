from __future__ import annotations

from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule
from app.services.docx_formatter.engine.fixability_matrix import apply_fixability_to_findings


class AnalyzerEngine:
    def __init__(self, rules: list[AnalyzeRule]) -> None:
        self.rules = rules

    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        findings: list[Finding] = []

        for rule in self.rules:
            findings.extend(rule.analyze(doc, config))

        return apply_fixability_to_findings(findings)
