from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.services.docx_formatter.domain.report import (
    ProductionReport,
    ReportIssueGroup,
    ReportSeverity,
    ReportSummary,
)
from app.services.docx_formatter.engine.fixability_matrix import classify_fixability
from app.services.docx_formatter.engine.manual_repair_guidance import (
    build_group_repair_guidance,
    build_issue_repair_guidance,
    build_summary_repair_guidance,
)
from app.services.docx_formatter.engine.vietnamese_text import (
    normalize_fix_action,
    normalize_vietnamese_display,
)

GROUP_ORDER = [
    "page_setup",
    "document_length",
    "cover_layout",
    "header_footer_page_number",
    "chapter_layout",
    "toc",
    "list_of_figures",
    "list_of_tables",
    "front_matter",
    "heading",
    "list_item",
    "body_paragraph",
    "caption",
    "table_cell_format",
    "header_footer_format",
    "table",
    "image_layout",
    "character_density",
    "text_decoration",
    "equation_layout",
    "scope_review",
    "references",
    "layout_abnormal",
    "render_verification",
]

GROUPS = {
    "page_setup": {
        "name": "Thiết lập trang và căn lề",
        "description": "Kiểm tra khổ giấy, căn lề, section và hướng trang.",
    },
    "document_length": {
        "name": "Số trang tài liệu",
        "description": "Kiểm tra tổng số trang theo giới hạn quy định.",
    },
    "cover_layout": {
        "name": "Trang bìa",
        "description": "Kiểm tra bố cục bìa theo style mẫu, không kiểm tra nội dung đề tài.",
    },
    "header_footer_page_number": {
        "name": "Header/Footer và số trang",
        "description": "Kiểm tra vị trí header, footer và đánh số trang.",
    },
    "chapter_layout": {
        "name": "Trình bày chương",
        "description": "Kiểm tra dòng số chương, tiêu đề chương, căn giữa và chữ in hoa.",
    },
    "toc": {
        "name": "Mục lục",
        "description": "Kiểm tra style mục lục, dot leader và số trang.",
    },
    "list_of_figures": {
        "name": "Danh mục hình ảnh",
        "description": "Kiểm tra style danh mục hình ảnh.",
    },
    "list_of_tables": {
        "name": "Danh mục bảng",
        "description": "Kiểm tra style danh mục bảng.",
    },
    "front_matter": {
        "name": "Phần đầu tài liệu",
        "description": "Kiểm tra tiêu đề phần đầu như lời cảm ơn, lời cam đoan, tóm tắt mà không trộn với heading chương.",
    },
    "heading": {
        "name": "Heading chương/mục",
        "description": "Kiểm tra font, cỡ chữ, in đậm, căn lề và khoảng cách heading.",
    },
    "list_item": {
        "name": "Danh sách/bullet",
        "description": "Kiểm tra font, cỡ chữ và giãn dòng của bullet/numbered list; không ép thụt đầu dòng như đoạn văn thường.",
    },
    "body_paragraph": {
        "name": "Đoạn văn nội dung",
        "description": "Kiểm tra font, cỡ chữ, căn đều, giãn dòng và thụt đầu dòng.",
    },
    "caption": {
        "name": "Caption hình/bảng",
        "description": "Kiểm tra định dạng caption hình và bảng.",
    },
    "table_cell_format": {
        "name": "Định dạng chữ trong bảng",
        "description": "Kiểm tra font chữ và cỡ chữ trong ô bảng mà không thay đổi cấu trúc bảng.",
    },
    "header_footer_format": {
        "name": "Định dạng chữ header/footer",
        "description": "Kiểm tra font chữ và cỡ chữ trong đầu trang/chân trang mà không sửa số trang.",
    },
    "table": {
        "name": "Bảng biểu",
        "description": "Kiểm tra bố cục và style bảng.",
    },
    "image_layout": {
        "name": "Hình ảnh/sơ đồ",
        "description": "Kiểm tra bố cục hình ảnh và sơ đồ.",
    },
    "character_density": {
        "name": "Mật độ chữ",
        "description": "Kiểm tra chữ bị nén, kéo giãn hoặc thay đổi khoảng cách ký tự.",
    },
    "text_decoration": {
        "name": "Màu chữ/highlight/gạch chân",
        "description": "Kiểm tra màu chữ, highlight và underline bất thường; các lỗi này chỉ báo để kiểm tra thủ công.",
    },
    "equation_layout": {
        "name": "Công thức/ký hiệu",
        "description": "Kiểm tra bố cục công thức, ký hiệu, căn giữa và nguy cơ bị cắt trang.",
    },
    "scope_review": {
        "name": "Phạm vi nội dung",
        "description": "Phát hiện cụm từ được cấu hình là ngoài phạm vi đề tài.",
    },
    "references": {
        "name": "Tài liệu tham khảo",
        "description": "Kiểm tra style phần tài liệu tham khảo.",
    },
    "layout_abnormal": {
        "name": "Lỗi layout bất thường",
        "description": "Phát hiện các dấu hiệu layout bị vỡ hoặc số trang dính vào nội dung.",
    },
    "render_verification": {
        "name": "Kiểm tra bản render PDF",
        "description": "Kiểm tra trang trắng, tràn lề, mất mép và caption nhảy trang sau khi render Word sang PDF.",
    },
}

FIELD_LABELS = {
    "alignment": "Căn lề",
    "bold": "In đậm",
    "first_line_indent_cm": "Thụt đầu dòng",
    "font_name": "Font chữ",
    "font_size": "Cỡ chữ",
    "caption_numbering": "Đánh số hình/bảng",
    "character_density": "Mật độ chữ",
    "chapter_layout": "Bố cục chương",
    "header_footer_layout": "Bố cục header/footer",
    "image_layout": "Bố cục ảnh/sơ đồ",
    "line_spacing": "Giãn dòng",
    "list_entry_layout": "Bố cục dòng danh mục",
    "margin_top_cm": "Lề trên",
    "margin_bottom_cm": "Lề dưới",
    "margin_left_cm": "Lề trái",
    "margin_right_cm": "Lề phải",
    "paper_size": "Khổ giấy",
    "page_count": "Số trang",
    "page_number_position": "Vị trí số trang",
    "scope_term": "Từ khóa ngoài phạm vi",
    "space_before_pt": "Khoảng cách trước đoạn",
    "space_after_pt": "Khoảng cách sau đoạn",
    "uppercase": "Viết hoa",
}

FIELD_LABELS.update(
    {
        "blank_paragraphs": "Dong trong lien tiep",
        "comment_artifact": "Nhan xet/lich su sua",
        "hyperlink": "Lien ket",
        "image_width": "Kich thuoc anh/so do",
        "image_wrap": "Kieu boc chu quanh anh/so do",
        "list_marker": "Bullet/number thu cong",
        "manual_page_break": "Ngat trang thu cong",
        "manual_spacing": "Can le thu cong",
        "page_orientation": "Huong trang",
        "section_break": "Ngat section",
        "table_width": "Do rong bang",
        "toc_structure": "Cau truc muc luc",
        "track_changes": "Lich su sua",
        "text_decoration": "Màu chữ/highlight/gạch chân",
        "equation_layout": "Bố cục công thức/ký hiệu",
        "blank_page": "Trang trắng",
        "render_edge_overflow": "Nội dung sát/vượt mép trang",
        "caption_page_break": "Caption nhảy trang",
    }
)

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

