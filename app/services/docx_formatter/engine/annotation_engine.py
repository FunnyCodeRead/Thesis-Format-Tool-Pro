from __future__ import annotations

import json
import re
from collections import OrderedDict, defaultdict
from typing import Any

from app.services.docx_formatter.domain.annotation import (
    AnnotationComment,
    AnnotationIssue,
    AnnotationTarget,
    AnnotationTargetKind,
)
from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.engine.report_builder import (
    FIELD_LABELS,
    MESSAGE_BY_TYPE,
    SUGGESTION_BY_TYPE,
    get_rule_identity,
)
from app.services.docx_formatter.engine.vietnamese_text import normalize_vietnamese_display

HYBRID_STYLE_GROUP_MIN_FINDINGS = 10
STYLE_GROUP_CONTEXTS = {"body_paragraph", "heading", "front_matter_heading", "list_item"}
STYLE_GROUP_FIELDS = {
    "alignment",
    "bold",
    "first_line_indent_cm",
    "font_name",
    "font_size",
    "line_spacing",
    "space_before_pt",
    "space_after_pt",
    "uppercase",
}


class AnnotationEngine:
    def build_comments(self, findings: list[dict[str, Any]]) -> list[AnnotationComment]:
        raw_findings = [_finding_from_dict(finding, index) for index, finding in enumerate(findings, start=1)]
        sorted_findings = sorted(raw_findings, key=_finding_sort_key)

        style_buckets: dict[tuple[str, str, str, str], list[Finding]] = defaultdict(list)
        direct_findings: list[Finding] = []
        for finding in sorted_findings:
            style_key = _style_group_key(finding)
            if style_key is None:
                direct_findings.append(finding)
                continue
            style_buckets[style_key].append(finding)

        comments: list[AnnotationComment] = []
        grouped_issue_ids: set[str] = set()
        for bucket_items in style_buckets.values():
            if len(bucket_items) < HYBRID_STYLE_GROUP_MIN_FINDINGS:
                direct_findings.extend(bucket_items)
                continue
            comments.append(_style_group_comment(bucket_items))
            grouped_issue_ids.update(_issue_id(item) for item in bucket_items)

        comments_by_locator: OrderedDict[tuple[object, ...], list[Finding]] = OrderedDict()
        for finding in sorted(direct_findings, key=_finding_sort_key):
            if _issue_id(finding) in grouped_issue_ids:
                continue
            target = _target_for_finding(finding)
            key = target.locator_key()
            comments_by_locator.setdefault(key, []).append(finding)

        comments.extend(
            _comment_from_findings(target=_target_for_finding(items[0]), items=items)
            for items in comments_by_locator.values()
        )
        return sorted(comments, key=_comment_sort_key)


def _finding_from_dict(row: dict[str, Any], index: int) -> Finding:
    metadata = row.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}

    metadata = {
        **metadata,
        "annotation_issue_id": metadata.get("annotation_issue_id") or f"FINDING-{index:04d}",
    }

    return Finding(
        type=str(row.get("type") or "FORMAT_ERROR"),
        severity=str(row.get("severity") or "warning"),
        location=str(row.get("location") or ""),
        message=str(row.get("message") or "Formatting issue."),
        current_value=row.get("current_value"),
        expected_value=row.get("expected_value"),
        suggestion=row.get("suggestion"),
        metadata=metadata,
    )


def _comment_from_findings(target: AnnotationTarget, items: list[Finding]) -> AnnotationComment:
    issues = [_issue_from_finding(finding) for finding in items]
    title = _comment_title(target, issues)
    severity = _max_severity(items)

    return AnnotationComment(
        title=title,
        message=f"Có {len(items)} lỗi định dạng tại vị trí này.",
        severity=severity,
        target=target,
        issues=issues,
        source_type=",".join(issue.source_type for issue in issues),
    )


