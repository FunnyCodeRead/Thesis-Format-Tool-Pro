from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.services.docx_formatter.domain.finding import Finding


MAX_LOCATIONS = 5

FIELD_LABELS = {
    "alignment": "Căn lề",
    "bold": "In đậm",
    "first_line_indent_cm": "Thụt đầu dòng",
    "font_name": "Font chữ",
    "font_size": "Cỡ chữ",
    "line_spacing": "Giãn dòng",
    "margin_top_cm": "Lề trên",
    "margin_bottom_cm": "Lề dưới",
    "margin_left_cm": "Lề trái",
    "margin_right_cm": "Lề phải",
    "paper_size": "Khổ giấy",
    "space_before_pt": "Khoảng cách trước đoạn",
    "space_after_pt": "Khoảng cách sau đoạn",
    "uppercase": "Viết hoa",
}

VALUE_LABELS = {
    "JUSTIFY": "Căn đều hai bên",
    "LEFT": "Căn trái",
    "CENTER": "Căn giữa",
    "RIGHT": "Căn phải",
    "not set": "Chưa thiết lập",
    "not uppercase": "Chưa viết hoa",
    "uppercase": "Viết hoa",
    "true": "Có",
    "false": "Không",
}

TITLE_BY_TYPE = {
    "PAGE_SETUP_GROUP": "Thiết lập trang/căn lề",
    "PAGE_MARGIN_ERROR": "Căn lề trang",
    "PAPER_SIZE_ERROR": "Khổ giấy",
    "PARAGRAPH_ALIGNMENT_ERROR": "Căn đều đoạn văn",
    "PARAGRAPH_FIRST_LINE_INDENT_ERROR": "Thụt đầu dòng",
    "PARAGRAPH_LINE_SPACING_ERROR": "Giãn dòng",
    "PARAGRAPH_SPACE_BEFORE_PT_ERROR": "Khoảng cách trước đoạn",
    "PARAGRAPH_SPACE_AFTER_PT_ERROR": "Khoảng cách sau đoạn",
    "PARAGRAPH_FONT_NAME_ERROR": "Font chữ đoạn văn",
    "PARAGRAPH_FONT_SIZE_ERROR": "Cỡ chữ đoạn văn",
    "PARAGRAPH_BOLD_ERROR": "In đậm đoạn văn",
    "HEADING_1_ALIGNMENT_ERROR": "Căn lề heading cấp 1",
    "HEADING_1_SPACE_BEFORE_PT_ERROR": "Khoảng cách trước heading cấp 1",
    "HEADING_1_SPACE_AFTER_PT_ERROR": "Khoảng cách sau heading cấp 1",
    "HEADING_1_FONT_NAME_ERROR": "Font chữ heading cấp 1",
    "HEADING_1_FONT_SIZE_ERROR": "Cỡ chữ heading cấp 1",
    "HEADING_1_BOLD_ERROR": "In đậm heading cấp 1",
    "HEADING_1_UPPERCASE_ERROR": "Viết hoa heading cấp 1",
    "HEADING_2_ALIGNMENT_ERROR": "Căn lề heading cấp 2",
    "HEADING_2_SPACE_BEFORE_PT_ERROR": "Khoảng cách trước heading cấp 2",
    "HEADING_2_SPACE_AFTER_PT_ERROR": "Khoảng cách sau heading cấp 2",
    "HEADING_2_FONT_NAME_ERROR": "Font chữ heading cấp 2",
    "HEADING_2_FONT_SIZE_ERROR": "Cỡ chữ heading cấp 2",
    "HEADING_2_BOLD_ERROR": "In đậm heading cấp 2",
    "HEADING_2_UPPERCASE_ERROR": "Viết hoa heading cấp 2",
}

