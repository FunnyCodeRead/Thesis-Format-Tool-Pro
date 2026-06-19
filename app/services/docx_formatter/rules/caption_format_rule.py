from __future__ import annotations

from typing import Any

from app.services.docx_formatter.domain.rule import FixRule
from app.services.docx_formatter.engine.context_classifier import classify_paragraph_context
from app.services.docx_formatter.rules.common_format import CommonFormatMixin


class CaptionFormatRule(CommonFormatMixin, FixRule):
    def fix(self, doc: Any, config: dict[str, Any]) -> int:
        expected = _caption_expected_config(config)
        changes = 0

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            if classify_paragraph_context(paragraph, paragraph_index).context != "caption":
                continue

            changes += self.fix_common_format(paragraph, expected)

        return changes


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