RULE_NAMES = {
    "PAGE_MARGIN_ERROR": ("PAGE_SETUP_MARGIN", "Căn lề trang"),
    "PAPER_SIZE_ERROR": ("PAGE_SETUP_PAPER_SIZE", "Khổ giấy A4"),
    "DOCUMENT_PAGE_COUNT_REVIEW": ("DOCUMENT_PAGE_COUNT", "Số trang tài liệu"),
    "PAGE_NUMBER_IN_BODY_ERROR": ("PAGE_NUMBER_NOT_IN_BODY", "Số trang không được nằm trong nội dung"),
    "PAGE_NUMBER_FOOTER_REVIEW": ("PAGE_NUMBER_FOOTER", "Đánh số trang trong footer"),
    "HEADER_FOOTER_LAYOUT_REVIEW": ("HEADER_FOOTER_LAYOUT", "Bố cục header/footer"),
    "COVER_PAGE_NUMBER_VISIBLE_REVIEW": ("COVER_PAGE_NUMBER_VISIBLE", "Trang bìa có thể đang hiển thị số trang"),
    "PAGE_NUMBER_ALIGNMENT_REVIEW": ("PAGE_NUMBER_ALIGNMENT", "Số trang ở footer chưa căn giữa"),
    "ROMAN_PAGE_NUMBER_REPEATED_REVIEW": ("ROMAN_PAGE_NUMBER_REPEATED", "Số trang La Mã có dấu hiệu bị lặp"),
    "MAIN_PAGE_NUMBER_FORMAT_REVIEW": ("MAIN_PAGE_NUMBER_FORMAT", "Số trang phần nội dung chính chưa dùng số Ả Rập"),
    "MAIN_PAGE_NUMBER_RESET_REVIEW": ("MAIN_PAGE_NUMBER_RESET", "Số trang phần nội dung chính chưa reset về 1"),
    "COVER_ALIGNMENT_REVIEW": ("COVER_LAYOUT_ALIGNMENT", "Bố cục căn giữa trang bìa"),
    "CHAPTER_NUMBER_NOT_SEPARATED_REVIEW": ("CHAPTER_NUMBER_NOT_SEPARATED", "Dòng số chương chưa tách riêng"),
    "CHAPTER_NUMBER_LABEL_REVIEW": ("CHAPTER_NUMBER_LABEL", "Dòng số chương chưa đúng mẫu"),
    "CHAPTER_NUMBER_ALIGNMENT_REVIEW": ("CHAPTER_NUMBER_ALIGNMENT", "Dòng số chương chưa căn giữa"),
    "CHAPTER_NUMBER_BOLD_REVIEW": ("CHAPTER_NUMBER_BOLD", "Dòng số chương chưa in đậm"),
    "CHAPTER_TITLE_MISSING_REVIEW": ("CHAPTER_TITLE_MISSING", "Thiếu tiêu đề chương dưới dòng số chương"),
    "CHAPTER_TITLE_UPPERCASE_REVIEW": ("CHAPTER_TITLE_UPPERCASE", "Tiêu đề chương chưa viết hoa"),
    "CHAPTER_TITLE_ALIGNMENT_REVIEW": ("CHAPTER_TITLE_ALIGNMENT", "Tiêu đề chương chưa căn giữa"),
    "CHAPTER_TITLE_BOLD_REVIEW": ("CHAPTER_TITLE_BOLD", "Tiêu đề chương chưa in đậm"),
    "TOC_TITLE_ALIGNMENT_REVIEW": ("TOC_TITLE_ALIGNMENT", "Căn giữa tiêu đề mục lục"),
    "TOC_DOT_LEADER_REVIEW": ("TOC_DOT_LEADER", "Dot leader và số trang mục lục"),
    "LIST_OF_FIGURES_TITLE_ALIGNMENT_REVIEW": ("LIST_OF_FIGURES_TITLE_ALIGNMENT", "Căn giữa tiêu đề danh mục hình ảnh"),
    "LIST_OF_FIGURES_DOT_LEADER_REVIEW": ("LIST_OF_FIGURES_DOT_LEADER", "Dot leader danh mục hình ảnh"),
    "LIST_OF_TABLES_TITLE_ALIGNMENT_REVIEW": ("LIST_OF_TABLES_TITLE_ALIGNMENT", "Căn giữa tiêu đề danh mục bảng"),
    "LIST_OF_TABLES_DOT_LEADER_REVIEW": ("LIST_OF_TABLES_DOT_LEADER", "Dot leader danh mục bảng"),
    "FIGURE_NUMBERING_MALFORMED_REVIEW": ("FIGURE_NUMBERING_MALFORMED", "Số hình bị rối"),
    "FIGURE_NUMBERING_MISSING_REVIEW": ("FIGURE_NUMBERING_MISSING", "Thiếu số hình"),
    "FIGURE_NUMBERING_MISSING_SEPARATOR_REVIEW": ("FIGURE_NUMBERING_MISSING_SEPARATOR", "Caption hình thiếu dấu phân cách"),
    "FIGURE_NUMBERING_DUPLICATE_REVIEW": ("FIGURE_NUMBERING_DUPLICATE", "Số hình bị lặp"),
    "FIGURE_LIST_DUPLICATE_REVIEW": ("FIGURE_LIST_DUPLICATE", "Số hình bị lặp trong danh mục"),
    "FIGURE_LIST_ENTRY_MISSING_TARGET_REVIEW": ("FIGURE_LIST_ENTRY_MISSING_TARGET", "Dòng danh mục hình chưa có caption tương ứng"),
    "FIGURE_LIST_TITLE_MISMATCH_REVIEW": ("FIGURE_LIST_TITLE_MISMATCH", "Tiêu đề hình trong danh mục không khớp"),
    "TABLE_NUMBERING_MALFORMED_REVIEW": ("TABLE_NUMBERING_MALFORMED", "Số bảng bị rối"),
    "TABLE_NUMBERING_MISSING_REVIEW": ("TABLE_NUMBERING_MISSING", "Thiếu số bảng"),
    "TABLE_NUMBERING_MISSING_SEPARATOR_REVIEW": ("TABLE_NUMBERING_MISSING_SEPARATOR", "Caption bảng thiếu dấu phân cách"),
    "TABLE_NUMBERING_DUPLICATE_REVIEW": ("TABLE_NUMBERING_DUPLICATE", "Số bảng bị lặp"),
    "TABLE_LIST_DUPLICATE_REVIEW": ("TABLE_LIST_DUPLICATE", "Số bảng bị lặp trong danh mục"),
    "TABLE_LIST_ENTRY_MISSING_TARGET_REVIEW": ("TABLE_LIST_ENTRY_MISSING_TARGET", "Dòng danh mục bảng chưa có caption tương ứng"),
    "TABLE_LIST_TITLE_MISMATCH_REVIEW": ("TABLE_LIST_TITLE_MISMATCH", "Tiêu đề bảng trong danh mục không khớp"),
    "HEADING_CHAPTER_MISMATCH_REVIEW": ("HEADING_CHAPTER_MISMATCH", "Tiểu mục không khớp chương hiện tại"),
    "CAPTION_ALIGNMENT_ERROR": ("CAPTION_ALIGNMENT", "Căn giữa caption hình/bảng"),
    "CAPTION_FONT_NAME_ERROR": ("CAPTION_FONT_NAME", "Font chữ caption hình/bảng"),
    "CAPTION_FONT_SIZE_ERROR": ("CAPTION_FONT_SIZE", "Cỡ chữ caption hình/bảng"),
    "CAPTION_SPACE_BEFORE_PT_ERROR": ("CAPTION_SPACE_BEFORE", "Khoảng cách trước caption"),
    "CAPTION_SPACE_AFTER_PT_ERROR": ("CAPTION_SPACE_AFTER", "Khoảng cách sau caption"),
    "TABLE_CELL_FONT_NAME_ERROR": ("TABLE_CELL_FONT_NAME", "Font chữ trong bảng"),
    "TABLE_CELL_FONT_SIZE_ERROR": ("TABLE_CELL_FONT_SIZE", "Cỡ chữ trong bảng"),
    "IMAGE_LAYOUT_REVIEW": ("IMAGE_LAYOUT", "Bố cục ảnh/sơ đồ"),
    "CHARACTER_DENSITY_REVIEW": ("CHARACTER_DENSITY", "Mật độ chữ không bình thường"),
    "OUT_OF_SCOPE_TERM_REVIEW": ("OUT_OF_SCOPE_TERM", "Nội dung có thể ngoài phạm vi đề tài"),
    "PARAGRAPH_ALIGNMENT_ERROR": ("BODY_ALIGN_JUSTIFY", "Căn đều hai bên cho đoạn văn nội dung"),
    "PARAGRAPH_FIRST_LINE_INDENT_ERROR": ("BODY_FIRST_LINE_INDENT", "Thụt đầu dòng đoạn văn nội dung"),
    "PARAGRAPH_LINE_SPACING_ERROR": ("BODY_LINE_SPACING", "Giãn dòng đoạn văn nội dung"),
    "PARAGRAPH_SPACE_BEFORE_PT_ERROR": ("BODY_SPACE_BEFORE", "Khoảng cách trước đoạn văn nội dung"),
    "PARAGRAPH_SPACE_AFTER_PT_ERROR": ("BODY_SPACE_AFTER", "Khoảng cách sau đoạn văn nội dung"),
    "PARAGRAPH_FONT_NAME_ERROR": ("BODY_FONT_NAME", "Font chữ đoạn văn nội dung"),
    "PARAGRAPH_FONT_SIZE_ERROR": ("BODY_FONT_SIZE", "Cỡ chữ đoạn văn nội dung"),
    "PARAGRAPH_BOLD_ERROR": ("BODY_BOLD", "Định dạng in đậm đoạn văn nội dung"),
    "HEADING_1_ALIGNMENT_ERROR": ("HEADING_1_ALIGNMENT", "Căn lề heading cấp 1"),
    "HEADING_1_SPACE_BEFORE_PT_ERROR": ("HEADING_1_SPACE_BEFORE", "Khoảng cách trước heading cấp 1"),
    "HEADING_1_SPACE_AFTER_PT_ERROR": ("HEADING_1_SPACE_AFTER", "Khoảng cách sau heading cấp 1"),
    "HEADING_1_FONT_NAME_ERROR": ("HEADING_1_FONT_NAME", "Font chữ heading cấp 1"),
    "HEADING_1_FONT_SIZE_ERROR": ("HEADING_1_FONT_SIZE", "Cỡ chữ heading cấp 1"),
    "HEADING_1_BOLD_ERROR": ("HEADING_1_BOLD", "In đậm heading cấp 1"),
    "HEADING_1_UPPERCASE_ERROR": ("HEADING_1_UPPERCASE", "Viết hoa heading cấp 1"),
    "HEADING_2_ALIGNMENT_ERROR": ("HEADING_2_ALIGNMENT", "Căn lề heading cấp 2"),
    "HEADING_2_SPACE_BEFORE_PT_ERROR": ("HEADING_2_SPACE_BEFORE", "Khoảng cách trước heading cấp 2"),
    "HEADING_2_SPACE_AFTER_PT_ERROR": ("HEADING_2_SPACE_AFTER", "Khoảng cách sau heading cấp 2"),
    "HEADING_2_FONT_NAME_ERROR": ("HEADING_2_FONT_NAME", "Font chữ heading cấp 2"),
    "HEADING_2_FONT_SIZE_ERROR": ("HEADING_2_FONT_SIZE", "Cỡ chữ heading cấp 2"),
    "HEADING_2_BOLD_ERROR": ("HEADING_2_BOLD", "In đậm heading cấp 2"),
    "HEADING_2_UPPERCASE_ERROR": ("HEADING_2_UPPERCASE", "Viết hoa heading cấp 2"),
    "HEADING_3_ALIGNMENT_ERROR": ("HEADING_3_ALIGNMENT", "Căn lề heading cấp 3"),
    "HEADING_3_FONT_NAME_ERROR": ("HEADING_3_FONT_NAME", "Font chữ heading cấp 3"),
    "HEADING_3_FONT_SIZE_ERROR": ("HEADING_3_FONT_SIZE", "Cỡ chữ heading cấp 3"),
    "HEADING_3_BOLD_ERROR": ("HEADING_3_BOLD", "In đậm heading cấp 3"),
}