def _style_group_comment(items: list[Finding]) -> AnnotationComment:
    sorted_items = sorted(items, key=_finding_sort_key)
    first = sorted_items[0]
    metadata = _metadata(first)
    target = _target_for_finding(first)
    _, rule_name = get_rule_identity(first.type, metadata)
    style_name = _style_name(first)
    source_ids = [_issue_id(item) for item in sorted_items]
    sample_locations = _sample_locations(sorted_items)
    message = (
        f"Có {len(sorted_items)} lỗi lặp lại theo kiểu định dạng \"{style_name}\". "
        "Nên sửa kiểu định dạng gốc trong Word thay vì sửa từng đoạn thủ công."
    )
    if sample_locations:
        message = f"{message} Vị trí mẫu: {', '.join(sample_locations)}."

    issue = AnnotationIssue(
        issue_id=source_ids[0],
        title=f"Sửa kiểu định dạng {style_name}: {normalize_vietnamese_display(rule_name)}",
        message=message,
        source_type=first.type,
        current_value=_value_with_field_label(metadata.get("field"), first.current_value),
        expected_value=_value_with_field_label(metadata.get("field"), first.expected_value),
        suggestion=(
            f"Mở ngăn Kiểu định dạng trong Word, chỉnh \"{style_name}\" theo yêu cầu rồi áp dụng lại cho "
            "các đoạn đang dùng kiểu định dạng này."
        ),
        field=str(metadata.get("field")) if metadata.get("field") else None,
    )
    return AnnotationComment(
        title=issue.title,
        message=message,
        severity=_max_severity(sorted_items),
        target=target,
        issues=[issue],
        source_type=f"style_group:{first.type}",
        source_count_override=len(sorted_items),
        source_ids_override=source_ids,
    )


def _issue_from_finding(finding: Finding) -> AnnotationIssue:
    metadata = _metadata(finding)
    _, rule_name = get_rule_identity(finding.type, metadata)

    return AnnotationIssue(
        issue_id=_issue_id(finding),
        title=normalize_vietnamese_display(rule_name),
        message=normalize_vietnamese_display(
            MESSAGE_BY_TYPE.get(finding.type) or _clean_sentence(finding.message)
        ),
        source_type=finding.type,
        current_value=_value_with_field_label(metadata.get("field"), finding.current_value),
        expected_value=_value_with_field_label(metadata.get("field"), finding.expected_value),
        suggestion=normalize_vietnamese_display(
            SUGGESTION_BY_TYPE.get(finding.type) or _clean_sentence(finding.suggestion)
        ),
        field=str(metadata.get("field")) if metadata.get("field") else None,
    )


def _target_for_finding(finding: Finding) -> AnnotationTarget:
    metadata = _metadata(finding)
    target = _normalize_target_kind(metadata, finding)

    section_index = _int_or_none(metadata.get("section_index"))
    paragraph_index = _int_or_none(metadata.get("paragraph_index"))
    table_index = _int_or_none(metadata.get("table_index"))
    row_index = _int_or_none(metadata.get("row_index"))
    cell_index = _int_or_none(metadata.get("cell_index"))
    table_paragraph_index = _int_or_none(metadata.get("table_paragraph_index"))
    part_paragraph_index = _int_or_none(metadata.get("part_paragraph_index"))

    if paragraph_index is None:
        paragraph_index = _paragraph_index_from_location(finding.location)
    if section_index is None:
        section_index = _section_index_from_location(finding.location)

    if target == "section" and section_index is None:
        section_index = 1

    return AnnotationTarget(
        target=target,
        section_index=section_index,
        paragraph_index=paragraph_index,
        table_index=table_index,
        row_index=row_index,
        cell_index=cell_index,
        table_paragraph_index=table_paragraph_index,
        part_paragraph_index=part_paragraph_index,
        field=str(metadata.get("field")) if metadata.get("field") else None,
        location=finding.location or None,
    )


