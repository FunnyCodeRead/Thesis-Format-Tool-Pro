from __future__ import annotations

from app.services.docx_formatter.rules.advanced_format_rule import AdvancedFormatRule
from app.services.docx_formatter.rules.caption_format_rule import CaptionFormatRule
from app.services.docx_formatter.rules.caption_numbering_rule import CaptionNumberingRule
from app.services.docx_formatter.rules.chapter_layout_rule import ChapterLayoutRule
from app.services.docx_formatter.rules.character_density_rule import CharacterDensityRule
from app.services.docx_formatter.rules.document_length_rule import DocumentLengthRule
from app.services.docx_formatter.rules.front_matter_heading_rule import FrontMatterHeadingRule
from app.services.docx_formatter.rules.header_footer_format_rule import HeaderFooterFormatRule
from app.services.docx_formatter.rules.heading_format_rule import HeadingFormatRule
from app.services.docx_formatter.rules.heading_structure_rule import HeadingStructureRule
from app.services.docx_formatter.rules.list_item_format_rule import ListItemFormatRule
from app.services.docx_formatter.rules.layout_abnormal_rule import LayoutAbnormalRule
from app.services.docx_formatter.rules.manual_review_rule import ManualReviewRule
from app.services.docx_formatter.rules.page_setup_rule import PageSetupRule
from app.services.docx_formatter.rules.page_numbering_rule import PageNumberingRule
from app.services.docx_formatter.rules.paragraph_format_rule import ParagraphFormatRule
from app.services.docx_formatter.rules.region_review_rule import RegionReviewRule
from app.services.docx_formatter.rules.scope_review_rule import ScopeReviewRule
from app.services.docx_formatter.rules.table_cell_format_rule import TableCellFormatRule
from app.services.docx_formatter.rules.toc_structure_rule import TocStructureRule


class RuleFactory:
    @staticmethod
    def create_analyze_rules():
        return [
            PageSetupRule(),
            DocumentLengthRule(),
            ManualReviewRule(),
            LayoutAbnormalRule(),
            PageNumberingRule(),
            TocStructureRule(),
            RegionReviewRule(),
            AdvancedFormatRule(),
            TableCellFormatRule(),
            HeaderFooterFormatRule(),
            CaptionNumberingRule(),
            CharacterDensityRule(),
            ScopeReviewRule(),
            ChapterLayoutRule(),
            HeadingStructureRule(),
            FrontMatterHeadingRule(),
            ListItemFormatRule(),
            ParagraphFormatRule(),
            HeadingFormatRule(),
        ]

    @staticmethod
    def create_fix_rules():
        return [
            PageSetupRule(),
            FrontMatterHeadingRule(),
            ListItemFormatRule(),
            CaptionFormatRule(),
            TableCellFormatRule(),
            HeaderFooterFormatRule(),
            ParagraphFormatRule(),
            HeadingFormatRule(),
        ]