RULE_NAMES.update(
    {
        "SECTION_LANDSCAPE_REVIEW": ("SECTION_LANDSCAPE", "Section dang de huong ngang"),
        "TOC_MISSING_REVIEW": ("TOC_MISSING", "Thieu muc luc"),
        "TOC_NOT_AUTOMATIC_REVIEW": ("TOC_NOT_AUTOMATIC", "Muc luc chua phai field tu dong"),
        "EXCESSIVE_BLANK_PARAGRAPHS_REVIEW": ("EXCESSIVE_BLANK_PARAGRAPHS", "Quá nhiều dòng trống liên tiếp"),
        "MANUAL_SPACING_REVIEW": ("MANUAL_SPACING", "Can le bang dau cach/tab thu cong"),
        "MANUAL_PAGE_BREAK_REVIEW": ("MANUAL_PAGE_BREAK", "Ngat trang thu cong"),
        "SECTION_BREAK_REVIEW": ("SECTION_BREAK", "Ngat section can kiem tra"),
        "TRACK_CHANGES_REVIEW": ("TRACK_CHANGES", "Lich su sua can kiem tra"),
        "COMMENTS_REVIEW": ("COMMENTS_REVIEW", "Nhận xét còn trong file"),
        "COMMENTS_OR_TRACKED_REVIEW": ("COMMENTS_OR_TRACKED", "Nhan xet/lich su sua con trong file"),
        "HYPERLINK_REVIEW": ("HYPERLINK", "Lien ket can kiem tra style"),
        "MANUAL_LIST_MARKER_REVIEW": ("MANUAL_LIST_MARKER", "Bullet/number co the dang go tay"),
        "TABLE_WIDTH_REVIEW": ("TABLE_WIDTH", "Bang co the tran le"),
        "IMAGE_WRAP_REVIEW": ("IMAGE_WRAP", "Kieu boc chu quanh anh/so do can kiem tra"),
        "IMAGE_WIDTH_REVIEW": ("IMAGE_WIDTH", "Anh/so do co the tran le"),
        "TEXT_DECORATION_REVIEW": ("TEXT_DECORATION", "Màu chữ/highlight/gạch chân bất thường"),
        "TABLE_TEXT_DECORATION_REVIEW": ("TABLE_TEXT_DECORATION", "Màu chữ/highlight/gạch chân trong bảng"),
        "EQUATION_LAYOUT_REVIEW": ("EQUATION_LAYOUT", "Bố cục công thức/ký hiệu cần kiểm tra"),
        "RENDER_BLANK_PAGE_REVIEW": ("RENDER_BLANK_PAGE", "Trang render gần như trống"),
        "RENDER_EDGE_OVERFLOW_REVIEW": ("RENDER_EDGE_OVERFLOW", "Nội dung render sát hoặc vượt mép trang"),
        "RENDER_CAPTION_PAGE_BREAK_REVIEW": ("RENDER_CAPTION_PAGE_BREAK", "Caption có thể bị tách trang"),
        "HEADER_FOOTER_FONT_NAME_ERROR": ("HEADER_FOOTER_FONT_NAME", "Font chu header/footer"),
        "HEADER_FOOTER_FONT_SIZE_ERROR": ("HEADER_FOOTER_FONT_SIZE", "Co chu header/footer"),
    }
)

