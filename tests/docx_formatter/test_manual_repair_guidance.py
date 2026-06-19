from __future__ import annotations

import unittest

from app.services.docx_formatter.engine.report_builder import ReportBuilder


class ManualRepairGuidanceTests(unittest.TestCase):
    def test_manual_review_issue_gets_repair_guidance(self) -> None:
        report = ReportBuilder().build(
            raw_findings=[_toc_not_automatic_finding()],
            document_id="doc-1",
            document_type="do_an_tot_nghiep",
            filename="demo.docx",
            template_name="Đồ án tốt nghiệp",
            generated_at="2026-06-16T00:00:00+00:00",
        )

        issue_group = report["issue_groups"][0]
        issue = issue_group["issues"][0]
        repair = issue["repair"]

        self.assertTrue(issue["manual_review"])
        self.assertEqual(repair["guide_id"], "manual_toc")
        self.assertEqual(repair["tool"], "Microsoft Word")
        self.assertIn("References > Table of Contents", " ".join(repair["steps"]))
        self.assertIn("manual_repair_guidance", issue_group)
        self.assertEqual(issue_group["manual_repair_guidance"][0]["guide_id"], "manual_toc")
        self.assertEqual(report["summary"]["manual_repair_guidance"][0]["guide_id"], "manual_toc")
        self.assertEqual(report["manual_repair_guidance"][0]["guide_id"], "manual_toc")

    def test_auto_fixable_issue_does_not_require_manual_repair(self) -> None:
        report = ReportBuilder().build(
            raw_findings=[_paragraph_alignment_finding()],
            document_id="doc-1",
            document_type="do_an_tot_nghiep",
            filename="demo.docx",
            template_name="Đồ án tốt nghiệp",
            generated_at="2026-06-16T00:00:00+00:00",
        )

        issue = report["issue_groups"][0]["issues"][0]
        self.assertFalse(issue["manual_review"])
        self.assertIsNone(issue["repair"])
        self.assertEqual(report["summary"]["manual_repair_guidance"], [])
        self.assertEqual(report["manual_repair_guidance"], [])


def _toc_not_automatic_finding() -> dict:
    return {
        "type": "TOC_NOT_AUTOMATIC_REVIEW",
        "severity": "warning",
        "location": "Paragraph 12",
        "message": "Mục lục có thể đang được gõ tay, chưa phải TOC field tự động.",
        "current_value": "MỤC LỤC",
        "expected_value": "Mục lục nên được tạo bằng TOC field để cập nhật heading và số trang.",
        "suggestion": "Dùng References > Table of Contents hoặc Update Table trong Word thay vì gõ tay.",
        "metadata": {
            "target": "paragraph",
            "context": "toc",
            "report_group_id": "toc",
            "report_severity": "major",
            "paragraph_index": 12,
            "field": "toc_structure",
            "auto_fixable": False,
            "manual_review": True,
            "fix_action": {
                "type": "manual_review",
                "reason": "Mục lục là field/cấu trúc Word phức tạp nên chỉ report, không auto-fix.",
            },
        },
    }


def _paragraph_alignment_finding() -> dict:
    return {
        "type": "PARAGRAPH_ALIGNMENT_ERROR",
        "severity": "warning",
        "location": "Paragraph 30",
        "message": "Căn lề đoạn văn chưa đúng yêu cầu.",
        "current_value": "căn trái",
        "expected_value": "căn đều hai bên",
        "suggestion": "Đặt căn lề thành căn đều hai bên.",
        "metadata": {
            "target": "paragraph",
            "context": "body_paragraph",
            "report_group_id": "body_paragraph",
            "report_severity": "minor",
            "paragraph_index": 30,
            "field": "alignment",
            "auto_fixable": True,
            "manual_review": False,
            "fix_action": {
                "type": "set_paragraph_alignment",
                "value": "JUSTIFY",
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
