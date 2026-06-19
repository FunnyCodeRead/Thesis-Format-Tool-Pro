from __future__ import annotations

from typing import Any

from docx.enum.section import WD_ORIENT
from docx.shared import Cm

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule, FixRule
from app.services.docx_formatter.utils.docx_units import close, format_cm, length_to_cm

CM_TOLERANCE = 0.08
A4_WIDTH_CM = 21.0
A4_HEIGHT_CM = 29.7


class PageSetupRule(AnalyzeRule, FixRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        page_setup = config.get("page_setup", {})
        findings: list[Finding] = []

        findings.extend(self._check_margins(doc, page_setup))
        findings.extend(self._check_paper_size(doc, page_setup))
        findings.extend(self._check_orientation_review(doc, page_setup))

        return findings

    def fix(self, doc: Any, config: dict[str, Any]) -> int:
        page_setup = config.get("page_setup", {})
        changes = 0

        for section in doc.sections:
            if str(page_setup.get("paper_size", "")).upper() == "A4":
                width_cm = length_to_cm(section.page_width)
                height_cm = length_to_cm(section.page_height)
                if not self._is_a4(width_cm, height_cm):
                    section.orientation = WD_ORIENT.PORTRAIT
                    section.page_width = Cm(21)
                    section.page_height = Cm(29.7)
                    changes += 1

            for attr_name, config_key in [
                ("top_margin", "margin_top_cm"),
                ("bottom_margin", "margin_bottom_cm"),
                ("left_margin", "margin_left_cm"),
                ("right_margin", "margin_right_cm"),
            ]:
                expected_cm = page_setup.get(config_key)
                if expected_cm is None:
                    continue

                current_cm = length_to_cm(getattr(section, attr_name, None))
                if close(current_cm, float(expected_cm), CM_TOLERANCE):
                    continue

                setattr(section, attr_name, Cm(float(expected_cm)))
                changes += 1

        return changes

    def _check_margins(self, doc: Any, page_setup: dict[str, Any]) -> list[Finding]:
        findings: list[Finding] = []

        expected_margins = {
            "top_margin": ("margin_top_cm", "lề trên"),
            "bottom_margin": ("margin_bottom_cm", "lề dưới"),
            "left_margin": ("margin_left_cm", "lề trái"),
            "right_margin": ("margin_right_cm", "lề phải"),
        }

        for section_index, section in enumerate(doc.sections, start=1):
            for attr_name, (config_key, label) in expected_margins.items():
                expected_cm = page_setup.get(config_key)
                if expected_cm is None:
                    continue

                current_cm = length_to_cm(getattr(section, attr_name, None))
                if close(current_cm, float(expected_cm), CM_TOLERANCE):
                    continue

                findings.append(
                    Finding(
                        type="PAGE_MARGIN_ERROR",
                        severity="error",
                        location=f"Section {section_index}",
                        message=f"{label.capitalize()} chưa đúng yêu cầu.",
                        current_value=format_cm(current_cm),
                        expected_value=format_cm(float(expected_cm)),
                        suggestion=f"Đặt {label} thành {format_cm(float(expected_cm))}.",
                        metadata={
                            "target": "section",
                            "context": "page_setup",
                            "report_group_id": "page_setup",
                            "report_severity": "major",
                            "auto_fixable": True,
                            "field": config_key,
                            "section_index": section_index,
                            "fix_action": {
                                "type": "set_section_margin",
                                "field": config_key,
                                "value": float(expected_cm),
                            },
                        },
                    )
                )

        return findings

    def _check_paper_size(self, doc: Any, page_setup: dict[str, Any]) -> list[Finding]:
        findings: list[Finding] = []

        if str(page_setup.get("paper_size", "")).upper() != "A4":
            return findings

        for section_index, section in enumerate(doc.sections, start=1):
            width_cm = length_to_cm(section.page_width)
            height_cm = length_to_cm(section.page_height)

            if self._is_a4(width_cm, height_cm):
                continue

            findings.append(
                Finding(
                    type="PAPER_SIZE_ERROR",
                    severity="error",
                    location=f"Section {section_index}",
                    message="Khổ giấy chưa đúng A4.",
                    current_value=f"{format_cm(width_cm)} x {format_cm(height_cm)}",
                    expected_value="A4 (21.00 cm x 29.70 cm)",
                    suggestion="Đặt khổ giấy thành A4.",
                    metadata={
                        "target": "section",
                        "context": "page_setup",
                        "report_group_id": "page_setup",
                        "report_severity": "major",
                        "auto_fixable": True,
                        "field": "paper_size",
                        "section_index": section_index,
                        "fix_action": {
                            "type": "set_paper_size",
                            "value": "A4",
                        },
                    },
                )
            )

        return findings

    def _check_orientation_review(self, doc: Any, page_setup: dict[str, Any]) -> list[Finding]:
        findings: list[Finding] = []
        if page_setup.get("allow_landscape_sections", False) is True:
            return findings

        for section_index, section in enumerate(doc.sections, start=1):
            width_cm = length_to_cm(section.page_width)
            height_cm = length_to_cm(section.page_height)
            if width_cm is None or height_cm is None or width_cm <= height_cm:
                continue

            findings.append(
                Finding(
                    type="SECTION_LANDSCAPE_REVIEW",
                    severity="warning",
                    location=f"Section {section_index}",
                    message="Section đang để hướng ngang, cần kiểm tra.",
                    current_value=f"{format_cm(width_cm)} x {format_cm(height_cm)}",
                    expected_value="Hướng dọc cho nội dung chính, trừ khi phụ lục hoặc bảng biểu được phép dùng hướng ngang.",
                    suggestion="Kiểm tra section này có phải phụ lục hoặc bảng ngang hợp lệ không; nếu không thì chuyển về Portrait trong Word.",
                    metadata={
                        "target": "section",
                        "context": "page_setup",
                        "report_group_id": "page_setup",
                        "report_severity": "major",
                        "auto_fixable": False,
                        "manual_review": True,
                        "field": "page_orientation",
                        "section_index": section_index,
                        "fix_action": {
                            "type": "manual_review",
                            "reason": "Hướng trang ngang có thể hợp lệ với phụ lục hoặc bảng lớn, cần người dùng xác nhận.",
                        },
                    },
                )
            )

        return findings

    def _is_a4(self, width_cm: float | None, height_cm: float | None) -> bool:
        if width_cm is None or height_cm is None:
            return False

        portrait = close(width_cm, A4_WIDTH_CM, 0.2) and close(height_cm, A4_HEIGHT_CM, 0.2)
        landscape = close(width_cm, A4_HEIGHT_CM, 0.2) and close(height_cm, A4_WIDTH_CM, 0.2)

        return portrait or landscape
