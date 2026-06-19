from __future__ import annotations

from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule, FixRule
from app.services.docx_formatter.engine.context_classifier import text_preview
from app.services.docx_formatter.rules.common_format import CommonFormatMixin


class TableCellFormatRule(CommonFormatMixin, AnalyzeRule, FixRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        expected = _table_cell_expected_config(config)
        findings: list[Finding] = []

        for table_index, table in enumerate(doc.tables, start=1):
            for row_index, row in enumerate(table.rows, start=1):
                for cell_index, cell in enumerate(row.cells, start=1):
                    for cell_paragraph_index, paragraph in enumerate(cell.paragraphs, start=1):
                        preview = text_preview(paragraph.text)
                        if not preview:
                            continue

                        findings.extend(
                            self.analyze_run_format(
                                paragraph=paragraph,
                                expected=expected,
                                location=(
                                    f"Table {table_index}, Row {row_index}, Cell {cell_index}, "
                                    f"Paragraph {cell_paragraph_index}"
                                ),
                                type_prefix="TABLE_CELL",
                                metadata={
                                    "target": "table_cell",
                                    "context": "table_cell",
                                    "report_group_id": "table_cell_format",
                                    "report_severity": "minor",
                                    "auto_fixable": True,
                                    "manual_review": False,
                                    "table_index": table_index,
                                    "row_index": row_index,
                                    "cell_index": cell_index,
                                    "table_paragraph_index": cell_paragraph_index,
                                    "text_preview": preview,
                                    "style_name": getattr(getattr(paragraph, "style", None), "name", ""),
                                },
                            )
                        )

        return findings

    def fix(self, doc: Any, config: dict[str, Any]) -> int:
        expected = _table_cell_expected_config(config)
        changes = 0

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        if not (paragraph.text or "").strip():
                            continue
                        changes += self.fix_run_format(paragraph, expected)

        return changes


def _table_cell_expected_config(config: dict[str, Any]) -> dict[str, Any]:
    paragraph_config = config.get("paragraph", {})
    table_config = config.get("table_cell_format", config.get("table_cell", {}))
    return {
        "font_name": table_config.get("font_name", paragraph_config.get("font_name", "Times New Roman")),
        "font_size": table_config.get("font_size", paragraph_config.get("font_size", 13)),
    }
