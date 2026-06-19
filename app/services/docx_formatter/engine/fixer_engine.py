from __future__ import annotations

from typing import Any

from app.services.docx_formatter.domain.rule import FixRule


class FixerEngine:
    def __init__(self, rules: list[FixRule]) -> None:
        self.rules = rules

    def fix(self, doc: Any, config: dict[str, Any]) -> dict[str, int]:
        changes_by_rule: dict[str, int] = {}
        total_changes = 0

        for rule in self.rules:
            rule_name = rule.__class__.__name__
            changes = rule.fix(doc, config)
            changes_by_rule[rule_name] = changes
            total_changes += changes

        return {
            "page_setup_changes": changes_by_rule.get("PageSetupRule", 0),
            "front_matter_heading_changes": changes_by_rule.get("FrontMatterHeadingRule", 0),
            "list_item_changes": changes_by_rule.get("ListItemFormatRule", 0),
            "caption_changes": changes_by_rule.get("CaptionFormatRule", 0),
            "table_cell_changes": changes_by_rule.get("TableCellFormatRule", 0),
            "header_footer_changes": changes_by_rule.get("HeaderFooterFormatRule", 0),
            "paragraph_changes": changes_by_rule.get("ParagraphFormatRule", 0),
            "heading_changes": changes_by_rule.get("HeadingFormatRule", 0),
            "total_changes": total_changes,
            "changes_by_rule": changes_by_rule,
        }
