from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from app.services.docx_formatter.engine.context_classifier import classify_paragraph_context
from app.services.docx_formatter.rules.common_format import (
    ALIGNMENT_BY_NAME,
    CM_TOLERANCE,
    LINE_SPACING_TOLERANCE,
    PT_TOLERANCE,
)
from app.services.docx_formatter.utils.docx_units import close, length_to_cm, length_to_pt
from app.services.docx_formatter.utils.text_utils import heading_key

STYLE_FIX_MODE = "conservative_exclusive_style"
SAFE_STYLE_CONTEXTS = {"body_paragraph", "front_matter_heading", "list_item", "caption", "heading"}
DEFAULT_MIN_COUNTS = {
    "body_paragraph": 3,
    "front_matter_heading": 1,
    "list_item": 3,
    "caption": 2,
    "heading": 1,
}


@dataclass(frozen=True)
class _StyleUsage:
    context: str
    expected_id: str


@dataclass
class _StyleCandidate:
    style: Any
    style_key: str
    style_name: str
    context: str
    expected_id: str
    expected: dict[str, Any]
    paragraph_count: int = 0


class StyleLevelFixEngine:
    """Conservative style fixer for repeated safe formatting contexts.

    A style is updated only when every non-empty paragraph using that style belongs
    to the same safe context and expected-format bucket. Mixed styles still fall
    back to existing paragraph-level fix rules.
    """

    def fix(
        self,
        doc: Any,
        config: dict[str, Any],
        *,
        allowed_contexts: set[str] | None = None,
    ) -> dict[str, Any]:
        candidates, usages = self._collect_candidates(doc, config)
        min_counts = _min_counts(config)

        changes_by_style: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        total_changes = 0

        for candidate in sorted(candidates.values(), key=lambda item: (item.style_name, item.context)):
            if allowed_contexts is not None and candidate.context not in allowed_contexts:
                skipped.append(
                    {
                        "style_name": candidate.style_name,
                        "context": candidate.context,
                        "paragraph_count": candidate.paragraph_count,
                        "reason": "Nhóm định dạng này không nằm trong phạm vi sửa đã chọn.",
                    }
                )
                continue

            required_count = min_counts.get(candidate.context, 3)
            if candidate.paragraph_count < required_count:
                skipped.append(
                    {
                        "style_name": candidate.style_name,
                        "context": candidate.context,
                        "paragraph_count": candidate.paragraph_count,
                        "reason": "Không đủ số đoạn lặp lại để sửa ở cấp style.",
                    }
                )
                continue

            if not _style_usage_is_exclusive(candidate, usages.get(candidate.style_key, set())):
                skipped.append(
                    {
                        "style_name": candidate.style_name,
                        "context": candidate.context,
                        "paragraph_count": candidate.paragraph_count,
                        "reason": "Style đang dùng lẫn nhiều vùng tài liệu nên không sửa ở cấp style.",
                    }
                )
                continue

            changes, fields = self._apply_expected_to_style(candidate.style, candidate.expected)
            if changes <= 0:
                continue

            total_changes += changes
            changes_by_style.append(
                {
                    "style_name": candidate.style_name,
                    "context": candidate.context,
                    "paragraph_count": candidate.paragraph_count,
                    "changes": changes,
                    "fields": fields,
                }
            )

        return {
            "style_fix_mode": STYLE_FIX_MODE,
            "style_changes": total_changes,
            "style_fix_groups_applied": len(changes_by_style),
            "style_changes_by_style": changes_by_style,
            "style_fix_skipped": skipped,
        }

    def _collect_candidates(
        self,
        doc: Any,
        config: dict[str, Any],
    ) -> tuple[dict[tuple[str, str, str], _StyleCandidate], dict[str, set[_StyleUsage]]]:
        candidates: dict[tuple[str, str, str], _StyleCandidate] = {}
        usages: dict[str, set[_StyleUsage]] = defaultdict(set)

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            style = getattr(paragraph, "style", None)
            style_key = _style_key(style)
            if not style_key:
                continue

            context_info = classify_paragraph_context(paragraph, paragraph_index)
            context = context_info.context
            if context == "empty":
                continue

            expected_id, expected = _expected_for_context(paragraph, context, config)
            usage = _StyleUsage(str(context), expected_id or "")
            usages[style_key].add(usage)

            if context not in SAFE_STYLE_CONTEXTS or expected is None or expected_id is None:
                continue

            key = (style_key, str(context), expected_id)
            if key not in candidates:
                candidates[key] = _StyleCandidate(
                    style=style,
                    style_key=style_key,
                    style_name=_style_name(style),
                    context=str(context),
                    expected_id=expected_id,
                    expected=expected,
                )
            candidates[key].paragraph_count += 1

        return candidates, usages

    def _apply_expected_to_style(self, style: Any, expected: dict[str, Any]) -> tuple[int, list[str]]:
        changes = 0
        fields: list[str] = []
        paragraph_format = getattr(style, "paragraph_format", None)
        font = getattr(style, "font", None)
        if paragraph_format is None or font is None:
            return changes, fields

        expected_alignment = str(expected.get("alignment", "")).upper()
        if expected_alignment in ALIGNMENT_BY_NAME:
            current_alignment = _effective_style_paragraph_attr(style, "alignment")
            expected_value = ALIGNMENT_BY_NAME[expected_alignment]
            if current_alignment != expected_value:
                paragraph_format.alignment = expected_value
                changes += 1
                fields.append("alignment")

        first_line_indent_cm = expected.get("first_line_indent_cm")
        if first_line_indent_cm is not None:
            current_cm = length_to_cm(_effective_style_paragraph_attr(style, "first_line_indent"))
            if not close(current_cm, float(first_line_indent_cm), CM_TOLERANCE):
                paragraph_format.first_line_indent = Cm(float(first_line_indent_cm))
                changes += 1
                fields.append("first_line_indent_cm")

        line_spacing = expected.get("line_spacing")
        if line_spacing is not None:
            current_spacing = _effective_style_paragraph_attr(style, "line_spacing")
            if not _line_spacing_matches(current_spacing, float(line_spacing)):
                paragraph_format.line_spacing = float(line_spacing)
                changes += 1
                fields.append("line_spacing")

        for config_key, attr_name in (
            ("space_before_pt", "space_before"),
            ("space_after_pt", "space_after"),
        ):
            expected_pt = expected.get(config_key)
            if expected_pt is None:
                continue
            current_pt = length_to_pt(_effective_style_paragraph_attr(style, attr_name))
            if not close(current_pt, float(expected_pt), PT_TOLERANCE):
                setattr(paragraph_format, attr_name, Pt(float(expected_pt)))
                changes += 1
                fields.append(config_key)

        font_name = expected.get("font_name")
        if font_name:
            current_font_name = _effective_style_font_attr(style, "name")
            if current_font_name is None or current_font_name.casefold() != str(font_name).casefold():
                _set_style_font_name(style, str(font_name))
                changes += 1
                fields.append("font_name")

        font_size = expected.get("font_size")
        if font_size is not None:
            current_size = length_to_pt(_effective_style_font_attr(style, "size"))
            if current_size is None or not close(current_size, float(font_size), PT_TOLERANCE):
                font.size = Pt(float(font_size))
                changes += 1
                fields.append("font_size")

        if "bold" in expected:
            expected_bold = bool(expected["bold"])
            current_bold = _effective_style_font_attr(style, "bold")
            if bool(current_bold) != expected_bold:
                font.bold = expected_bold
                changes += 1
                fields.append("bold")

        if expected.get("uppercase") is True and hasattr(font, "all_caps"):
            if getattr(font, "all_caps", None) is not True:
                font.all_caps = True
                changes += 1
                fields.append("uppercase")

        return changes, fields