MESSAGE_BY_TYPE = {
    "PAGE_MARGIN_ERROR": "Căn lề section chưa đúng quy chuẩn.",
    "PAPER_SIZE_ERROR": "Khổ giấy section chưa đúng A4.",
    "DOCUMENT_PAGE_COUNT_REVIEW": "Số trang tài liệu nằm ngoài khoảng quy định.",
    "PAGE_NUMBER_IN_BODY_ERROR": "Số trang có dấu hiệu bị dính vào nội dung văn bản.",
    "PAGE_NUMBER_FOOTER_REVIEW": "Footer/số trang cần được kiểm tra.",
    "HEADER_FOOTER_LAYOUT_REVIEW": "Header/footer có dấu hiệu bố cục cần kiểm tra.",
    "COVER_PAGE_NUMBER_VISIBLE_REVIEW": "Trang bìa có thể đang hiển thị số trang.",
    "PAGE_NUMBER_ALIGNMENT_REVIEW": "Số trang trong footer chưa được căn giữa.",
    "ROMAN_PAGE_NUMBER_REPEATED_REVIEW": "Số trang La Mã có dấu hiệu bị restart/lặp lại.",
    "MAIN_PAGE_NUMBER_FORMAT_REVIEW": "Phần nội dung chính chưa dùng số trang Ả Rập.",
    "MAIN_PAGE_NUMBER_RESET_REVIEW": "Phần nội dung chính chưa reset số trang về 1.",
    "COVER_ALIGNMENT_REVIEW": "Một dòng trên trang bìa chưa được căn giữa.",
    "CHAPTER_NUMBER_NOT_SEPARATED_REVIEW": "Dòng số chương đang bị viết chung với tiêu đề chương.",
    "CHAPTER_NUMBER_LABEL_REVIEW": "Dòng số chương chưa đúng mẫu CHƯƠNG 1.",
    "CHAPTER_NUMBER_ALIGNMENT_REVIEW": "Dòng số chương chưa được căn giữa.",
    "CHAPTER_NUMBER_BOLD_REVIEW": "Dòng số chương chưa in đậm.",
    "CHAPTER_TITLE_MISSING_REVIEW": "Thiếu dòng tiêu đề chương ngay dưới số chương.",
    "CHAPTER_TITLE_UPPERCASE_REVIEW": "Tiêu đề chương chưa viết hoa toàn bộ.",
    "CHAPTER_TITLE_ALIGNMENT_REVIEW": "Tiêu đề chương chưa được căn giữa.",
    "CHAPTER_TITLE_BOLD_REVIEW": "Tiêu đề chương chưa in đậm.",
    "TOC_TITLE_ALIGNMENT_REVIEW": "Tiêu đề mục lục chưa được căn giữa.",
    "TOC_DOT_LEADER_REVIEW": "Một dòng mục lục có thể thiếu dot leader hoặc số trang căn phải.",
    "LIST_OF_FIGURES_TITLE_ALIGNMENT_REVIEW": "Tiêu đề danh mục hình ảnh chưa được căn giữa.",
    "LIST_OF_FIGURES_DOT_LEADER_REVIEW": "Một dòng danh mục hình ảnh có thể thiếu dot leader hoặc số trang căn phải.",
    "LIST_OF_TABLES_TITLE_ALIGNMENT_REVIEW": "Tiêu đề danh mục bảng chưa được căn giữa.",
    "LIST_OF_TABLES_DOT_LEADER_REVIEW": "Một dòng danh mục bảng có thể thiếu dot leader hoặc số trang căn phải.",
    "FIGURE_NUMBERING_MALFORMED_REVIEW": "Số hình bị rối hoặc không đúng mẫu đánh số.",
    "FIGURE_NUMBERING_MISSING_REVIEW": "Dòng hình chưa có số thứ tự hợp lệ.",
    "FIGURE_NUMBERING_MISSING_SEPARATOR_REVIEW": "Caption hình hoặc dòng danh mục hình thiếu dấu chấm/dấu hai chấm sau số thứ tự.",
    "FIGURE_NUMBERING_DUPLICATE_REVIEW": "Số hình bị lặp trong cùng nhóm.",
    "FIGURE_LIST_DUPLICATE_REVIEW": "Số hình bị lặp trong danh mục hình ảnh.",
    "FIGURE_LIST_ENTRY_MISSING_TARGET_REVIEW": "Dòng danh mục hình chưa tìm thấy caption tương ứng trong nội dung.",
    "FIGURE_LIST_TITLE_MISMATCH_REVIEW": "Tiêu đề hình trong danh mục không khớp với caption trong nội dung.",
    "TABLE_NUMBERING_MALFORMED_REVIEW": "Số bảng bị rối hoặc không đúng mẫu đánh số.",
    "TABLE_NUMBERING_MISSING_REVIEW": "Dòng bảng chưa có số thứ tự hợp lệ.",
    "TABLE_NUMBERING_MISSING_SEPARATOR_REVIEW": "Caption bảng hoặc dòng danh mục bảng thiếu dấu chấm/dấu hai chấm sau số thứ tự.",
    "TABLE_NUMBERING_DUPLICATE_REVIEW": "Số bảng bị lặp trong cùng nhóm.",
    "TABLE_LIST_DUPLICATE_REVIEW": "Số bảng bị lặp trong danh mục bảng.",
    "TABLE_LIST_ENTRY_MISSING_TARGET_REVIEW": "Dòng danh mục bảng chưa tìm thấy caption tương ứng trong nội dung.",
    "TABLE_LIST_TITLE_MISMATCH_REVIEW": "Tiêu đề bảng trong danh mục không khớp với caption trong nội dung.",
    "HEADING_CHAPTER_MISMATCH_REVIEW": "Tiểu mục không khớp với chương hiện tại.",
    "CAPTION_ALIGNMENT_ERROR": "Caption hình/bảng chưa được căn giữa.",
    "CAPTION_FONT_NAME_ERROR": "Caption hình/bảng chưa đúng font chữ.",
    "CAPTION_FONT_SIZE_ERROR": "Caption hình/bảng chưa đúng cỡ chữ.",
    "CAPTION_SPACE_BEFORE_PT_ERROR": "Caption hình/bảng chưa đúng khoảng cách trước.",
    "CAPTION_SPACE_AFTER_PT_ERROR": "Caption hình/bảng chưa đúng khoảng cách sau.",
    "TABLE_CELL_FONT_NAME_ERROR": "Chữ trong bảng chưa đúng font.",
    "TABLE_CELL_FONT_SIZE_ERROR": "Chữ trong bảng chưa đúng cỡ chữ.",
    "IMAGE_LAYOUT_REVIEW": "Ảnh hoặc sơ đồ cần được kiểm tra bố cục.",
    "CHARACTER_DENSITY_REVIEW": "Chữ có dấu hiệu bị nén, kéo giãn hoặc thay đổi khoảng cách ký tự.",
    "OUT_OF_SCOPE_TERM_REVIEW": "Đoạn văn chứa cụm từ được cấu hình là ngoài phạm vi đề tài.",
    "PARAGRAPH_ALIGNMENT_ERROR": "Đoạn văn nội dung chưa được căn đều hai bên.",
    "PARAGRAPH_FIRST_LINE_INDENT_ERROR": "Đoạn văn nội dung chưa thụt đầu dòng đúng yêu cầu.",
    "PARAGRAPH_LINE_SPACING_ERROR": "Đoạn văn nội dung chưa đúng giãn dòng.",
    "PARAGRAPH_SPACE_BEFORE_PT_ERROR": "Khoảng cách trước đoạn văn chưa đúng.",
    "PARAGRAPH_SPACE_AFTER_PT_ERROR": "Khoảng cách sau đoạn văn chưa đúng.",
    "PARAGRAPH_FONT_NAME_ERROR": "Font chữ đoạn văn chưa đúng yêu cầu.",
    "PARAGRAPH_FONT_SIZE_ERROR": "Cỡ chữ đoạn văn không đồng nhất hoặc chưa đúng yêu cầu.",
    "PARAGRAPH_BOLD_ERROR": "Đoạn văn nội dung đang có định dạng in đậm không đúng.",
    "HEADING_1_ALIGNMENT_ERROR": "Heading cấp 1 chưa đúng căn lề.",
    "HEADING_1_SPACE_BEFORE_PT_ERROR": "Heading cấp 1 chưa đúng khoảng cách trước.",
    "HEADING_1_SPACE_AFTER_PT_ERROR": "Heading cấp 1 chưa đúng khoảng cách sau.",
    "HEADING_1_FONT_NAME_ERROR": "Heading cấp 1 chưa đúng font chữ.",
    "HEADING_1_FONT_SIZE_ERROR": "Heading cấp 1 chưa đúng cỡ chữ.",
    "HEADING_1_BOLD_ERROR": "Heading cấp 1 chưa đúng định dạng in đậm.",
    "HEADING_1_UPPERCASE_ERROR": "Heading cấp 1 chưa dùng định dạng viết hoa.",
    "HEADING_2_ALIGNMENT_ERROR": "Heading cấp 2 chưa đúng căn lề.",
    "HEADING_2_SPACE_BEFORE_PT_ERROR": "Heading cấp 2 chưa đúng khoảng cách trước.",
    "HEADING_2_SPACE_AFTER_PT_ERROR": "Heading cấp 2 chưa đúng khoảng cách sau.",
    "HEADING_2_FONT_NAME_ERROR": "Heading cấp 2 chưa đúng font chữ.",
    "HEADING_2_FONT_SIZE_ERROR": "Heading cấp 2 chưa đúng cỡ chữ.",
    "HEADING_2_BOLD_ERROR": "Heading cấp 2 chưa đúng định dạng in đậm.",
    "HEADING_2_UPPERCASE_ERROR": "Heading cấp 2 chưa dùng định dạng viết hoa.",
}

