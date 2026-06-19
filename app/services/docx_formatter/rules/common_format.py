from __future__ import annotations

from typing import Any

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, Twips

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.utils.docx_units import (
    close,
    format_cm,
    format_line_spacing,
    format_pt,
    length_to_cm,
    length_to_pt,
)

CM_TOLERANCE = 0.08
PT_TOLERANCE = 0.5
LINE_SPACING_TOLERANCE = 0.05
RUN_FORMAT_MISMATCH_RATIO_THRESHOLD = 0.2
RUN_FORMAT_MIN_MISMATCH_CHARS = 12

ALIGNMENT_BY_NAME = {
    "LEFT": WD_ALIGN_PARAGRAPH.LEFT,
    "CENTER": WD_ALIGN_PARAGRAPH.CENTER,
    "RIGHT": WD_ALIGN_PARAGRAPH.RIGHT,
    "JUSTIFY": WD_ALIGN_PARAGRAPH.JUSTIFY,
}

ALIGNMENT_LABELS = {
    WD_ALIGN_PARAGRAPH.LEFT: "LEFT",
    WD_ALIGN_PARAGRAPH.CENTER: "CENTER",
    WD_ALIGN_PARAGRAPH.RIGHT: "RIGHT",
    WD_ALIGN_PARAGRAPH.JUSTIFY: "JUSTIFY",
}

ALIGNMENT_BY_XML_VALUE = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "both": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "distribute": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "thaiDistribute": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "mediumKashida": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "highKashida": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "lowKashida": WD_ALIGN_PARAGRAPH.JUSTIFY,
}


