from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule
from app.services.docx_formatter.engine.caption_detector import CaptionKind, caption_label
from app.services.docx_formatter.engine.document_structure import (
    DocumentStructureIndex,
    ParagraphStructure,
    normalized_title_key,
)


class CaptionNumberingRule(AnalyzeRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        numbering_config = config.get("caption_numbering", {})
        if numbering_config.get("enabled", True) is False:
            return []

        structure = DocumentStructureIndex.build(doc)
        findings: list[Finding] = []
        seen_numbers: dict[tuple[str, str, str], int] = {}

        for paragraph in structure.paragraphs:
            caption = paragraph.caption
            if caption.kind is None or caption.status in {"not_caption", "body_reference"}:
                continue

            group_id = _group_id(caption.kind, paragraph)
            metadata = _metadata(paragraph, group_id)

            if caption.number is None:
                findings.append(
                    _manual_finding(
                        finding_type=f"{caption.kind.upper()}_NUMBERING_MISSING_REVIEW",
                        severity="warning",
                        location=f"Paragraph {paragraph.index}",
                        message="Dòng hình/bảng chưa có số thứ tự hợp lệ.",
                        current_value=paragraph.text_preview,
                        expected_value=f"{caption_label(caption.kind)} x.y. Tiêu đề",
                        suggestion="Kiểm tra lại số thứ tự hình/bảng; hệ thống không tự sửa số hoặc nội dung caption.",
                        metadata=metadata,
                    )
                )
                continue

            if caption.status in {"malformed", "missing_separator"}:
                findings.append(
                    _manual_finding(
                        finding_type=_malformed_type(caption.kind, caption.status),
                        severity="warning",
                        location=f"Paragraph {paragraph.index}",
                        message=_malformed_message(caption.status),
                        current_value=paragraph.text_preview,
                        expected_value=f"{caption_label(caption.kind)} {caption.number}. Tiêu đề",
                        suggestion=_malformed_suggestion(caption.kind, caption.status),
                        metadata=metadata,
                    )
                )

            if (
                caption.status == "valid"
                and paragraph.generated_list_region is None
                and paragraph.current_chapter is not None
                and caption.number.split(".", 1)[0] != paragraph.current_chapter
            ):
                label = caption_label(caption.kind)
                findings.append(
                    _manual_finding(
                        finding_type=f"{caption.kind.upper()}_NUMBERING_CHAPTER_MISMATCH_REVIEW",
                        severity="warning",
                        location=f"Paragraph {paragraph.index}",
                        message="Số chương trong caption không khớp với chương gần nhất.",
                        current_value=(
                            f"{label} {caption.number}; chương gần nhất được phát hiện: "
                            f"Chương {paragraph.current_chapter}"
                        ),
                        expected_value=(
                            f"Caption trong Chương {paragraph.current_chapter} nên dùng dạng "
                            f"{label} {paragraph.current_chapter}.x hoặc cần có tiêu đề Chương "
                            f"{caption.number.split('.', 1)[0]} trước caption này."
                        ),
                        suggestion=(
                            "Kiểm tra xem thiếu dòng Chương tương ứng, section bị cắt/ghép, "
                            "hoặc caption đang đánh sai prefix chương."
                        ),
                        metadata=metadata,
                    )
                )

            if caption.status == "valid" and paragraph.generated_list_region is None:
                key = (caption.kind, caption.number, group_id)
                previous_index = seen_numbers.get(key)
                if previous_index is not None:
                    findings.append(
                        _manual_finding(
                            finding_type=f"{caption.kind.upper()}_NUMBERING_DUPLICATE_REVIEW",
                            severity="warning",
                            location=f"Paragraph {paragraph.index}",
                            message="Số hình/bảng bị lặp trong cùng nhóm.",
                            current_value=f"{caption_label(caption.kind)} {caption.number}",
                            expected_value="Mỗi hình/bảng cần có số thứ tự duy nhất theo chương.",
                            suggestion="Kiểm tra lại caption/danh mục và cập nhật numbering nếu bị lặp.",
                            metadata={
                                **metadata,
                                "duplicate_of_paragraph_index": previous_index,
                            },
                        )
                    )
                else:
                    seen_numbers[key] = paragraph.index

        findings.extend(_generated_list_consistency_findings(structure))
        return findings


def _generated_list_consistency_findings(structure: DocumentStructureIndex) -> list[Finding]:
    findings: list[Finding] = []
    for region, entries in structure.generated_list_entries.items():
        by_number: dict[tuple[CaptionKind, str], list[Any]] = defaultdict(list)
        for entry in entries:
            by_number[(entry.kind, entry.number)].append(entry)

        for (_kind, _number), duplicates in by_number.items():
            if len(duplicates) <= 1:
                continue
            first = duplicates[0]
            for duplicate in duplicates[1:]:
                paragraph = structure.paragraph(duplicate.paragraph_index)
                if paragraph is None:
                    continue
                findings.append(
                    _manual_finding(
                        finding_type=f"{duplicate.kind.upper()}_LIST_DUPLICATE_REVIEW",
                        severity="warning",
                        location=f"Paragraph {duplicate.paragraph_index}",
                        message="Số hình/bảng bị lặp trong danh mục.",
                        current_value=f"{caption_label(duplicate.kind)} {duplicate.number}",
                        expected_value="Mỗi dòng trong danh mục cần trỏ tới một hình/bảng duy nhất.",
                        suggestion="Cập nhật lại danh mục hình/bảng trong Word và kiểm tra các caption bị lặp.",
                        metadata={
                            **_metadata(paragraph, region),
                            "duplicate_of_paragraph_index": first.paragraph_index,
                        },
                    )
                )

        for entry in entries:
            paragraph = structure.paragraph(entry.paragraph_index)
            if paragraph is None:
                continue

            body_caption = structure.body_caption(entry.kind, entry.number)
            if body_caption is None:
                findings.append(
                    _manual_finding(
                        finding_type=f"{entry.kind.upper()}_LIST_ENTRY_MISSING_TARGET_REVIEW",
                        severity="warning",
                        location=f"Paragraph {entry.paragraph_index}",
                        message="Dòng danh mục không tìm thấy caption tương ứng trong nội dung.",
                        current_value=f"{caption_label(entry.kind)} {entry.number}",
                        expected_value="Mỗi dòng danh mục cần có caption tương ứng trong phần nội dung.",
                        suggestion="Cập nhật lại danh mục hoặc kiểm tra caption trong nội dung có bị thiếu/sai số không.",
                        metadata=_metadata(paragraph, region),
                    )
                )
                continue

            if normalized_title_key(entry.title) and normalized_title_key(body_caption.title):
                if normalized_title_key(entry.title) != normalized_title_key(body_caption.title):
                    findings.append(
                        _manual_finding(
                            finding_type=f"{entry.kind.upper()}_LIST_TITLE_MISMATCH_REVIEW",
                            severity="warning",
                            location=f"Paragraph {entry.paragraph_index}",
                            message="Tiêu đề trong danh mục không khớp với caption trong nội dung.",
                            current_value=entry.title,
                            expected_value=body_caption.title,
                            suggestion="Cập nhật lại danh mục hình/bảng sau khi chỉnh caption trong nội dung.",
                            metadata={
                                **_metadata(paragraph, region),
                                "body_caption_paragraph_index": body_caption.paragraph_index,
                            },
                        )
                    )

    return findings


def _metadata(paragraph: ParagraphStructure, group_id: str) -> dict[str, Any]:
    return {
        "target": "caption" if paragraph.context == "caption" else "paragraph",
        "context": paragraph.context,
        "report_group_id": group_id,
        "report_severity": "major",
        "paragraph_index": paragraph.index,
        "field": "caption_numbering",
        "text_preview": paragraph.text_preview,
        "style_name": paragraph.style_name,
        "current_chapter": paragraph.current_chapter,
        "caption_status": paragraph.caption.status,
    }


def _group_id(kind: CaptionKind, paragraph: ParagraphStructure) -> str:
    if paragraph.generated_list_region is not None:
        return paragraph.generated_list_region
    if paragraph.context == "list_of_figures":
        return "list_of_figures"
    if paragraph.context == "list_of_tables":
        return "list_of_tables"
    return "caption"


def _malformed_type(kind: CaptionKind, status: str) -> str:
    if status == "missing_separator":
        return f"{kind.upper()}_NUMBERING_MISSING_SEPARATOR_REVIEW"
    return f"{kind.upper()}_NUMBERING_MALFORMED_REVIEW"


def _malformed_message(status: str) -> str:
    if status == "missing_separator":
        return "Caption hoặc dòng danh mục thiếu dấu chấm/dấu hai chấm sau số thứ tự."
    return "Số hình/bảng bị rối hoặc không đúng mẫu đánh số."


def _malformed_suggestion(kind: CaptionKind, status: str) -> str:
    label = caption_label(kind)
    if status == "missing_separator":
        return f"Đưa về mẫu {label} x.y. Tiêu đề hoặc {label} x.y: Tiêu đề; không viết dính với câu dẫn."
    return f"Kiểm tra lại số thứ tự; mẫu chuẩn chỉ nên có dạng {label} x.y."


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
                "reason": "Cần kiểm tra caption/danh mục thủ công; hệ thống không tự sửa số hoặc nội dung caption.",
            },
        },
    )
