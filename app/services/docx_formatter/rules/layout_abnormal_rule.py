from __future__ import annotations

import re
from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule
from app.services.docx_formatter.engine.context_classifier import (
    classify_paragraph_context,
    text_preview,
)


BODY_LIKE_CONTEXTS = {
    "body_paragraph",
    "heading",
    "chapter_number",
    "chapter_title",
    "list_item",
}


class LayoutAbnormalRule(AnalyzeRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        layout_config = config.get("layout_abnormal", {})
        if layout_config.get("enabled", True) is False:
            return []

        max_blank = int(layout_config.get("max_consecutive_blank_paragraphs", 2))
        findings: list[Finding] = []
        blank_streak = 0

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            raw_text = getattr(paragraph, "text", "") or ""
            stripped = raw_text.strip()
            context = classify_paragraph_context(paragraph, paragraph_index)
            xml = getattr(getattr(paragraph, "_p", None), "xml", "")

            if not stripped:
                blank_streak += 1
                if paragraph_index > 25 and blank_streak > max_blank:
                    findings.append(
                        _manual_finding(
                            finding_type="EXCESSIVE_BLANK_PARAGRAPHS_REVIEW",
                            severity="warning",
                            location=f"Paragraph {paragraph_index}",
                            message="Có nhiều dòng trống liên tiếp làm bố cục có thể bị vỡ.",
                            current_value=f"{blank_streak} dòng trống liên tiếp",
                            expected_value=f"Không quá {max_blank} dòng trống liên tiếp trong phần nội dung.",
                            suggestion="Kiểm tra các dòng trống thủ công; nếu cần xuống trang thì dùng page break hoặc section đúng cách.",
                            metadata=_paragraph_metadata(
                                paragraph_index=paragraph_index,
                                context="layout_abnormal",
                                group_id="layout_abnormal",
                                field="blank_paragraphs",
                                text=raw_text,
                                style_name=context.style_name,
                            ),
                        )
                    )
                continue

            blank_streak = 0

            if context.context in BODY_LIKE_CONTEXTS and _has_manual_spacing(raw_text):
                findings.append(
                    _manual_finding(
                        finding_type="MANUAL_SPACING_REVIEW",
                        severity="warning",
                        location=f"Paragraph {paragraph_index}",
                        message="Đoạn văn có dấu hiệu căn lề bằng dấu cách hoặc tab thủ công.",
                        current_value=text_preview(raw_text),
                        expected_value="Căn lề và thụt đầu dòng nên dùng paragraph style, không dùng dấu cách hoặc tab thủ công.",
                        suggestion="Xóa căn lề thủ công nếu có và áp dụng lại style định dạng phù hợp trong Word.",
                        metadata=_paragraph_metadata(
                            paragraph_index=paragraph_index,
                            context=context.context,
                            group_id="layout_abnormal",
                            field="manual_spacing",
                            text=raw_text,
                            style_name=context.style_name,
                        ),
                    )
                )

            if context.context == "list_item" and _uses_manual_list_marker(paragraph, raw_text):
                findings.append(
                    _manual_finding(
                        finding_type="MANUAL_LIST_MARKER_REVIEW",
                        severity="warning",
                        location=f"Paragraph {paragraph_index}",
                        message="Dòng danh sách có thể đang dùng dấu bullet hoặc số thủ công.",
                        current_value=text_preview(raw_text),
                        expected_value="Bullet/number nên được tạo bằng Word list settings.",
                        suggestion="Kiểm tra lại list settings trong Word để tránh lề bullet bị lệch khi auto format.",
                        metadata=_paragraph_metadata(
                            paragraph_index=paragraph_index,
                            context="list_item",
                            group_id="list_item",
                            field="list_marker",
                            text=raw_text,
                            style_name=context.style_name,
                        ),
                    )
                )

            if _has_manual_page_break(xml):
                findings.append(
                    _manual_finding(
                        finding_type="MANUAL_PAGE_BREAK_REVIEW",
                        severity="warning",
                        location=f"Paragraph {paragraph_index}",
                        message="Đoạn này có page break thủ công.",
                        current_value=text_preview(raw_text) or "Ngắt trang trong đoạn",
                        expected_value="Ngắt trang chỉ nên dùng tại vị trí tách trang có chủ ý.",
                        suggestion="Kiểm tra page break thủ công; nếu nó làm sai đánh số trang hoặc bố cục thì điều chỉnh trong Word.",
                        metadata=_paragraph_metadata(
                            paragraph_index=paragraph_index,
                            context=context.context,
                            group_id="layout_abnormal",
                            field="manual_page_break",
                            text=raw_text,
                            style_name=context.style_name,
                        ),
                    )
                )

            if _has_section_break(xml):
                findings.append(
                    _manual_finding(
                        finding_type="SECTION_BREAK_REVIEW",
                        severity="warning",
                        location=f"Paragraph {paragraph_index}",
                        message="Đoạn này có section break cần kiểm tra.",
                        current_value=text_preview(raw_text) or "Section break trong paragraph",
                        expected_value="Section break phải khớp với vùng bìa, phần đầu, nội dung chính và phụ lục.",
                        suggestion="Kiểm tra section break, footer và đánh số trang quanh vị trí này.",
                        metadata=_paragraph_metadata(
                            paragraph_index=paragraph_index,
                            context=context.context,
                            group_id="layout_abnormal",
                            field="section_break",
                            text=raw_text,
                            style_name=context.style_name,
                        ),
                    )
                )

            if "<w:hyperlink" in xml:
                findings.append(
                    _manual_finding(
                        finding_type="HYPERLINK_REVIEW",
                        severity="info",
                        location=f"Paragraph {paragraph_index}",
                        message="Đoạn này có hyperlink cần kiểm tra style.",
                        current_value=text_preview(raw_text),
                        expected_value="Liên kết nếu được phép dùng vẫn phải theo style trình bày của tài liệu.",
                        suggestion="Kiểm tra màu chữ, gạch chân và tính hợp lệ của hyperlink trong Word.",
                        metadata=_paragraph_metadata(
                            paragraph_index=paragraph_index,
                            context=context.context,
                            group_id="layout_abnormal",
                            field="hyperlink",
                            text=raw_text,
                            style_name=context.style_name,
                        ),
                    )
                )

        findings.extend(_document_xml_findings(doc))
        return findings


def _paragraph_metadata(
    *,
    paragraph_index: int,
    context: str,
    group_id: str,
    field: str,
    text: str,
    style_name: str,
) -> dict[str, Any]:
    return {
        "target": "paragraph",
        "context": context,
        "report_group_id": group_id,
        "report_severity": "major",
        "paragraph_index": paragraph_index,
        "field": field,
        "text_preview": text_preview(text),
        "style_name": style_name,
    }


def _manual_finding(
    *,
    finding_type: str,
    severity: str,
    location: str,
    message: str,
    current_value: str | None,
    expected_value: str | None,
    suggestion: str,
    metadata: dict[str, Any],
) -> Finding:
    return Finding(
        type=finding_type,
        severity=severity,
        location=location,
        message=message,
        current_value=current_value,
        expected_value=expected_value,
        suggestion=suggestion,
        metadata={
            **metadata,
            "auto_fixable": False,
            "manual_review": True,
            "fix_action": {
                "type": "manual_review",
                "reason": "Lỗi layout này cần kiểm tra thủ công; hệ thống không tự sửa nội dung hoặc cấu trúc phức tạp.",
            },
        },
    )


def _has_manual_spacing(text: str) -> bool:
    if "\t" in text:
        return True
    return bool(re.match(r"^[ ]{2,}\S", text))


def _uses_manual_list_marker(paragraph: Any, text: str) -> bool:
    if _has_numbering_properties(paragraph):
        return False
    stripped = text.lstrip()
    return stripped.startswith(("- ", "* ", "\u2022", "\u00b7", "\u25cf", "\u25aa", "\u25ab"))


def _has_numbering_properties(paragraph: Any) -> bool:
    p_pr = getattr(getattr(paragraph, "_p", None), "pPr", None)
    return getattr(p_pr, "numPr", None) is not None


def _has_manual_page_break(xml: str) -> bool:
    return "<w:br" in xml and 'w:type="page"' in xml


def _has_section_break(xml: str) -> bool:
    return "<w:sectPr" in xml


def _document_xml_findings(doc: Any) -> list[Finding]:
    findings: list[Finding] = []
    package_text = _package_xml_text(doc)

    if any(marker in package_text for marker in ("word/comments.xml", "commentRangeStart", "commentReference")):
        findings.append(
            _manual_finding(
                finding_type="COMMENTS_REVIEW",
                severity="warning",
                location="Document",
                message="Tài liệu còn comment hoặc dấu vết nhận xét cần kiểm tra.",
                current_value="Phát hiện comment/review markup trong gói .docx",
                expected_value="File nộp nên sạch comment nếu quy định yêu cầu.",
                suggestion="Mở Word, kiểm tra thẻ Review và xóa comment trước khi nộp nếu cần.",
                metadata={
                    "target": "paragraph",
                    "context": "layout_abnormal",
                    "report_group_id": "layout_abnormal",
                    "report_severity": "major",
                    "paragraph_index": 1,
                    "field": "comment_artifact",
                    "text_preview": "Document-level review",
                    "style_name": "",
                    "auto_fixable": False,
                    "manual_review": True,
                },
            )
        )

    if _has_track_changes_marker(package_text):
        findings.append(
            _manual_finding(
                finding_type="TRACK_CHANGES_REVIEW",
                severity="warning",
                location="Document",
                message="Tài liệu có track changes thật cần kiểm tra trước khi nộp.",
                current_value="Phát hiện w:trackRevisions/w:ins/w:del/w:moveFrom/w:moveTo trong gói .docx",
                expected_value="File nộp nên accept hoặc reject toàn bộ track changes trước khi format tự động.",
                suggestion="Mở Word và xử lý Track Changes trong thẻ Review, sau đó upload lại file sạch.",
                metadata={
                    "target": "paragraph",
                    "context": "layout_abnormal",
                    "report_group_id": "layout_abnormal",
                    "report_severity": "major",
                    "paragraph_index": 1,
                    "field": "track_changes",
                    "text_preview": "Document-level review",
                    "style_name": "",
                    "auto_fixable": False,
                    "manual_review": True,
                },
            )
        )
    return findings


def _has_track_changes_marker(package_text: str) -> bool:
    return bool(
        re.search(r"<w:(trackRevisions|ins|del|moveFrom|moveTo)(\s|/|>)", package_text)
    )


def _package_xml_text(doc: Any) -> str:
    chunks: list[str] = []
    try:
        parts = doc.part.package.parts
    except AttributeError:
        return ""

    for part in parts:
        partname = str(getattr(part, "partname", ""))
        if partname.endswith(".xml"):
            chunks.append(partname)
        try:
            blob = part.blob
        except (AttributeError, ValueError):
            continue
        if not isinstance(blob, bytes):
            continue
        try:
            chunks.append(blob.decode("utf-8", errors="ignore"))
        except AttributeError:
            continue
    return "\n".join(chunks)