MESSAGE_BY_TYPE.update(
    {
        "SECTION_LANDSCAPE_REVIEW": "Section dang de huong ngang va can duoc kiem tra.",
        "TOC_MISSING_REVIEW": "Tai lieu co chuong nhung chua phat hien muc luc.",
        "TOC_NOT_AUTOMATIC_REVIEW": "Muc luc co the dang duoc go tay, chua phai field tu dong.",
        "EXCESSIVE_BLANK_PARAGRAPHS_REVIEW": "Có nhiều dòng trống liên tiếp làm bố cục có thể bị vỡ.",
        "MANUAL_SPACING_REVIEW": "Doan van co dau hieu can le bang dau cach hoac tab thu cong.",
        "MANUAL_PAGE_BREAK_REVIEW": "Doan nay co page break thu cong.",
        "SECTION_BREAK_REVIEW": "Doan nay co section break can kiem tra.",
        "TRACK_CHANGES_REVIEW": "Tai lieu co track changes can kiem tra truoc khi nop.",
        "COMMENTS_OR_TRACKED_REVIEW": "Tai lieu con comment hoac dau vet review can kiem tra.",
        "HYPERLINK_REVIEW": "Doan nay co hyperlink can kiem tra style.",
        "MANUAL_LIST_MARKER_REVIEW": "Dong danh sach co the dang dung dau bullet/so thu cong.",
        "TABLE_WIDTH_REVIEW": "Bang co the rong hon vung noi dung cua trang.",
        "IMAGE_WRAP_REVIEW": "Anh/so do dang dung floating hoac wrap text can kiem tra.",
        "IMAGE_WIDTH_REVIEW": "Anh/so do co the rong hon vung noi dung.",
        "TEXT_DECORATION_REVIEW": "Đoạn này có màu chữ, highlight hoặc gạch chân cần kiểm tra.",
        "TABLE_TEXT_DECORATION_REVIEW": "Chữ trong bảng có màu, highlight hoặc gạch chân cần kiểm tra.",
        "EQUATION_LAYOUT_REVIEW": "Công thức/ký hiệu toán học cần kiểm tra bố cục thủ công.",
        "RENDER_BLANK_PAGE_REVIEW": "Trang render gần như trống, cần kiểm tra lại bố cục.",
        "RENDER_EDGE_OVERFLOW_REVIEW": "Nội dung render nằm quá sát mép trang, có nguy cơ tràn lề hoặc bị cắt.",
        "RENDER_CAPTION_PAGE_BREAK_REVIEW": "Caption xuất hiện ở đầu trang render, cần kiểm tra có bị tách khỏi hình/bảng không.",
        "HEADER_FOOTER_FONT_NAME_ERROR": "Header/footer chua dung font chu.",
        "HEADER_FOOTER_FONT_SIZE_ERROR": "Header/footer chua dung co chu.",
    }
)

SUGGESTION_BY_TYPE = {
    "PAGE_MARGIN_ERROR": "Đặt lại lề trang cho section theo quy chuẩn của trường.",
    "PAPER_SIZE_ERROR": "Đặt lại khổ giấy A4 cho section.",
    "DOCUMENT_PAGE_COUNT_REVIEW": "Kiểm tra số trang nội dung chính và tách phụ lục nếu cần; hệ thống không tự rút gọn nội dung.",
    "PAGE_NUMBER_IN_BODY_ERROR": "Kiểm tra thủ công và đưa số trang về chân trang nếu nó đang nằm trong nội dung văn bản.",
    "PAGE_NUMBER_FOOTER_REVIEW": "Kiểm tra lại chân trang, kiểu số trang La Mã/Ả Rập và vị trí đánh số trang.",
    "HEADER_FOOTER_LAYOUT_REVIEW": "Kiểm tra lại đầu trang/chân trang và đảm bảo không có chữ bị chuyển nhầm thành nội dung thường.",
    "COVER_PAGE_NUMBER_VISIBLE_REVIEW": "Ẩn số trang ở trang bìa bằng tùy chọn trang đầu khác biệt hoặc tách section bìa.",
    "PAGE_NUMBER_ALIGNMENT_REVIEW": "Căn giữa số trang ở footer.",
    "ROMAN_PAGE_NUMBER_REPEATED_REVIEW": "Kiểm tra ngắt section và định dạng số trang để tránh lặp số i.",
    "MAIN_PAGE_NUMBER_FORMAT_REVIEW": "Đặt phần nội dung chính về kiểu số Ả Rập.",
    "MAIN_PAGE_NUMBER_RESET_REVIEW": "Đặt định dạng số trang của section nội dung chính bắt đầu từ 1.",
    "COVER_ALIGNMENT_REVIEW": "Kiểm tra bố cục bìa và căn giữa các khối chữ theo mẫu trường.",
    "CHAPTER_NUMBER_NOT_SEPARATED_REVIEW": "Tách số chương thành một dòng riêng; đặt tiêu đề chương ở dòng ngay dưới.",
    "CHAPTER_NUMBER_LABEL_REVIEW": "Kiểm tra lại dòng số chương theo mẫu CHƯƠNG 1.",
    "CHAPTER_NUMBER_ALIGNMENT_REVIEW": "Căn giữa dòng số chương.",
    "CHAPTER_NUMBER_BOLD_REVIEW": "Đặt dòng số chương ở dạng chữ đậm.",
    "CHAPTER_TITLE_MISSING_REVIEW": "Thêm hoặc kiểm tra tiêu đề chương ngay dưới dòng số chương.",
    "CHAPTER_TITLE_UPPERCASE_REVIEW": "Kiểm tra và chuyển tiêu đề chương sang chữ in hoa nếu đúng mẫu trường.",
    "CHAPTER_TITLE_ALIGNMENT_REVIEW": "Căn giữa tiêu đề chương.",
    "CHAPTER_TITLE_BOLD_REVIEW": "Đặt tiêu đề chương ở dạng chữ đậm.",
    "TOC_TITLE_ALIGNMENT_REVIEW": "Căn giữa tiêu đề mục lục theo mẫu trường.",
    "TOC_DOT_LEADER_REVIEW": "Cập nhật lại mục lục bằng Word và kiểm tra số trang căn phải.",
    "LIST_OF_FIGURES_TITLE_ALIGNMENT_REVIEW": "Căn giữa tiêu đề danh mục hình ảnh theo mẫu trường.",
    "LIST_OF_FIGURES_DOT_LEADER_REVIEW": "Cập nhật lại danh mục hình ảnh và kiểm tra số trang căn phải.",
    "LIST_OF_TABLES_TITLE_ALIGNMENT_REVIEW": "Căn giữa tiêu đề danh mục bảng theo mẫu trường.",
    "LIST_OF_TABLES_DOT_LEADER_REVIEW": "Cập nhật lại danh mục bảng và kiểm tra số trang căn phải.",
    "FIGURE_NUMBERING_MALFORMED_REVIEW": "Kiểm tra lại caption/danh mục hình; số hình nên có dạng Hình x.y.",
    "FIGURE_NUMBERING_MISSING_REVIEW": "Kiểm tra lại định dạng số hình.",
    "FIGURE_NUMBERING_MISSING_SEPARATOR_REVIEW": "Thêm dấu chấm hoặc dấu hai chấm sau số hình, ví dụ Hình 2.1. Tên hình.",
    "FIGURE_NUMBERING_DUPLICATE_REVIEW": "Kiểm tra lại caption/danh mục hình và cập nhật numbering nếu bị lặp.",
    "FIGURE_LIST_DUPLICATE_REVIEW": "Cập nhật lại danh mục hình ảnh và kiểm tra caption bị lặp.",
    "FIGURE_LIST_ENTRY_MISSING_TARGET_REVIEW": "Kiểm tra caption trong nội dung hoặc cập nhật lại danh mục hình ảnh.",
    "FIGURE_LIST_TITLE_MISMATCH_REVIEW": "Cập nhật lại danh mục hình ảnh sau khi chỉnh caption trong nội dung.",
    "TABLE_NUMBERING_MALFORMED_REVIEW": "Kiểm tra lại caption/danh mục bảng; số bảng nên có dạng Bảng x.y.",
    "TABLE_NUMBERING_MISSING_REVIEW": "Kiểm tra lại định dạng số bảng.",
    "TABLE_NUMBERING_MISSING_SEPARATOR_REVIEW": "Thêm dấu chấm hoặc dấu hai chấm sau số bảng, ví dụ Bảng 2.1. Tên bảng.",
    "TABLE_NUMBERING_DUPLICATE_REVIEW": "Kiểm tra lại caption/danh mục bảng và cập nhật numbering nếu bị lặp.",
    "TABLE_LIST_DUPLICATE_REVIEW": "Cập nhật lại danh mục bảng và kiểm tra caption bị lặp.",
    "TABLE_LIST_ENTRY_MISSING_TARGET_REVIEW": "Kiểm tra caption trong nội dung hoặc cập nhật lại danh mục bảng.",
    "TABLE_LIST_TITLE_MISMATCH_REVIEW": "Cập nhật lại danh mục bảng sau khi chỉnh caption trong nội dung.",
    "HEADING_CHAPTER_MISMATCH_REVIEW": "Kiểm tra cấu trúc chương; có thể thiếu dòng Chương tương ứng hoặc tài liệu bị ghép sai thứ tự.",
    "CAPTION_ALIGNMENT_ERROR": "Đặt caption hình/bảng về kiểu định dạng caption chuẩn.",
    "CAPTION_FONT_NAME_ERROR": "Áp dụng lại kiểu định dạng caption chuẩn.",
    "CAPTION_FONT_SIZE_ERROR": "Áp dụng lại kiểu định dạng caption chuẩn.",
    "CAPTION_SPACE_BEFORE_PT_ERROR": "Kiểm tra khoảng cách caption theo mẫu trường.",
    "CAPTION_SPACE_AFTER_PT_ERROR": "Kiểm tra khoảng cách caption theo mẫu trường.",
    "TABLE_CELL_FONT_NAME_ERROR": "Kiểm tra kiểu định dạng chữ trong bảng theo mẫu trường.",
    "TABLE_CELL_FONT_SIZE_ERROR": "Kiểm tra kiểu định dạng chữ trong bảng theo mẫu trường.",
    "IMAGE_LAYOUT_REVIEW": "Kiểm tra kích thước, vị trí, kiểu bọc chữ và caption của ảnh/sơ đồ.",
    "CHARACTER_DENSITY_REVIEW": "Đặt lại cài đặt font nâng cao: tỉ lệ 100%, khoảng cách ký tự bình thường.",
    "OUT_OF_SCOPE_TERM_REVIEW": "Kiểm tra thủ công xem nội dung này còn thuộc phạm vi đề tài hiện tại không.",
    "PARAGRAPH_ALIGNMENT_ERROR": "Căn đều hai bên cho đoạn văn nội dung.",
    "PARAGRAPH_FIRST_LINE_INDENT_ERROR": "Thiết lập thụt đầu dòng đúng theo quy chuẩn.",
    "PARAGRAPH_LINE_SPACING_ERROR": "Thiết lập lại giãn dòng cho đoạn văn nội dung.",
    "PARAGRAPH_SPACE_BEFORE_PT_ERROR": "Thiết lập khoảng cách trước đoạn theo quy chuẩn.",
    "PARAGRAPH_SPACE_AFTER_PT_ERROR": "Thiết lập khoảng cách sau đoạn theo quy chuẩn.",
    "PARAGRAPH_FONT_NAME_ERROR": "Áp dụng lại kiểu định dạng nội dung chuẩn: Times New Roman.",
    "PARAGRAPH_FONT_SIZE_ERROR": "Áp dụng lại kiểu định dạng nội dung chuẩn để cỡ chữ đồng nhất theo yêu cầu.",
    "PARAGRAPH_BOLD_ERROR": "Bỏ hoặc đặt lại in đậm theo đúng kiểu định dạng nội dung.",
    "HEADING_1_UPPERCASE_ERROR": "Áp dụng kiểu định dạng Heading 1 theo mẫu báo cáo.",
}


