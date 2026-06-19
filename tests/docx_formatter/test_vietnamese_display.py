from __future__ import annotations

import unittest

from app.services.docx_formatter.engine.annotation_engine import AnnotationEngine
from app.services.docx_formatter.engine.report_builder import ReportBuilder
from app.services.docx_formatter.engine.vietnamese_text import normalize_vietnamese_display


class VietnameseDisplayTests(unittest.TestCase):
    def test_normalizes_blank_paragraph_review_text(self) -> None:
        self.assertEqual(
            normalize_vietnamese_display("Qua nhieu dong trong lien tiep"),
            "Quá nhiều dòng trống liên tiếp",
        )
        self.assertEqual(
            normalize_vietnamese_display("4 dong trong lien tiep"),
            "4 dòng trống liên tiếp",
        )
        self.assertEqual(normalize_vietnamese_display("JUSTIFY"), "Căn đều hai bên")
        self.assertEqual(normalize_vietnamese_display("LEFT"), "Căn trái")
        self.assertEqual(normalize_vietnamese_display("95 pages"), "95 trang")
        self.assertEqual(
            normalize_vietnamese_display("60-80 pages, excluding appendix"),
            "60-80 trang, không kể phụ lục",
        )
        self.assertEqual(
            normalize_vietnamese_display("CHƯƠNG 1. on one centered line; title on the next centered uppercase line."),
            'Dòng "CHƯƠNG 1." căn giữa; tiêu đề chương ở dòng ngay dưới, viết hoa và căn giữa.',
        )
        self.assertEqual(
            normalize_vietnamese_display("Khong vuot qua vùng nội dung 15.50 cm"),
            "Không vượt quá vùng nội dung 15.50 cm",
        )

    def test_report_builder_returns_accented_vietnamese_for_legacy_ascii_finding(self) -> None:
        report = ReportBuilder().build(
            raw_findings=[_legacy_blank_finding()],
            document_id="doc-1",
            document_type="do_an",
            filename="demo.docx",
            template_name="Đồ án",
            generated_at="2026-06-11T00:00:00+00:00",
        )

        issue = report["issue_groups"][0]["issues"][0]
        self.assertEqual(report["reference"]["rule_source"], "template_config")
        self.assertFalse(report["reference"]["sample_document_used_for_rules"])
        self.assertEqual(issue["rule"]["rule_name"], "Quá nhiều dòng trống liên tiếp")
        self.assertEqual(
            issue["message"],
            "Có nhiều dòng trống liên tiếp làm bố cục có thể bị vỡ.",
        )
        self.assertEqual(issue["current"]["blank_paragraphs"], "4 dòng trống liên tiếp")
        self.assertEqual(issue["current"]["_label"], "Dòng trống liên tiếp")
        self.assertIn("Kiểm tra các dòng trống thủ công", issue["suggestion"])

    def test_annotation_engine_returns_accented_vietnamese_for_legacy_ascii_finding(self) -> None:
        comments = AnnotationEngine().build_comments([_legacy_blank_finding()])

        self.assertEqual(len(comments), 1)
        issue = comments[0].issues[0]
        self.assertEqual(issue.title, "Quá nhiều dòng trống liên tiếp")
        self.assertEqual(issue.current_value, "Dòng trống liên tiếp: 4 dòng trống liên tiếp")
        self.assertIn("Không quá 2 dòng trống liên tiếp", issue.expected_value or "")
        self.assertIn("Kiểm tra các dòng trống thủ công", issue.suggestion or "")

    def test_annotation_comment_text_is_line_based_and_user_facing_vietnamese(self) -> None:
        comments = AnnotationEngine().build_comments(
            [
                _format_finding(
                    "PARAGRAPH_ALIGNMENT_ERROR",
                    field="alignment",
                    current_value="LEFT",
                    expected_value="JUSTIFY",
                    suggestion="Set alignment to JUSTIFY.",
                ),
                _legacy_blank_finding(),
            ]
        )

        text = "\n\n".join(comment.to_text() for comment in comments)

        self.assertIn("Lỗi: Căn đều hai bên cho đoạn văn nội dung", text)
        self.assertIn("Mô tả: Đoạn văn nội dung chưa được căn đều hai bên.", text)
        self.assertIn("Hiện tại: Căn lề: Căn trái", text)
        self.assertIn("Yêu cầu: Căn lề: Căn đều hai bên", text)
        self.assertIn("Gợi ý: Căn đều hai bên cho đoạn văn nội dung.", text)
        self.assertIn("Lỗi: Quá nhiều dòng trống liên tiếp", text)
        self.assertNotIn("JUSTIFY", text)
        self.assertNotIn("LEFT", text)
        self.assertNotIn("Khong", text)
        self.assertNotIn("does not match", text)
        self.assertNotIn("pages, excluding appendix", text)


def _legacy_blank_finding() -> dict:
    return {
        "type": "EXCESSIVE_BLANK_PARAGRAPHS_REVIEW",
        "severity": "warning",
        "location": "Paragraph 30",
        "message": "Co nhieu dong trong lien tiep lam bo cuc co the bi vo.",
        "current_value": "4 dong trong lien tiep",
        "expected_value": "Khong qua 2 dong trong lien tiep trong phan noi dung.",
        "suggestion": "Kiem tra cac dong trong thu cong; neu can xuong trang thi dung page break hoac section dung cach.",
        "metadata": {
            "target": "paragraph",
            "context": "layout_abnormal",
            "report_group_id": "layout_abnormal",
            "report_severity": "major",
            "paragraph_index": 30,
            "field": "blank_paragraphs",
            "auto_fixable": False,
            "manual_review": True,
            "fix_action": {
                "type": "manual_review",
                "reason": "Loi layout nay can kiem tra thu cong; he thong khong tu sua noi dung hoac cau truc phuc tap.",
            },
        },
    }


def _format_finding(
    finding_type: str,
    *,
    field: str,
    current_value: str,
    expected_value: str,
    suggestion: str,
) -> dict:
    return {
        "type": finding_type,
        "severity": "warning",
        "location": "Paragraph 30",
        "message": "Paragraph alignment does not match the required format.",
        "current_value": current_value,
        "expected_value": expected_value,
        "suggestion": suggestion,
        "metadata": {
            "target": "paragraph",
            "context": "body_paragraph",
            "report_group_id": "body_paragraph",
            "report_severity": "major",
            "paragraph_index": 30,
            "field": field,
            "auto_fixable": True,
            "manual_review": False,
            "fix_action": {
                "type": "paragraph_format",
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