def _normalize_target_kind(metadata: dict[str, Any], finding: Finding) -> AnnotationTargetKind:
    raw_target = str(metadata.get("target") or metadata.get("context") or "").strip()
    group_id = str(metadata.get("report_group_id") or metadata.get("category") or "").strip()

    if raw_target in {"section", "paragraph", "heading", "caption", "table_cell", "header", "footer"}:
        return raw_target  # type: ignore[return-value]

    if group_id == "page_setup" or finding.type.startswith(("PAGE_MARGIN", "PAPER_SIZE")):
        return "section"
    if group_id == "header_footer_page_number":
        return "footer"
    if group_id == "caption":
        return "caption"
    if group_id == "table":
        return "table_cell"
    if finding.type.startswith("HEADING_"):
        return "heading"

    return "paragraph"


def _style_group_key(finding: Finding) -> tuple[str, str, str, str] | None:
    metadata = _metadata(finding)
    if metadata.get("manual_review") is True or metadata.get("auto_fixable") is False:
        return None

    group_id = str(metadata.get("report_group_id") or metadata.get("context") or "")
    context = str(metadata.get("context") or "")
    field = str(metadata.get("field") or "")
    if group_id not in STYLE_GROUP_CONTEXTS and context not in STYLE_GROUP_CONTEXTS:
        return None
    if field not in STYLE_GROUP_FIELDS:
        return None
    if not finding.type.endswith("_ERROR"):
        return None

    expected = "" if finding.expected_value is None else normalize_vietnamese_display(finding.expected_value)
    return (_style_name(finding), finding.type, field, expected)


def _style_name(finding: Finding) -> str:
    metadata = _metadata(finding)
    style_name = str(metadata.get("style_name") or "").strip()
    context = str(metadata.get("context") or "").strip()
    return style_name or context or "Không xác định"


def _sample_locations(items: list[Finding], limit: int = 5) -> list[str]:
    result: list[str] = []
    for finding in items:
        location = str(finding.location or "").strip()
        if not location:
            paragraph_index = _int_or_none(_metadata(finding).get("paragraph_index"))
            location = f"Paragraph {paragraph_index}" if paragraph_index else ""
        if location and location not in result:
            result.append(location)
        if len(result) >= limit:
            break
    return result


def _finding_sort_key(finding: Finding) -> tuple[int, int, int, int, int, int, int, str]:
    target = _target_for_finding(finding)
    target_order = {
        "section": 0,
        "header": 1,
        "footer": 2,
        "heading": 3,
        "paragraph": 4,
        "caption": 5,
        "table_cell": 6,
    }
    return (
        target_order.get(target.target, 99),
        target.section_index or 0,
        target.paragraph_index or 0,
        target.table_index or 0,
        target.row_index or 0,
        target.cell_index or 0,
        target.table_paragraph_index or 0,
        finding.type,
    )


def _comment_sort_key(comment: AnnotationComment) -> tuple[int, int, int, int, int, int, int, str]:
    target = comment.target
    target_order = {
        "section": 0,
        "header": 1,
        "footer": 2,
        "heading": 3,
        "paragraph": 4,
        "caption": 5,
        "table_cell": 6,
    }
    return (
        target_order.get(target.target, 99),
        target.section_index or 0,
        target.paragraph_index or 0,
        target.table_index or 0,
        target.row_index or 0,
        target.cell_index or 0,
        target.table_paragraph_index or 0,
        comment.title,
    )


def _comment_title(target: AnnotationTarget, issues: list[AnnotationIssue]) -> str:
    if len(issues) == 1:
        return issues[0].title

    label = {
        "section": "section",
        "header": "đầu trang",
        "footer": "chân trang",
        "heading": "heading",
        "paragraph": "đoạn văn",
        "caption": "caption",
        "table_cell": "ô bảng",
    }.get(target.target, "vị trí")

    return f"{len(issues)} lỗi định dạng trong cùng {label}"


