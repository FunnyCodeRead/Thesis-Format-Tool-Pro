from __future__ import annotations

import unittest

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule
from app.services.docx_formatter.engine.analyzer_engine import AnalyzerEngine
from app.services.docx_formatter.engine.fixability_matrix import (
    apply_fixability_to_finding,
    classify_fixability,
)
from app.services.docx_formatter.engine.report_builder import ReportBuilder


class FixabilityMatrixTests(unittest.TestCase):
    def test_safe_format_errors_are_auto_fixable(self) -> None:
        for finding_type, group_id in [
            ("PAGE_MARGIN_ERROR", "page_setup"),
            ("PAPER_SIZE_ERROR", "page_setup"),
            ("PARAGRAPH_ALIGNMENT_ERROR", "body_paragraph"),
            ("HEADING_1_FONT_SIZE_ERROR", "heading"),
            ("LIST_ITEM_SPACE_AFTER_PT_ERROR", "list_item"),
            ("CAPTION_SPACE_BEFORE_PT_ERROR", "caption"),
            ("FRONT_MATTER_HEADING_ALIGNMENT_ERROR", "front_matter"),
            ("TABLE_CELL_FONT_NAME_ERROR", "table_cell_format"),
            ("HEADER_FOOTER_FONT_SIZE_ERROR", "header_footer_format"),
        ]:
            with self.subTest(finding_type=finding_type):
                spec = classify_fixability(finding_type, group_id=group_id)

                self.assertEqual(spec.scope, "safe_auto_fix")
                self.assertTrue(spec.auto_fixable)
                self.assertFalse(spec.manual_review)
                self.assertNotEqual(spec.fix_action["type"], "manual_review")

    def test_review_and_structural_errors_are_manual_review(self) -> None:
        for finding_type, group_id in [
            ("FIGURE_NUMBERING_MALFORMED_REVIEW", "caption"),
            ("PAGE_NUMBER_ALIGNMENT_REVIEW", "header_footer_page_number"),
            ("HEADER_FOOTER_LAYOUT_REVIEW", "header_footer_page_number"),
            ("TABLE_WIDTH_REVIEW", "table"),
            ("TOC_NOT_AUTOMATIC_REVIEW", "toc"),
        ]:
            with self.subTest(finding_type=finding_type):
                spec = classify_fixability(finding_type, group_id=group_id)

                self.assertEqual(spec.scope, "manual_review")
                self.assertFalse(spec.auto_fixable)
                self.assertTrue(spec.manual_review)
                self.assertEqual(spec.fix_action["type"], "manual_review")

    def test_matrix_overrides_unsafe_metadata(self) -> None:
        finding = Finding(
            type="FIGURE_NUMBERING_MALFORMED_REVIEW",
            severity="warning",
            location="Paragraph 10",
            message="Review numbering.",
            metadata={
                "report_group_id": "caption",
                "auto_fixable": True,
                "manual_review": False,
                "fix_action": {"type": "set_numbering"},
            },
        )

        normalized = apply_fixability_to_finding(finding)

        self.assertFalse(normalized.metadata["auto_fixable"])
        self.assertTrue(normalized.metadata["manual_review"])
        self.assertEqual(normalized.metadata["fixability_scope"], "manual_review")
        self.assertEqual(normalized.metadata["fix_action"]["type"], "manual_review")

    def test_analyzer_engine_normalizes_rule_findings(self) -> None:
        findings = AnalyzerEngine([_UnsafeAnalyzeRule()]).analyze(doc=None, config={})

        self.assertEqual(len(findings), 1)
        self.assertFalse(findings[0].metadata["auto_fixable"])
        self.assertTrue(findings[0].metadata["manual_review"])
        self.assertEqual(findings[0].metadata["fixability_scope"], "manual_review")

    def test_report_builder_exposes_fixability_scope(self) -> None:
        report = ReportBuilder().build(
            raw_findings=[
                {
                    "type": "LIST_ITEM_SPACE_AFTER_PT_ERROR",
                    "severity": "warning",
                    "location": "Paragraph 5",
                    "message": "Space after does not match the required format.",
                    "current_value": "12.0 pt",
                    "expected_value": "6.0 pt",
                    "suggestion": "Set space after to 6.0 pt.",
                    "metadata": {
                        "report_group_id": "list_item",
                        "field": "space_after_pt",
                        "style_name": "List Paragraph",
                    },
                },
                {
                    "type": "PAGE_NUMBER_ALIGNMENT_REVIEW",
                    "severity": "warning",
                    "location": "Footer section 1",
                    "message": "Review footer page numbering.",
                    "metadata": {
                        "report_group_id": "header_footer_page_number",
                    },
                },
            ],
            document_id="doc-1",
            document_type="do_an_tot_nghiep",
        )

        issues = [
            issue
            for group in report["issue_groups"]
            for issue in group["issues"]
        ]
        by_type = {issue["rule"]["rule_id"]: issue for issue in issues}

        self.assertTrue(by_type["LIST_ITEM_SPACE_AFTER"]["auto_fixable"])
        self.assertEqual(by_type["LIST_ITEM_SPACE_AFTER"]["fixability_scope"], "safe_auto_fix")
        self.assertFalse(by_type["PAGE_NUMBER_ALIGNMENT"]["auto_fixable"])
        self.assertTrue(by_type["PAGE_NUMBER_ALIGNMENT"]["manual_review"])
        self.assertEqual(by_type["PAGE_NUMBER_ALIGNMENT"]["fix_action"]["type"], "manual_review")


class _UnsafeAnalyzeRule(AnalyzeRule):
    def analyze(self, doc, config):
        return [
            Finding(
                type="HEADER_FOOTER_LAYOUT_REVIEW",
                severity="warning",
                location="Footer section 1",
                message="Header/footer layout is unsafe to auto-fix.",
                metadata={
                    "report_group_id": "header_footer_page_number",
                    "auto_fixable": True,
                    "manual_review": False,
                    "fix_action": {"type": "set_header_footer_layout"},
                },
            )
        ]


if __name__ == "__main__":
    unittest.main()