SUGGESTION_BY_TYPE.update(
    {
        "SECTION_LANDSCAPE_REVIEW": "Kiểm tra section này có phải phụ lục hoặc bảng ngang hợp lệ không; nếu không thì chuyển về hướng dọc.",
        "TOC_MISSING_REVIEW": "Tạo mục lục bằng chức năng mục lục tự động của Word để cập nhật được số trang.",
        "TOC_NOT_AUTOMATIC_REVIEW": "Dùng chức năng tạo/cập nhật mục lục tự động trong Word thay vì gõ tay.",
        "EXCESSIVE_BLANK_PARAGRAPHS_REVIEW": "Kiểm tra các dòng trống thủ công; nếu cần xuống trang thì dùng ngắt trang hoặc section đúng cách.",
        "MANUAL_SPACING_REVIEW": "Xóa căn lề thủ công nếu có và áp dụng lại kiểu định dạng phù hợp trong Word.",
        "MANUAL_PAGE_BREAK_REVIEW": "Kiểm tra ngắt trang thủ công; nếu nó làm sai đánh số trang hoặc bố cục thì điều chỉnh trong Word.",
        "SECTION_BREAK_REVIEW": "Kiểm tra ngắt section, chân trang và đánh số trang quanh vị trí này.",
        "TRACK_CHANGES_REVIEW": "Mở Word và kiểm tra mục Theo dõi thay đổi trước khi nộp.",
        "COMMENTS_OR_TRACKED_REVIEW": "Mở Word và kiểm tra mục Nhận xét/Theo dõi thay đổi trước khi nộp.",
        "HYPERLINK_REVIEW": "Kiểm tra màu chữ, gạch chân và tính hợp lệ của liên kết trong Word.",
        "MANUAL_LIST_MARKER_REVIEW": "Kiểm tra lại thiết lập danh sách trong Word để tránh lề bullet bị lệch khi tự động định dạng.",
        "TABLE_WIDTH_REVIEW": "Kiểm tra độ rộng bảng, độ rộng cột hoặc đưa bảng lớn sang phụ lục/section ngang.",
        "IMAGE_WRAP_REVIEW": "Kiểm tra tùy chọn bố cục của ảnh; ưu tiên đặt ảnh nằm cùng dòng với chữ nếu mẫu trường yêu cầu.",
        "IMAGE_WIDTH_REVIEW": "Kiểm tra kích thước ảnh/sơ đồ và thu nhỏ nếu ảnh tràn lề.",
        "TEXT_DECORATION_REVIEW": "Kiểm tra lại định dạng chữ; chỉ giữ màu, highlight hoặc gạch chân khi đó là yêu cầu trình bày hợp lệ.",
        "TABLE_TEXT_DECORATION_REVIEW": "Kiểm tra lại định dạng chữ trong bảng; chỉ giữ màu, highlight hoặc gạch chân khi đó là yêu cầu trình bày hợp lệ.",
        "EQUATION_LAYOUT_REVIEW": "Mở Word để kiểm tra căn giữa, số thứ tự công thức, font ký hiệu và vị trí ngắt trang quanh công thức.",
        "RENDER_BLANK_PAGE_REVIEW": "Mở bản Word/PDF render để kiểm tra ngắt trang, ngắt section hoặc bảng/ảnh bị đẩy trang.",
        "RENDER_EDGE_OVERFLOW_REVIEW": "Kiểm tra trang render này; nếu bảng, ảnh, đầu trang/chân trang hoặc chữ bị sát mép/mất chữ thì chỉnh thủ công trong Word.",
        "RENDER_CAPTION_PAGE_BREAK_REVIEW": "Mở trang render để kiểm tra caption có còn đi cùng hình/bảng hay bị nhảy sang trang mới.",
        "HEADER_FOOTER_FONT_NAME_ERROR": "Kiểm tra kiểu định dạng đầu trang/chân trang theo mẫu trường.",
        "HEADER_FOOTER_FONT_SIZE_ERROR": "Kiểm tra cỡ chữ đầu trang/chân trang theo mẫu trường.",
    }
)