def _expected_for_context(paragraph: Any, context: str, config: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    if context == "body_paragraph":
        return "body_paragraph", dict(config.get("paragraph", {}))
    if context == "list_item":
        return "list_item", _list_item_expected_config(config)
    if context == "front_matter_heading":
        return "front_matter_heading", _front_matter_expected_config(config)
    if context == "caption":
        return "caption", _caption_expected_config(config)
    if context == "heading":
        key = heading_key(paragraph)
        heading_configs = config.get("headings", {})
        if key is None or key not in heading_configs:
            return None, None
        return key, dict(heading_configs[key])
    return None, None


def _list_item_expected_config(config: dict[str, Any]) -> dict[str, Any]:
    paragraph_config = config.get("paragraph", {})
    list_config = config.get("list_item", {})
    return {
        "font_name": list_config.get("font_name", paragraph_config.get("font_name", "Times New Roman")),
        "font_size": list_config.get("font_size", paragraph_config.get("font_size", 13)),
        "line_spacing": list_config.get("line_spacing", paragraph_config.get("line_spacing", 1.3)),
        "space_before_pt": list_config.get("space_before_pt", paragraph_config.get("space_before_pt", 6)),
        "space_after_pt": list_config.get("space_after_pt", paragraph_config.get("space_after_pt", 6)),
    }


def _caption_expected_config(config: dict[str, Any]) -> dict[str, Any]:
    paragraph_config = config.get("paragraph", {})
    caption_config = config.get("caption", config.get("caption_format", {}))
    return {
        "font_name": caption_config.get("font_name", paragraph_config.get("font_name", "Times New Roman")),
        "font_size": caption_config.get("font_size", paragraph_config.get("font_size", 13)),
        "alignment": caption_config.get("alignment", "CENTER"),
        "space_before_pt": caption_config.get("space_before_pt", paragraph_config.get("space_before_pt", 6)),
        "space_after_pt": caption_config.get("space_after_pt", paragraph_config.get("space_after_pt", 6)),
    }


def _front_matter_expected_config(config: dict[str, Any]) -> dict[str, Any]:
    paragraph_config = config.get("paragraph", {})
    front_matter_config = config.get("front_matter_heading", {})
    return {
        "font_name": front_matter_config.get("font_name", paragraph_config.get("font_name", "Times New Roman")),
        "font_size": front_matter_config.get("font_size", paragraph_config.get("font_size", 13)),
        "bold": front_matter_config.get("bold", True),
        "uppercase": front_matter_config.get("uppercase", True),
        "alignment": front_matter_config.get("alignment", "CENTER"),
        "space_after_pt": front_matter_config.get("space_after_pt", paragraph_config.get("space_after_pt", 6)),
    }


def _style_usage_is_exclusive(candidate: _StyleCandidate, usages: set[_StyleUsage]) -> bool:
    return usages == {_StyleUsage(candidate.context, candidate.expected_id)}


def _min_counts(config: dict[str, Any]) -> dict[str, int]:
    style_fix_config = config.get("style_fix", {})
    configured = style_fix_config.get("min_paragraphs_by_context", {})
    result = dict(DEFAULT_MIN_COUNTS)
    if isinstance(configured, dict):
        for key, value in configured.items():
            try:
                result[str(key)] = max(1, int(value))
            except (TypeError, ValueError):
                continue
    return result


def _style_key(style: Any) -> str | None:
    if style is None:
        return None
    style_id = str(getattr(style, "style_id", "") or "").strip()
    if style_id:
        return style_id
    name = _style_name(style)
    return name or None


def _style_name(style: Any) -> str:
    return str(getattr(style, "name", "") or "").strip()


def _style_chain(style: Any) -> list[Any]:
    chain: list[Any] = []
    seen: set[int] = set()
    current = style
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = getattr(current, "base_style", None)
    return chain


def _effective_style_paragraph_attr(style: Any, attr_name: str) -> Any:
    for item in _style_chain(style):
        style_format = getattr(item, "paragraph_format", None)
        if style_format is None:
            continue
        value = getattr(style_format, attr_name, None)
        if value is not None:
            return value
    return None


def _effective_style_font_attr(style: Any, attr_name: str) -> Any:
    for item in _style_chain(style):
        font = getattr(item, "font", None)
        if font is None:
            continue
        value = getattr(font, attr_name, None)
        if value is not None:
            return value
    if attr_name == "bold":
        return False
    return None


def _line_spacing_matches(current: Any, expected: float) -> bool:
    if current is None:
        return False
    if isinstance(current, (float, int)):
        return abs(float(current) - expected) <= LINE_SPACING_TOLERANCE
    return False


def _set_style_font_name(style: Any, font_name: str) -> None:
    style.font.name = font_name
    style_element = getattr(style, "element", None)
    if style_element is None:
        style_element = getattr(style, "_element", None)
    if style_element is None:
        return

    if hasattr(style_element, "get_or_add_rPr"):
        r_pr = style_element.get_or_add_rPr()
    else:
        r_pr = style_element.find(qn("w:rPr"))
        if r_pr is None:
            r_pr = OxmlElement("w:rPr")
            style_element.append(r_pr)

    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.append(r_fonts)

    for attribute_name in ("w:ascii", "w:hAnsi", "w:eastAsia"):
        r_fonts.set(qn(attribute_name), font_name)
