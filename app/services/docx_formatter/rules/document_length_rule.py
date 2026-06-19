from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule


class DocumentLengthRule(AnalyzeRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        length_config = config.get("document_length", {})
        if length_config.get("enabled", True) is False:
            return []

        page_count = _document_page_count(doc)
        if page_count is None:
            return []

        min_pages = int(length_config.get("min_content_pages", 60))
        max_pages = int(length_config.get("max_content_pages", 80))
        if min_pages <= page_count <= max_pages:
            return []

        if page_count > max_pages:
            message = "Tài liệu có dấu hiệu vượt quá số trang theo quy định."
            suggestion = "Kiểm tra số trang nội dung chính; yêu cầu thường là 60-80 trang không kể phụ lục."
        else:
            message = "Tài liệu có dấu hiệu ngắn hơn số trang theo quy định."
            suggestion = "Kiểm tra lại phạm vi nội dung chính nếu quy định yêu cầu tối thiểu số trang."

        return [
            Finding(
                type="DOCUMENT_PAGE_COUNT_REVIEW",
                severity="warning",
                location="Thuộc tính tài liệu",
                message=message,
                current_value=f"{page_count} trang",
                expected_value=f"{min_pages}-{max_pages} trang, không kể phụ lục",
                suggestion=suggestion,
                metadata={
                    "target": "section",
                    "context": "document_length",
                    "report_group_id": "document_length",
                    "report_severity": "major",
                    "field": "page_count",
                    "auto_fixable": False,
                    "manual_review": True,
                    "fix_action": {
                        "type": "manual_review",
                        "reason": "Số trang cần kiểm tra theo bản render và phạm vi phụ lục; hệ thống không tự xóa/rút gọn nội dung.",
                    },
                },
            )
        ]


def _document_page_count(doc: Any) -> int | None:
    try:
        parts = doc.part.package.parts
    except AttributeError:
        return None

    for part in parts:
        if str(getattr(part, "partname", "")) != "/docProps/app.xml":
            continue
        try:
            root = ET.fromstring(part.blob)
        except ET.ParseError:
            return None
        for element in root.iter():
            if element.tag.endswith("Pages") and element.text:
                try:
                    return int(element.text)
                except ValueError:
                    return None
    return None