FIELD_LABELS.update(
    {
        "comment_artifact": "Nhận xét/comment",
        "track_changes": "Track changes",
    }
)
RULE_NAMES.update(
    {
        "TRACK_CHANGES_REVIEW": ("TRACK_CHANGES", "Track changes cần kiểm tra"),
        "COMMENTS_REVIEW": ("COMMENTS_REVIEW", "Nhận xét còn trong file"),
    }
)
MESSAGE_BY_TYPE.update(
    {
        "COMMENTS_REVIEW": "Tài liệu còn comment hoặc dấu vết nhận xét cần kiểm tra.",
        "TRACK_CHANGES_REVIEW": "Tài liệu có track changes thật cần kiểm tra trước khi nộp.",
    }
)
SUGGESTION_BY_TYPE.update(
    {
        "COMMENTS_REVIEW": "Mở Word, kiểm tra thẻ Review và xóa comment trước khi nộp nếu quy định yêu cầu.",
        "TRACK_CHANGES_REVIEW": "Mở Word và accept/reject toàn bộ Track Changes, lưu file sạch rồi upload lại.",
    }
)


class ReportBuilder:
    def build(
        self,
        *,
        raw_findings: list[dict[str, Any]],
        document_id: str,
        document_type: str,
        filename: str | None = None,
        template_name: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        generated_at = generated_at or datetime.now(timezone.utc).isoformat()
        issues = [
            self._issue_from_finding(index, finding)
            for index, finding in enumerate(raw_findings, start=1)
        ]
        summary = self._summary(issues)
        groups = self._groups(issues)
        manual_repair_guidance = build_summary_repair_guidance(issues)

        report = ProductionReport(
            ok=True,
            message="Phân tích định dạng hoàn tất.",
            document={
                "id": document_id,
                "filename": filename,
                "document_type": document_type,
                "analyzed_at": generated_at,
            },
            reference={
                "mode": "style_only",
                "template_name": template_name or document_type,
                "rule_source": "template_config",
                "sample_document_used_for_rules": False,
                "sample_document_role": "reference_only",
                "note": (
                    "Chuẩn bắt lỗi lấy từ cấu hình template. File mẫu, nếu có, chỉ dùng để tham khảo "
                    "trình bày và không được coi là chuẩn tự động."
                ),
            },
            summary=summary,
            issue_groups=groups,
            manual_repair_guidance=manual_repair_guidance,
        )
        return report.to_dict()

    def _issue_from_finding(self, index: int, finding: dict[str, Any]) -> dict[str, Any]:
        metadata = _metadata(finding)
        finding_type = str(finding.get("type") or "FORMAT_ERROR")
        field = str(metadata.get("field") or "")
        group_id = _group_id(finding_type, metadata)
        severity = _report_severity(finding_type, metadata)
        fixability = classify_fixability(finding_type, metadata=metadata, group_id=group_id)
        auto_fixable = fixability.auto_fixable
        manual_review = fixability.manual_review
        rule_id, rule_name = _rule_identity(finding_type, metadata)
        fix_action = fixability.fix_action

        issue = {
            "issue_id": f"ISSUE-{index:04d}",
            "group_id": group_id,
            "severity": severity,
            "auto_fixable": auto_fixable,
            "manual_review": manual_review,
            "fixability_scope": fixability.scope,
            "fixability": {
                "scope": fixability.scope,
                "reason": normalize_vietnamese_display(fixability.reason),
            },
            "location": {
                "page": metadata.get("page"),
                "section_index": metadata.get("section_index"),
                "paragraph_index": metadata.get("paragraph_index"),
                "heading_path": _list_or_empty(metadata.get("heading_path")),
                "raw": finding.get("location"),
            },
            "target": {
                "type": metadata.get("target") or metadata.get("context") or _target_from_type(finding_type),
                "context": metadata.get("context"),
                "text_preview": metadata.get("text_preview"),
                "style_name": metadata.get("style_name"),
            },
            "rule": {
                "rule_id": rule_id,
                "rule_name": normalize_vietnamese_display(rule_name),
            },
            "current": _value_object(field, finding.get("current_value")),
            "expected": _value_object(field, finding.get("expected_value")),
            "message": normalize_vietnamese_display(
                MESSAGE_BY_TYPE.get(finding_type) or _clean_sentence(finding.get("message"))
            ),
            "suggestion": normalize_vietnamese_display(
                SUGGESTION_BY_TYPE.get(finding_type) or _clean_sentence(finding.get("suggestion"))
            ),
            "fix_action": normalize_fix_action(fix_action),
        }
        issue["repair"] = build_issue_repair_guidance(issue)
        return issue

    def _summary(self, issues: list[dict[str, Any]]) -> ReportSummary:
        return ReportSummary(
            total_issues=len(issues),
            critical=sum(1 for issue in issues if issue["severity"] == "critical"),
            major=sum(1 for issue in issues if issue["severity"] == "major"),
            minor=sum(1 for issue in issues if issue["severity"] == "minor"),
            auto_fixable=sum(1 for issue in issues if issue["auto_fixable"]),
            manual_review=sum(1 for issue in issues if issue["manual_review"]),
            style_fix_groups=_style_fix_groups(issues),
            manual_repair_guidance=build_summary_repair_guidance(issues),
        )

    def _groups(self, issues: list[dict[str, Any]]) -> list[ReportIssueGroup]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for issue in issues:
            grouped[issue["group_id"]].append(issue)

        result: list[ReportIssueGroup] = []
        for group_id in sorted(grouped, key=_group_sort_key):
            group_issues = grouped[group_id]
            group_meta = GROUPS.get(
                group_id,
                {
                    "name": "Lỗi định dạng khác",
                    "description": "Các lỗi định dạng cần kiểm tra.",
                },
            )
            result.append(
                ReportIssueGroup(
                    group_id=group_id,
                    group_name=group_meta["name"],
                    total=len(group_issues),
                    severity=_max_severity(group_issues),
                    description=group_meta["description"],
                    issues=group_issues,
                    recommended_fix_scope=_recommended_fix_scope(group_id, group_issues),
                    affected_styles=_affected_styles(group_issues),
                    manual_repair_guidance=build_group_repair_guidance(group_id, group_issues),
                )
            )
        return result


def _style_fix_groups(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for issue in issues:
        if not issue.get("auto_fixable"):
            continue
        style_name = str(issue.get("target", {}).get("style_name") or "").strip()
        if not style_name:
            continue
        rule_id = str(issue.get("rule", {}).get("rule_id") or "")
        expected = repr(issue.get("expected") or {})
        grouped[(style_name, rule_id, expected)].append(issue)

    result: list[dict[str, Any]] = []
    for (style_name, rule_id, _expected), group_issues in grouped.items():
        if len(group_issues) < 2:
            continue
        first = group_issues[0]
        result.append(
            {
                "style_name": style_name,
                "rule_id": rule_id,
                "rule_name": first.get("rule", {}).get("rule_name"),
                "count": len(group_issues),
                "expected": first.get("expected") or {},
                "sample_locations": [
                    issue.get("location", {}).get("raw")
                    for issue in group_issues[:5]
                    if issue.get("location", {}).get("raw")
                ],
            }
        )

    return sorted(result, key=lambda item: (-int(item["count"]), str(item["style_name"]), str(item["rule_id"])))


def _recommended_fix_scope(group_id: str, issues: list[dict[str, Any]]) -> str:
    if issues and all(issue.get("manual_review") for issue in issues):
        return "manual_review"
    if group_id in {"body_paragraph", "heading", "front_matter", "list_item"} and len(_style_fix_groups(issues)) > 0:
        return "style"
    if any(issue.get("auto_fixable") for issue in issues):
        return "paragraph"
    return "manual_review"


def _affected_styles(issues: list[dict[str, Any]]) -> list[str]:
    styles = {
        str(issue.get("target", {}).get("style_name") or "").strip()
        for issue in issues
        if str(issue.get("target", {}).get("style_name") or "").strip()
    }
    return sorted(styles)


def _metadata(finding: dict[str, Any]) -> dict[str, Any]:
    metadata = finding.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _group_id(finding_type: str, metadata: dict[str, Any]) -> str:
    explicit = metadata.get("report_group_id")
    if isinstance(explicit, str) and explicit:
        return explicit

    if finding_type.startswith(("PAGE_", "PAPER_")):
        return "page_setup"
    if finding_type.startswith("HEADING_"):
        return "heading"
    if finding_type.startswith("FRONT_MATTER_HEADING_"):
        return "front_matter"
    if finding_type.startswith("LIST_ITEM_"):
        return "list_item"
    if finding_type.startswith("PARAGRAPH_"):
        return "body_paragraph"
    if finding_type.startswith("CAPTION_"):
        return "caption"
    if finding_type.startswith("TABLE_CELL_"):
        return "table_cell_format"
    if finding_type.startswith("HEADER_FOOTER_"):
        return "header_footer_format"
    return "layout_abnormal"


def _report_severity(finding_type: str, metadata: dict[str, Any]) -> ReportSeverity:
    explicit = metadata.get("report_severity")
    if explicit in {"critical", "major", "minor"}:
        return explicit

    if finding_type in {"PAGE_NUMBER_IN_BODY_ERROR"}:
        return "critical"
    if any(marker in finding_type for marker in ("SPACE_", "LINE_SPACING")):
        return "minor"
    return "major"


def _rule_identity(finding_type: str, metadata: dict[str, Any]) -> tuple[str, str]:
    rule_id = metadata.get("rule_id")
    rule_name = metadata.get("rule_name")
    if isinstance(rule_id, str) and isinstance(rule_name, str):
        return rule_id, rule_name
    dynamic_identity = _dynamic_rule_identity(finding_type)
    if dynamic_identity is not None:
        return dynamic_identity
    return RULE_NAMES.get(finding_type, (finding_type, "Lỗi định dạng cần kiểm tra"))


def get_rule_identity(finding_type: str, metadata: dict[str, Any] | None = None) -> tuple[str, str]:
    return _rule_identity(finding_type, metadata or {})


def _dynamic_rule_identity(finding_type: str) -> tuple[str, str] | None:
    dynamic_names = {
        "FIGURE_NUMBERING_CHAPTER_MISMATCH_REVIEW": (
            "FIGURE_NUMBERING_CHAPTER_MISMATCH",
            "Số hình không khớp chương",
        ),
        "TABLE_NUMBERING_CHAPTER_MISMATCH_REVIEW": (
            "TABLE_NUMBERING_CHAPTER_MISMATCH",
            "Số bảng không khớp chương",
        ),
        "FRONT_MATTER_HEADING_ALIGNMENT_ERROR": (
            "FRONT_MATTER_HEADING_ALIGNMENT",
            "Căn giữa tiêu đề phần đầu",
        ),
        "FRONT_MATTER_HEADING_SPACE_AFTER_PT_ERROR": (
            "FRONT_MATTER_HEADING_SPACE_AFTER",
            "Khoảng cách sau tiêu đề phần đầu",
        ),
        "FRONT_MATTER_HEADING_FONT_NAME_ERROR": (
            "FRONT_MATTER_HEADING_FONT_NAME",
            "Font chữ tiêu đề phần đầu",
        ),
        "FRONT_MATTER_HEADING_FONT_SIZE_ERROR": (
            "FRONT_MATTER_HEADING_FONT_SIZE",
            "Cỡ chữ tiêu đề phần đầu",
        ),
        "FRONT_MATTER_HEADING_BOLD_ERROR": (
            "FRONT_MATTER_HEADING_BOLD",
            "In đậm tiêu đề phần đầu",
        ),
        "FRONT_MATTER_HEADING_UPPERCASE_ERROR": (
            "FRONT_MATTER_HEADING_UPPERCASE",
            "Viết hoa tiêu đề phần đầu",
        ),
        "LIST_ITEM_LINE_SPACING_ERROR": ("LIST_ITEM_LINE_SPACING", "Giãn dòng bullet/list"),
        "LIST_ITEM_SPACE_BEFORE_PT_ERROR": ("LIST_ITEM_SPACE_BEFORE", "Khoảng cách trước bullet/list"),
        "LIST_ITEM_SPACE_AFTER_PT_ERROR": ("LIST_ITEM_SPACE_AFTER", "Khoảng cách sau bullet/list"),
        "LIST_ITEM_FONT_NAME_ERROR": ("LIST_ITEM_FONT_NAME", "Font chữ bullet/list"),
        "LIST_ITEM_FONT_SIZE_ERROR": ("LIST_ITEM_FONT_SIZE", "Cỡ chữ bullet/list"),
    }
    return dynamic_names.get(finding_type)


def _target_from_type(finding_type: str) -> str:
    if finding_type.startswith(("PAGE_", "PAPER_")):
        return "section"
    if finding_type.startswith("HEADING_"):
        return "heading"
    return "paragraph"


def _value_object(field: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {}

    key = field or "value"
    return {
        key: _human_value(str(value)),
        "_label": normalize_vietnamese_display(FIELD_LABELS.get(key, key.replace("_", " "))),
    }


def _human_value(value: str) -> str:
    stripped = value.strip()
    return normalize_vietnamese_display(
        VALUE_LABELS.get(stripped) or VALUE_LABELS.get(stripped.upper()) or stripped
    )


def _clean_sentence(value: Any) -> str:
    if not value:
        return "Cần kiểm tra định dạng theo quy chuẩn."
    text = normalize_vietnamese_display(str(value).strip())
    replacements = {
        "Paragraph alignment does not match the required format.": "Căn lề đoạn văn chưa đúng yêu cầu.",
        "First-line indent does not match the required format.": "Thụt đầu dòng chưa đúng yêu cầu.",
        "Line spacing does not match the required format.": "Giãn dòng chưa đúng yêu cầu.",
        "Font name does not match the required format.": "Font chữ chưa đúng yêu cầu.",
        "Font size is inconsistent or does not match the required format.": "Cỡ chữ không đồng nhất hoặc chưa đúng yêu cầu.",
        "Bold formatting does not match the required format.": "Định dạng in đậm chưa đúng yêu cầu.",
        "Heading text is not uppercase.": "Heading chưa viết hoa theo yêu cầu.",
    }
    replacements.update(
        {
            "Space before does not match the required format.": "Khoảng cách trước đoạn chưa đúng yêu cầu.",
            "Space after does not match the required format.": "Khoảng cách sau đoạn chưa đúng yêu cầu.",
            "Front-matter heading text is not uppercase.": "Tiêu đề phần đầu chưa viết hoa theo yêu cầu.",
            "Image or diagram may be missing a nearby caption.": "Ảnh hoặc sơ đồ trong nội dung có thể thiếu caption gần đó.",
            "Figure/table chapter prefix does not match the current chapter.": "Số hình/bảng không khớp với chương hiện tại.",
            "Figure/table numbering appears malformed.": "Số hình/bảng có dấu hiệu bị sai định dạng.",
            "Review list item formatting; keep bullet/number indentation controlled by Word list settings.": "Kiểm tra định dạng bullet/list; giữ thụt lề theo thiết lập danh sách của Word, không ép như đoạn văn thường.",
            "Review the front-matter heading style separately from chapter headings.": "Kiểm tra style tiêu đề phần đầu riêng với heading chương.",
            "Use uppercase formatting for this front-matter heading.": "Đặt tiêu đề phần đầu ở dạng chữ hoa theo mẫu trình bày.",
            "Review this content image and add or update the figure/table caption near the image if needed.": "Kiểm tra ảnh/sơ đồ trong nội dung và bổ sung hoặc cập nhật caption gần ảnh nếu cần.",
            "Review footer page numbering, roman/front-matter numbering, and main-content numbering.": "Kiểm tra footer, số trang La Mã ở phần đầu và số trang phần nội dung chính.",
        }
    )
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


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _max_severity(issues: list[dict[str, Any]]) -> ReportSeverity:
    severities = {issue["severity"] for issue in issues}
    if "critical" in severities:
        return "critical"
    if "major" in severities:
        return "major"
    return "minor"


def _group_sort_key(group_id: str) -> tuple[int, str]:
    try:
        return (GROUP_ORDER.index(group_id), group_id)
    except ValueError:
        return (len(GROUP_ORDER), group_id)
