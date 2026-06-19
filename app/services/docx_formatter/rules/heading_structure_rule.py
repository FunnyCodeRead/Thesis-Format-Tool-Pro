from __future__ import annotations

from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule
from app.services.docx_formatter.engine.document_structure import DocumentStructureIndex, ParagraphStructure


class HeadingStructureRule(AnalyzeRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        chapter_config = config.get("chapter_layout", {})
        if chapter_config.get("enabled", True) is False:
            return []

        structure = DocumentStructureIndex.build(doc)
        findings: list[Finding] = []
        for paragraph in structure.paragraphs:
            if paragraph.heading_number is None or paragraph.heading_chapter is None:
                continue
            if paragraph.current_chapter is None:
                continue
            if paragraph.heading_chapter == paragraph.current_chapter:
                continue

            findings.append(_chapter_mismatch_finding(paragraph))

        return findings


def _chapter_mismatch_finding(paragraph: ParagraphStructure) -> Finding:
    return Finding(
        type="HEADING_CHAPTER_MISMATCH_REVIEW",
        severity="warning",
        location=f"Paragraph {paragraph.index}",
        message="Tiểu mục không khớp với chương hiện tại.",
        current_value=(
            f"Tiểu mục {paragraph.heading_number}; chương gần nhất được phát hiện: "
            f"Chương {paragraph.current_chapter}"
        ),
        expected_value=(
            f"Tiểu mục trong Chương {paragraph.current_chapter} nên bắt đầu bằng "
            f"{paragraph.current_chapter}.x, hoặc cần bổ sung dòng Chương {paragraph.heading_chapter} trước đó."
        ),
        suggestion=(
            "Kiểm tra cấu trúc chương/section break; có thể thiếu dòng Chương tương ứng "
            "hoặc tài liệu bị ghép sai thứ tự."
        ),
        metadata={
            "target": "heading" if paragraph.context == "heading" else "paragraph",
            "context": paragraph.context,
            "report_group_id": "chapter_layout",
            "report_severity": "major",
            "paragraph_index": paragraph.index,
            "field": "chapter_layout",
            "text_preview": paragraph.text_preview,
            "style_name": paragraph.style_name,
            "current_chapter": paragraph.current_chapter,
            "heading_number": paragraph.heading_number,
            "auto_fixable": False,
            "manual_review": True,
            "fix_action": {
                "type": "manual_review",
                "reason": "Cần kiểm tra cấu trúc chương thủ công; hệ thống không tự đổi số hoặc nội dung heading.",
            },
        },
    )