MESSAGE_BY_TYPE = {
    "PARAGRAPH_ALIGNMENT_ERROR": "Có {count} đoạn văn chưa căn đều hai bên.",
    "PARAGRAPH_FIRST_LINE_INDENT_ERROR": "Có {count} đoạn văn sai thụt đầu dòng.",
    "PARAGRAPH_LINE_SPACING_ERROR": "Có {count} đoạn văn sai giãn dòng.",
    "PARAGRAPH_SPACE_BEFORE_PT_ERROR": "Có {count} đoạn văn sai khoảng cách trước đoạn.",
    "PARAGRAPH_SPACE_AFTER_PT_ERROR": "Có {count} đoạn văn sai khoảng cách sau đoạn.",
    "PARAGRAPH_FONT_NAME_ERROR": "Có {count} đoạn văn sai font chữ.",
    "PARAGRAPH_FONT_SIZE_ERROR": "Có {count} đoạn văn có cỡ chữ không đồng nhất hoặc chưa đúng yêu cầu.",
    "PARAGRAPH_BOLD_ERROR": "Có {count} đoạn văn sai định dạng in đậm.",
    "HEADING_1_ALIGNMENT_ERROR": "Có {count} heading cấp 1 sai căn lề.",
    "HEADING_1_SPACE_BEFORE_PT_ERROR": "Có {count} heading cấp 1 sai khoảng cách trước.",
    "HEADING_1_SPACE_AFTER_PT_ERROR": "Có {count} heading cấp 1 sai khoảng cách sau.",
    "HEADING_1_FONT_NAME_ERROR": "Có {count} heading cấp 1 sai font chữ.",
    "HEADING_1_FONT_SIZE_ERROR": "Có {count} heading cấp 1 có cỡ chữ không đồng nhất hoặc chưa đúng yêu cầu.",
    "HEADING_1_BOLD_ERROR": "Có {count} heading cấp 1 sai định dạng in đậm.",
    "HEADING_1_UPPERCASE_ERROR": "Có {count} heading cấp 1 chưa viết hoa.",
    "HEADING_2_ALIGNMENT_ERROR": "Có {count} heading cấp 2 sai căn lề.",
    "HEADING_2_SPACE_BEFORE_PT_ERROR": "Có {count} heading cấp 2 sai khoảng cách trước.",
    "HEADING_2_SPACE_AFTER_PT_ERROR": "Có {count} heading cấp 2 sai khoảng cách sau.",
    "HEADING_2_FONT_NAME_ERROR": "Có {count} heading cấp 2 sai font chữ.",
    "HEADING_2_FONT_SIZE_ERROR": "Có {count} heading cấp 2 có cỡ chữ không đồng nhất hoặc chưa đúng yêu cầu.",
    "HEADING_2_BOLD_ERROR": "Có {count} heading cấp 2 sai định dạng in đậm.",
    "HEADING_2_UPPERCASE_ERROR": "Có {count} heading cấp 2 chưa viết hoa.",
}

SUGGESTION_BY_TYPE = {
    "PARAGRAPH_ALIGNMENT_ERROR": "Căn đều hai bên cho các đoạn văn nội dung.",
    "PARAGRAPH_FIRST_LINE_INDENT_ERROR": "Thiết lập thụt đầu dòng đúng theo quy chuẩn.",
    "PARAGRAPH_LINE_SPACING_ERROR": "Thiết lập lại giãn dòng cho các đoạn văn nội dung.",
    "PARAGRAPH_SPACE_BEFORE_PT_ERROR": "Thiết lập khoảng cách trước đoạn theo quy chuẩn.",
    "PARAGRAPH_SPACE_AFTER_PT_ERROR": "Thiết lập khoảng cách sau đoạn theo quy chuẩn.",
    "PARAGRAPH_FONT_NAME_ERROR": "Đổi font chữ đoạn văn về đúng font yêu cầu.",
    "PARAGRAPH_FONT_SIZE_ERROR": "Chọn đoạn văn và áp dụng lại style nội dung chuẩn: Times New Roman, đúng cỡ chữ yêu cầu.",
    "PARAGRAPH_BOLD_ERROR": "Thiết lập in đậm theo đúng quy chuẩn.",
    "HEADING_1_ALIGNMENT_ERROR": "Thiết lập lại căn lề cho heading cấp 1.",
    "HEADING_1_SPACE_BEFORE_PT_ERROR": "Thiết lập khoảng cách trước heading cấp 1.",
    "HEADING_1_SPACE_AFTER_PT_ERROR": "Thiết lập khoảng cách sau heading cấp 1.",
    "HEADING_1_FONT_NAME_ERROR": "Đổi font chữ heading cấp 1 về đúng font yêu cầu.",
    "HEADING_1_FONT_SIZE_ERROR": "Áp dụng lại style heading cấp 1 theo đúng cỡ chữ yêu cầu.",
    "HEADING_1_BOLD_ERROR": "Thiết lập in đậm cho heading cấp 1 theo quy chuẩn.",
    "HEADING_1_UPPERCASE_ERROR": "Bật định dạng viết hoa cho heading cấp 1.",
    "HEADING_2_ALIGNMENT_ERROR": "Thiết lập lại căn lề cho heading cấp 2.",
    "HEADING_2_SPACE_BEFORE_PT_ERROR": "Thiết lập khoảng cách trước heading cấp 2.",
    "HEADING_2_SPACE_AFTER_PT_ERROR": "Thiết lập khoảng cách sau heading cấp 2.",
    "HEADING_2_FONT_NAME_ERROR": "Đổi font chữ heading cấp 2 về đúng font yêu cầu.",
    "HEADING_2_FONT_SIZE_ERROR": "Áp dụng lại style heading cấp 2 theo đúng cỡ chữ yêu cầu.",
    "HEADING_2_BOLD_ERROR": "Thiết lập in đậm cho heading cấp 2 theo quy chuẩn.",
    "HEADING_2_UPPERCASE_ERROR": "Bật định dạng viết hoa cho heading cấp 2.",
}