class CommonFormatMixin:
    def analyze_common_format(
        self,
        *,
        paragraph: Any,
        expected: dict[str, Any],
        location: str,
        type_prefix: str,
        metadata: dict[str, Any],
    ) -> list[Finding]:
        findings: list[Finding] = []

        expected_alignment = str(expected.get("alignment", "")).upper()
        if expected_alignment:
            current_alignment = self._effective_alignment(paragraph)
            if current_alignment is not None and current_alignment != ALIGNMENT_BY_NAME.get(expected_alignment):
                findings.append(
                    Finding(
                        type=f"{type_prefix}_ALIGNMENT_ERROR",
                        severity="warning",
                        location=location,
                        message="Căn lề đoạn văn chưa đúng yêu cầu.",
                        current_value=self._alignment_label(current_alignment),
                        expected_value=self._expected_alignment_label(expected_alignment),
                        suggestion=f"Đặt căn lề thành {self._expected_alignment_label(expected_alignment)}.",
                        metadata=self._finding_metadata(
                            metadata,
                            "alignment",
                            {"type": "set_paragraph_alignment", "value": expected_alignment},
                        ),
                    )
                )

        expected_indent_cm = expected.get("first_line_indent_cm")
        if expected_indent_cm is not None:
            current_indent_cm = length_to_cm(self._effective_paragraph_attr(paragraph, "first_line_indent"))
            if current_indent_cm is not None and not close(current_indent_cm, float(expected_indent_cm), CM_TOLERANCE):
                findings.append(
                    Finding(
                        type=f"{type_prefix}_FIRST_LINE_INDENT_ERROR",
                        severity="warning",
                        location=location,
                        message="Thụt đầu dòng chưa đúng yêu cầu.",
                        current_value=format_cm(current_indent_cm),
                        expected_value=format_cm(float(expected_indent_cm)),
                        suggestion=f"Đặt thụt đầu dòng thành {format_cm(float(expected_indent_cm))}.",
                        metadata=self._finding_metadata(
                            metadata,
                            "first_line_indent_cm",
                            {
                                "type": "set_first_line_indent",
                                "value": float(expected_indent_cm),
                                "unit": "cm",
                            },
                        ),
                    )
                )

        expected_line_spacing = expected.get("line_spacing")
        if expected_line_spacing is not None:
            current_line_spacing = self._effective_paragraph_attr(paragraph, "line_spacing")
            if current_line_spacing is not None and not self._line_spacing_matches(current_line_spacing, float(expected_line_spacing)):
                findings.append(
                    Finding(
                        type=f"{type_prefix}_LINE_SPACING_ERROR",
                        severity="warning",
                        location=location,
                        message="Giãn dòng chưa đúng yêu cầu.",
                        current_value=format_line_spacing(current_line_spacing),
                        expected_value=f"{float(expected_line_spacing):.2f}",
                        suggestion=f"Đặt giãn dòng thành {float(expected_line_spacing):.2f}.",
                        metadata=self._finding_metadata(
                            metadata,
                            "line_spacing",
                            {"type": "set_line_spacing", "value": float(expected_line_spacing)},
                        ),
                    )
                )

        for config_key, attr_name, label in [
            ("space_before_pt", "space_before", "Khoảng cách trước đoạn"),
            ("space_after_pt", "space_after", "Khoảng cách sau đoạn"),
        ]:
            expected_pt = expected.get(config_key)
            if expected_pt is None:
                continue

            current_pt = length_to_pt(self._effective_paragraph_attr(paragraph, attr_name))
            if current_pt is not None and not close(current_pt, float(expected_pt), PT_TOLERANCE):
                findings.append(
                    Finding(
                        type=f"{type_prefix}_{config_key.upper()}_ERROR",
                        severity="warning",
                        location=location,
                        message=f"{label} chưa đúng yêu cầu.",
                        current_value=format_pt(current_pt),
                        expected_value=format_pt(float(expected_pt)),
                        suggestion=f"Đặt {label.lower()} thành {format_pt(float(expected_pt))}.",
                        metadata=self._finding_metadata(
                            metadata,
                            config_key,
                            {
                                "type": f"set_{config_key}",
                                "value": float(expected_pt),
                                "unit": "pt",
                            },
                        ),
                    )
                )

        findings.extend(
            self.analyze_run_format(
                paragraph=paragraph,
                expected=expected,
                location=location,
                type_prefix=type_prefix,
                metadata=metadata,
            )
        )

        return findings

    def analyze_run_format(
        self,
        *,
        paragraph: Any,
        expected: dict[str, Any],
        location: str,
        type_prefix: str,
        metadata: dict[str, Any],
    ) -> list[Finding]:
        findings: list[Finding] = []
        runs = [run for run in paragraph.runs if run.text.strip()]
        if not runs:
            return findings

        expected_font_name = expected.get("font_name")
        if expected_font_name:
            font_name_mismatch = self._run_font_name_mismatch(
                runs,
                paragraph,
                str(expected_font_name),
            )
            if font_name_mismatch is not None:
                findings.append(
                    Finding(
                        type=f"{type_prefix}_FONT_NAME_ERROR",
                        severity="warning",
                        location=location,
                        message="Font chữ chưa đúng yêu cầu.",
                        current_value=font_name_mismatch,
                        expected_value=str(expected_font_name),
                        suggestion=f"Đặt font chữ thành {expected_font_name}.",
                        metadata=self._finding_metadata(
                            metadata,
                            "font_name",
                            {"type": "set_font_name", "value": str(expected_font_name)},
                        ),
                    )
                )

        expected_font_size = expected.get("font_size")
        if expected_font_size is not None:
            font_size_mismatch = self._run_font_size_mismatch(
                runs,
                paragraph,
                float(expected_font_size),
            )
            if font_size_mismatch is not None:
                findings.append(
                    Finding(
                        type=f"{type_prefix}_FONT_SIZE_ERROR",
                        severity="warning",
                        location=location,
                        message="Cỡ chữ không đồng nhất hoặc chưa đúng yêu cầu.",
                        current_value=font_size_mismatch,
                        expected_value=format_pt(float(expected_font_size)),
                        suggestion="Áp dụng lại style chuẩn cho đoạn này.",
                        metadata=self._finding_metadata(
                            metadata,
                            "font_size",
                            {
                                "type": "set_font_size",
                                "value": float(expected_font_size),
                                "unit": "pt",
                            },
                        ),
                    )
                )

        if "bold" in expected:
            expected_bold = bool(expected["bold"])
            for run in runs:
                current_bold = self._effective_run_bold(run, paragraph)
                if current_bold != expected_bold:
                    findings.append(
                        Finding(
                            type=f"{type_prefix}_BOLD_ERROR",
                            severity="warning",
                            location=location,
                            message="Định dạng in đậm chưa đúng yêu cầu.",
                            current_value="có" if current_bold else "không",
                            expected_value="có" if expected_bold else "không",
                            suggestion="Điều chỉnh định dạng in đậm theo quy chuẩn.",
                            metadata=self._finding_metadata(
                                metadata,
                                "bold",
                                {"type": "set_bold", "value": expected_bold},
                            ),
                        )
                    )
                    break

        return findings

    def fix_common_format(self, paragraph: Any, expected: dict[str, Any]) -> int:
        changes = 0
        paragraph_format = paragraph.paragraph_format

        expected_alignment = str(expected.get("alignment", "")).upper()
        if expected_alignment in ALIGNMENT_BY_NAME:
            if paragraph_format.alignment != ALIGNMENT_BY_NAME[expected_alignment]:
                paragraph_format.alignment = ALIGNMENT_BY_NAME[expected_alignment]
                changes += 1

        first_line_indent_cm = expected.get("first_line_indent_cm")
        if first_line_indent_cm is not None:
            current_indent_cm = length_to_cm(self._effective_paragraph_attr(paragraph, "first_line_indent"))
            if not close(current_indent_cm, float(first_line_indent_cm), CM_TOLERANCE):
                paragraph_format.first_line_indent = Cm(float(first_line_indent_cm))
                changes += 1

        line_spacing = expected.get("line_spacing")
        if line_spacing is not None:
            current_spacing = self._effective_paragraph_attr(paragraph, "line_spacing")
            if not self._line_spacing_matches(current_spacing, float(line_spacing)):
                paragraph_format.line_spacing = float(line_spacing)
                changes += 1

        space_before_pt = expected.get("space_before_pt")
        if space_before_pt is not None:
            current_pt = length_to_pt(self._effective_paragraph_attr(paragraph, "space_before"))
            if not close(current_pt, float(space_before_pt), PT_TOLERANCE):
                paragraph_format.space_before = Pt(float(space_before_pt))
                changes += 1

        space_after_pt = expected.get("space_after_pt")
        if space_after_pt is not None:
            current_pt = length_to_pt(self._effective_paragraph_attr(paragraph, "space_after"))
            if not close(current_pt, float(space_after_pt), PT_TOLERANCE):
                paragraph_format.space_after = Pt(float(space_after_pt))
                changes += 1

        changes += self.fix_run_format(paragraph, expected)
        return changes

    def fix_run_format(self, paragraph: Any, expected: dict[str, Any]) -> int:
        font_name = expected.get("font_name")
        font_size = expected.get("font_size")
        changes = 0

        for run in paragraph.runs:
            if not run.text.strip():
                continue

            if font_name:
                current_font_name = self._effective_run_font_name(run, paragraph)
                current_font_size = self._effective_run_font_size_pt(run, paragraph)
                needs_font_name = (
                    current_font_name is None
                    or current_font_name.casefold() != str(font_name).casefold()
                )
                needs_font_size = (
                    font_size is not None
                    and (
                        current_font_size is None
                        or not close(current_font_size, float(font_size), PT_TOLERANCE)
                    )
                )
                if needs_font_name or needs_font_size:
                    self._set_run_font(run, str(font_name), int(font_size) if font_size is not None else None)
                    changes += 1
            elif font_size is not None:
                current_font_size = self._effective_run_font_size_pt(run, paragraph)
                if current_font_size is None or not close(current_font_size, float(font_size), PT_TOLERANCE):
                    run.font.size = Pt(int(font_size))
                    changes += 1

            if "bold" in expected:
                expected_bold = bool(expected["bold"])
                if self._effective_run_bold(run, paragraph) != expected_bold:
                    run.font.bold = expected_bold
                    changes += 1

            if expected.get("uppercase") is True and hasattr(run.font, "all_caps"):
                if getattr(run.font, "all_caps", None) is not True:
                    run.font.all_caps = True
                    changes += 1

        return changes

    def _set_run_font(self, run: Any, font_name: str, font_size: int | None) -> None:
        run.font.name = font_name
        if font_size is not None:
            run.font.size = Pt(int(font_size))

        r_pr = run._element.get_or_add_rPr()
        r_fonts = r_pr.rFonts
        if r_fonts is None:
            r_fonts = OxmlElement("w:rFonts")
            r_pr.append(r_fonts)

        for attribute_name in ("w:ascii", "w:hAnsi", "w:eastAsia"):
            r_fonts.set(qn(attribute_name), font_name)

    def _effective_alignment(self, paragraph: Any) -> Any:
        direct_alignment = paragraph.paragraph_format.alignment
        if direct_alignment is not None:
            return direct_alignment

        for style in self._paragraph_style_chain(paragraph):
            style_format = getattr(style, "paragraph_format", None)
            if style_format is not None and style_format.alignment is not None:
                return style_format.alignment

        return self._document_default_paragraph_attr(paragraph, "alignment")

    def _effective_paragraph_attr(self, paragraph: Any, attr_name: str) -> Any:
        direct_value = getattr(paragraph.paragraph_format, attr_name)
        if direct_value is not None:
            return direct_value

        for style in self._paragraph_style_chain(paragraph):
            style_format = getattr(style, "paragraph_format", None)
            if style_format is None:
                continue
            style_value = getattr(style_format, attr_name)
            if style_value is not None:
                return style_value

        return self._document_default_paragraph_attr(paragraph, attr_name)

    def _effective_run_font_name(self, run: Any, paragraph: Any) -> str | None:
        if run.font.name:
            return run.font.name
        for style in self._style_chain(getattr(run, "style", None)):
            if style.font.name:
                return style.font.name
        for style in self._style_chain(getattr(paragraph, "style", None)):
            if style.font.name:
                return style.font.name
        normal_style = self._normal_style(paragraph)
        if normal_style is not None and normal_style.font.name:
            return normal_style.font.name
        return None

    def _effective_run_font_size_pt(self, run: Any, paragraph: Any) -> float | None:
        if run.font.size is not None:
            return length_to_pt(run.font.size)
        for style in self._style_chain(getattr(run, "style", None)):
            if style.font.size is not None:
                return length_to_pt(style.font.size)
        for style in self._style_chain(getattr(paragraph, "style", None)):
            if style.font.size is not None:
                return length_to_pt(style.font.size)
        normal_style = self._normal_style(paragraph)
        if normal_style is not None and normal_style.font.size is not None:
            return length_to_pt(normal_style.font.size)
        return None

    def _effective_run_bold(self, run: Any, paragraph: Any) -> bool:
        if run.font.bold is not None:
            return bool(run.font.bold)
        for style in self._style_chain(getattr(run, "style", None)):
            if style.font.bold is not None:
                return bool(style.font.bold)
        for style in self._style_chain(getattr(paragraph, "style", None)):
            if style.font.bold is not None:
                return bool(style.font.bold)
        return False

    def _run_font_name_mismatch(
        self,
        runs: list[Any],
        paragraph: Any,
        expected_font_name: str,
    ) -> str | None:
        wrong_values: dict[str, int] = {}
        wrong_chars = 0
        known_chars = 0

        for run in runs:
            text_length = self._visible_text_length(run.text)
            if text_length == 0:
                continue
            current_font_name = self._effective_run_font_name(run, paragraph)
            if current_font_name is None:
                continue

            known_chars += text_length
            if current_font_name.casefold() != expected_font_name.casefold():
                wrong_chars += text_length
                wrong_values[current_font_name] = wrong_values.get(current_font_name, 0) + text_length

        if not self._should_report_run_mismatch(wrong_chars, known_chars):
            return None

        return self._weighted_value_summary(wrong_values)

    def _run_font_size_mismatch(
        self,
        runs: list[Any],
        paragraph: Any,
        expected_font_size: float,
    ) -> str | None:
        wrong_values: dict[str, int] = {}
        wrong_chars = 0
        known_chars = 0

        for run in runs:
            text_length = self._visible_text_length(run.text)
            if text_length == 0:
                continue
            current_font_size = self._effective_run_font_size_pt(run, paragraph)
            if current_font_size is None:
                continue

            known_chars += text_length
            if not close(current_font_size, expected_font_size, PT_TOLERANCE):
                wrong_chars += text_length
                current_value = format_pt(current_font_size)
                wrong_values[current_value] = wrong_values.get(current_value, 0) + text_length

        if not self._should_report_run_mismatch(wrong_chars, known_chars):
            return None

        return self._weighted_value_summary(wrong_values)

    def _should_report_run_mismatch(self, wrong_chars: int, known_chars: int) -> bool:
        if wrong_chars == 0 or known_chars == 0:
            return False
        wrong_ratio = wrong_chars / known_chars
        return (
            wrong_ratio >= RUN_FORMAT_MISMATCH_RATIO_THRESHOLD
            or wrong_chars >= RUN_FORMAT_MIN_MISMATCH_CHARS
        )

    def _weighted_value_summary(self, values: dict[str, int]) -> str | None:
        if not values:
            return None
        ordered_values = sorted(values.items(), key=lambda item: (-item[1], item[0]))
        return ", ".join(value for value, _ in ordered_values[:3])

    def _style_chain(self, style: Any) -> list[Any]:
        chain: list[Any] = []
        seen: set[int] = set()
        current = style

        while current is not None and id(current) not in seen:
            seen.add(id(current))
            chain.append(current)
            current = getattr(current, "base_style", None)

        return chain

    def _normal_style(self, paragraph: Any) -> Any | None:
        try:
            return paragraph.part.document.styles["Normal"]
        except (AttributeError, KeyError):
            return None

    def _paragraph_style_chain(self, paragraph: Any) -> list[Any]:
        chain = self._style_chain(getattr(paragraph, "style", None))
        normal_style = self._normal_style(paragraph)
        if normal_style is not None and all(id(style) != id(normal_style) for style in chain):
            chain.append(normal_style)
        return chain

    def _document_default_paragraph_attr(self, paragraph: Any, attr_name: str) -> Any:
        p_pr = self._document_default_p_pr(paragraph)
        if p_pr is None:
            return None

        if attr_name == "alignment":
            jc = p_pr.find(qn("w:jc"))
            if jc is None:
                return None
            value = jc.get(qn("w:val"))
            return ALIGNMENT_BY_XML_VALUE.get(value or "")

        spacing = p_pr.find(qn("w:spacing"))
        if attr_name in {"space_before", "space_after", "line_spacing"} and spacing is None:
            return None

        if attr_name == "space_before":
            return self._twentieths_of_point_to_length(spacing.get(qn("w:before")) if spacing is not None else None)
        if attr_name == "space_after":
            return self._twentieths_of_point_to_length(spacing.get(qn("w:after")) if spacing is not None else None)
        if attr_name == "line_spacing":
            return self._line_spacing_from_spacing_element(spacing)

        if attr_name == "first_line_indent":
            ind = p_pr.find(qn("w:ind"))
            if ind is None:
                return None
            return self._twips_to_length(ind.get(qn("w:firstLine")))

        return None

    def _document_default_p_pr(self, paragraph: Any) -> Any:
        try:
            styles_element = paragraph.part.document.styles.element
        except AttributeError:
            return None

        doc_defaults = styles_element.find(qn("w:docDefaults"))
        if doc_defaults is None:
            return None

        p_pr_default = doc_defaults.find(qn("w:pPrDefault"))
        if p_pr_default is None:
            return None

        return p_pr_default.find(qn("w:pPr"))

    def _twentieths_of_point_to_length(self, value: str | None) -> Any:
        if value is None:
            return None
        try:
            return Pt(int(value) / 20)
        except (TypeError, ValueError):
            return None

    def _twips_to_length(self, value: str | None) -> Any:
        if value is None:
            return None
        try:
            return Twips(int(value))
        except (TypeError, ValueError):
            return None

    def _line_spacing_from_spacing_element(self, spacing: Any) -> Any:
        if spacing is None:
            return None
        value = spacing.get(qn("w:line"))
        if value is None:
            return None
        line_rule = spacing.get(qn("w:lineRule"))
        try:
            numeric_value = int(value)
        except (TypeError, ValueError):
            return None
        if line_rule in {None, "auto"}:
            return numeric_value / 240
        return Pt(numeric_value / 20)

    def _visible_text_length(self, value: str) -> int:
        return len((value or "").strip())

    def _line_spacing_matches(self, current: Any, expected: float) -> bool:
        if current is None:
            return False
        if isinstance(current, (float, int)):
            return abs(float(current) - expected) <= LINE_SPACING_TOLERANCE
        return False

    def _alignment_label(self, value: Any) -> str:
        if value is None:
            return "không xác định"
        return self._expected_alignment_label(ALIGNMENT_LABELS.get(value, str(value)))

    def _expected_alignment_label(self, value: str) -> str:
        labels = {
            "JUSTIFY": "căn đều hai bên",
            "LEFT": "căn trái",
            "CENTER": "căn giữa",
            "RIGHT": "căn phải",
        }
        return labels.get(str(value).upper(), str(value))

    def _finding_metadata(
        self,
        metadata: dict[str, Any],
        field: str,
        fix_action: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **metadata,
            "field": field,
            "fix_action": fix_action,
        }