def _max_severity(items: list[Finding]) -> str:
    severities = {item.severity for item in items}
    if "error" in severities:
        return "error"
    if "warning" in severities:
        return "warning"
    return "info"


def _value_with_field_label(field: Any, value: Any) -> str | None:
    if value is None:
        return None

    text = normalize_vietnamese_display(str(value).strip())
    if not text:
        return None

    if not field:
        return text

    label = normalize_vietnamese_display(FIELD_LABELS.get(str(field), str(field).replace("_", " ")))
    return f"{label}: {text}"


def _clean_sentence(value: Any) -> str | None:
    if value is None:
        return None
    text = normalize_vietnamese_display(str(value).strip())
    if not text:
        return None

    replacements = {
        "Formatting issue.": "Cần kiểm tra định dạng tại vị trí này.",
        "Paragraph alignment does not match the required format.": "Căn lề đoạn văn chưa đúng yêu cầu.",
        "First-line indent does not match the required format.": "Thụt đầu dòng chưa đúng yêu cầu.",
        "Line spacing does not match the required format.": "Giãn dòng chưa đúng yêu cầu.",
        "Space before does not match the required format.": "Khoảng cách trước đoạn chưa đúng yêu cầu.",
        "Space after does not match the required format.": "Khoảng cách sau đoạn chưa đúng yêu cầu.",
        "Font name does not match the required format.": "Font chữ chưa đúng yêu cầu.",
        "Font size is inconsistent or does not match the required format.": "Cỡ chữ không đồng nhất hoặc chưa đúng yêu cầu.",
        "Bold formatting does not match the required format.": "Định dạng in đậm chưa đúng yêu cầu.",
        "Heading text is not uppercase.": "Heading chưa viết hoa theo yêu cầu.",
        "Review list item formatting; keep bullet/number indentation controlled by Word list settings.": (
            "Kiểm tra định dạng bullet/list; giữ thụt lề theo thiết lập danh sách của Word, "
            "không ép như đoạn văn thường."
        ),
    }
    translated = replacements.get(text)
    if translated:
        return translated

    instruction = _translate_set_instruction(text)
    return normalize_vietnamese_display(instruction or text)


def _translate_set_instruction(text: str) -> str | None:
    alignment_match = re.fullmatch(r"Set alignment to ([A-Z]+)\.", text)
    if alignment_match:
        alignment_labels = {
            "JUSTIFY": "căn đều hai bên",
            "LEFT": "căn trái",
            "CENTER": "căn giữa",
            "RIGHT": "căn phải",
        }
        value = alignment_labels.get(alignment_match.group(1), alignment_match.group(1))
        return f"Đặt căn lề thành {value}."

    generic_match = re.fullmatch(r"Set (.+) to (.+)\.", text)
    if not generic_match:
        return None

    field = generic_match.group(1).strip().lower()
    value = generic_match.group(2).strip()
    field_labels = {
        "top margin": "lề trên",
        "bottom margin": "lề dưới",
        "left margin": "lề trái",
        "right margin": "lề phải",
        "first-line indent": "thụt đầu dòng",
        "line spacing": "giãn dòng",
        "space before": "khoảng cách trước đoạn",
        "space after": "khoảng cách sau đoạn",
        "font name": "font chữ",
        "bold formatting": "định dạng in đậm",
        "paper size": "khổ giấy",
    }
    label = field_labels.get(field, field)
    return f"Đặt {label} thành {value}."


def _metadata(finding: Finding) -> dict[str, Any]:
    return finding.metadata if isinstance(finding.metadata, dict) else {}


def _issue_id(finding: Finding) -> str:
    return str(_metadata(finding).get("annotation_issue_id") or finding.type)


def _paragraph_index_from_location(location: str | None) -> int | None:
    if not location:
        return None
    match = re.search(r"Paragraph\s+(\d+)", location, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _section_index_from_location(location: str | None) -> int | None:
    if not location:
        return None
    match = re.search(r"Section\s+(\d+)", location, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