class FindingGrouper:
    def group(self, findings: list[Finding]) -> list[Finding]:
        page_setup_errors: list[Finding] = []
        repeated_errors: dict[str, list[Finding]] = defaultdict(list)
        others: list[Finding] = []

        for finding in findings:
            if finding.type in {"PAGE_MARGIN_ERROR", "PAPER_SIZE_ERROR"}:
                page_setup_errors.append(finding)
            elif self._should_group(finding):
                repeated_errors[finding.type].append(finding)
            else:
                others.append(self._normalize_single_finding(finding))

        grouped: list[Finding] = []

        if page_setup_errors:
            grouped.append(self._group_page_setup(page_setup_errors))

        for finding_type, items in repeated_errors.items():
            grouped.append(self._group_repeated(finding_type, items))

        grouped.extend(others)
        return self._sort_findings(grouped)

    def _should_group(self, finding: Finding) -> bool:
        return finding.type.startswith(
            ("PARAGRAPH_", "HEADING_", "LIST_ITEM_", "FRONT_MATTER_HEADING_")
        )

    def _group_page_setup(self, items: list[Finding]) -> Finding:
        by_field: dict[str, list[Finding]] = defaultdict(list)

        for item in items:
            field = str(item.metadata.get("field") or "page_setup")
            by_field[field].append(item)

        details: list[dict[str, Any]] = []
        all_locations = self._sorted_locations(items)

        for field, field_items in by_field.items():
            locations = self._sorted_locations(field_items)
            current_values = self._human_values(item.current_value for item in field_items)
            expected_values = self._human_values(item.expected_value for item in field_items)

            details.append(
                {
                    "label": self._field_label(field),
                    "count": len(field_items),
                    "current_values": current_values,
                    "expected_values": expected_values,
                    "first_locations": locations[:MAX_LOCATIONS],
                    "hidden_count": max(0, len(locations) - MAX_LOCATIONS),
                }
            )

        return Finding(
            type="page_setup",
            severity="error",
            location=self._location_summary(all_locations),
            message=f"Có {len(items)} lỗi thiết lập trang/căn lề.",
            current_value=None,
            expected_value="Đúng quy chuẩn căn lề và khổ giấy của trường",
            suggestion="Áp dụng lại thiết lập trang cho toàn bộ section trong tài liệu.",
            metadata={
                "category": "page_setup",
                "title": "Thiết lập trang/căn lề",
                "total_items": len(items),
                "first_locations": all_locations[:MAX_LOCATIONS],
                "hidden_count": max(0, len(all_locations) - MAX_LOCATIONS),
                "details": details,
            },
        )

    def _group_repeated(self, finding_type: str, items: list[Finding]) -> Finding:
        first = items[0]
        locations = self._sorted_locations(items)

        return Finding(
            type=self._public_type(finding_type),
            severity=self._max_severity(items),
            location=self._location_summary(locations),
            message=self._message(finding_type, len(items)),
            current_value=self._current_summary(items),
            expected_value=self._human_value(first.expected_value),
            suggestion=self._suggestion(finding_type, first.suggestion),
            metadata={
                "category": self._category(finding_type),
                "title": self._title(finding_type),
                "total_items": len(items),
                "first_locations": locations[:MAX_LOCATIONS],
                "hidden_count": max(0, len(locations) - MAX_LOCATIONS),
            },
        )

    def _normalize_single_finding(self, finding: Finding) -> Finding:
        locations = [finding.location] if finding.location else []

        return Finding(
            type=self._public_type(finding.type),
            severity=finding.severity,
            location=finding.location,
            message=self._message(finding.type, 1),
            current_value=self._human_value(finding.current_value),
            expected_value=self._human_value(finding.expected_value),
            suggestion=self._suggestion(finding.type, finding.suggestion),
            metadata={
                "category": self._category(finding.type),
                "title": self._title(finding.type),
                "total_items": 1,
                "first_locations": locations,
                "hidden_count": 0,
            },
        )

    def _sorted_locations(self, items: list[Finding]) -> list[str]:
        unique = {item.location for item in items if item.location}
        return sorted(unique, key=self._location_sort_key)

    def _location_sort_key(self, location: str) -> tuple[int, int, str]:
        section_match = re.search(r"Section\s+(\d+)", location, re.IGNORECASE)
        if section_match:
            return (0, int(section_match.group(1)), location)

        paragraph_match = re.search(r"Paragraph\s+(\d+)", location, re.IGNORECASE)
        if paragraph_match:
            return (1, int(paragraph_match.group(1)), location)

        return (2, 0, location)

    def _location_summary(self, locations: list[str]) -> str | None:
        if not locations:
            return None
        first_locations = locations[:MAX_LOCATIONS]
        hidden_count = max(0, len(locations) - MAX_LOCATIONS)
        if hidden_count:
            return f"{', '.join(first_locations)} và {hidden_count} vị trí khác"
        return ", ".join(first_locations)

    def _sort_findings(self, findings: list[Finding]) -> list[Finding]:
        severity_order = {"error": 0, "warning": 1, "info": 2}
        category_order = {
            "page_setup": 0,
            "front_matter": 1,
            "heading": 2,
            "list_item": 3,
            "paragraph": 4,
            "other": 5,
        }

        return sorted(
            findings,
            key=lambda finding: (
                severity_order.get(finding.severity, 99),
                category_order.get(str(finding.metadata.get("category", "other")), 99),
                finding.type,
            ),
        )

    def _max_severity(self, items: list[Finding]) -> str:
        severities = {item.severity for item in items}

        if "error" in severities:
            return "error"
        if "warning" in severities:
            return "warning"
        return "info"

    def _current_summary(self, items: list[Finding]) -> str | None:
        values = self._human_values(item.current_value for item in items)
        if not values:
            return None
        if len(values) <= 3:
            return ", ".join(values)
        return None

    def _human_values(self, values: Any) -> list[str]:
        cleaned = {
            value
            for raw_value in values
            if (value := self._human_value(raw_value)) is not None
        }
        return sorted(cleaned)

    def _human_value(self, value: Any) -> str | None:
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        translated = VALUE_LABELS.get(text, VALUE_LABELS.get(text.upper()))
        if translated:
            return translated

        if self._is_technical_value(text):
            return None

        return text

    def _is_technical_value(self, value: str) -> bool:
        lowered = value.lower()
        if "issue(s)" in lowered or "occurrence(s)" in lowered:
            return True
        if lowered in FIELD_LABELS:
            return True
        if re.fullmatch(r"[A-Z0-9_]+(_ERROR|_GROUP)?", value):
            return True
        return False

    def _category(self, finding_type: str) -> str:
        source_type = finding_type.removesuffix("_GROUP")
        if source_type.startswith("PAGE_") or source_type.startswith("PAPER_"):
            return "page_setup"
        if source_type.startswith("HEADING_"):
            return "heading"
        if source_type.startswith("FRONT_MATTER_HEADING_"):
            return "front_matter"
        if source_type.startswith("LIST_ITEM_"):
            return "list_item"
        if source_type.startswith("PARAGRAPH_"):
            return "paragraph"
        return "other"

    def _field_label(self, field: str) -> str:
        return FIELD_LABELS.get(field, field.replace("_", " ").strip().title())

    def _title(self, finding_type: str) -> str:
        source_type = finding_type.removesuffix("_GROUP")
        if source_type.startswith("FRONT_MATTER_HEADING_"):
            return "Tiêu đề phần đầu tài liệu"
        if source_type.startswith("LIST_ITEM_"):
            return "Định dạng bullet/list"
        return TITLE_BY_TYPE.get(finding_type) or TITLE_BY_TYPE.get(source_type) or "Lỗi định dạng"

    def _public_type(self, finding_type: str) -> str:
        source_type = finding_type.removesuffix("_GROUP").removesuffix("_ERROR")
        if source_type in {"PAGE_MARGIN", "PAPER_SIZE"}:
            return "page_setup"
        return source_type.lower()

    def _message(self, finding_type: str, count: int) -> str:
        source_type = finding_type.removesuffix("_GROUP")
        template = MESSAGE_BY_TYPE.get(source_type)
        if template:
            return template.format(count=count)
        return f"Có {count} lỗi định dạng cần kiểm tra."

    def _suggestion(self, finding_type: str, fallback: str | None) -> str:
        source_type = finding_type.removesuffix("_GROUP")
        suggestion = SUGGESTION_BY_TYPE.get(source_type)
        if suggestion:
            return suggestion

        human_fallback = self._humanize_sentence(fallback)
        return human_fallback or "Điều chỉnh định dạng theo đúng quy chuẩn của trường."

    def _humanize_sentence(self, value: str | None) -> str | None:
        if not value:
            return None

        replacements = {
            "Set alignment to JUSTIFY.": "Căn đều hai bên theo quy chuẩn.",
            "Set alignment to LEFT.": "Căn trái theo quy chuẩn.",
            "Set alignment to CENTER.": "Căn giữa theo quy chuẩn.",
            "Set alignment to RIGHT.": "Căn phải theo quy chuẩn.",
            "Set paper size to A4.": "Thiết lập khổ giấy A4.",
        }
        return replacements.get(value, value)
