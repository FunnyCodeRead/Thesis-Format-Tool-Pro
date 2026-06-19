from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.services.docx_formatter.engine.vietnamese_text import normalize_vietnamese_display

MAX_SAMPLE_LOCATIONS = 5
SUMMARY_GUIDANCE_LIMIT = 8


def build_issue_repair_guidance(issue: dict[str, Any]) -> dict[str, Any] | None:
    if not issue.get("manual_review"):
        return None

    group_id = str(issue.get("group_id") or "layout_abnormal")
    rule_id = str(issue.get("rule", {}).get("rule_id") or "")
    template = _template_for(group_id, rule_id)
    location = issue.get("location") if isinstance(issue.get("location"), dict) else {}

    return {
        "required": True,
        "guide_id": template["guide_id"],
        "title": template["title"],
        "repair_scope": template["repair_scope"],
        "difficulty": template["difficulty"],
        "estimated_minutes": template["estimated_minutes"],
        "tool": "Microsoft Word",
        "not_auto_fix_reason": template["not_auto_fix_reason"],
        "steps": template["steps"],
        "verify": template["verify"],
        "warning": template["warning"],
        "issue_ids": [issue.get("issue_id")],
        "sample_locations": _sample_locations([location]),
    }


def build_group_repair_guidance(
    group_id: str,
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    manual_issues = [issue for issue in issues if issue.get("manual_review")]
    if not manual_issues:
        return []

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in manual_issues:
        repair = issue.get("repair")
        guide_id = repair.get("guide_id") if isinstance(repair, dict) else None
        grouped[str(guide_id or _template_for(group_id, "")["guide_id"])].append(issue)

    result: list[dict[str, Any]] = []
    for guide_id, guide_issues in grouped.items():
        first_repair = guide_issues[0].get("repair")
        if not isinstance(first_repair, dict):
            continue
        result.append(
            {
                **_without_issue_specific_fields(first_repair),
                "guide_id": guide_id,
                "count": len(guide_issues),
                "issue_ids": [issue.get("issue_id") for issue in guide_issues if issue.get("issue_id")],
                "sample_locations": _sample_locations(
                    [
                        issue.get("location")
                        for issue in guide_issues
                        if isinstance(issue.get("location"), dict)
                    ]
                ),
            }
        )

    return sorted(result, key=lambda item: (-int(item["count"]), str(item["title"])))


def build_summary_repair_guidance(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manual_issues = [issue for issue in issues if issue.get("manual_review")]
    if not manual_issues:
        return []

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in manual_issues:
        repair = issue.get("repair")
        guide_id = repair.get("guide_id") if isinstance(repair, dict) else None
        if guide_id:
            grouped[str(guide_id)].append(issue)

    result: list[dict[str, Any]] = []
    for guide_id, guide_issues in grouped.items():
        first_repair = guide_issues[0].get("repair")
        if not isinstance(first_repair, dict):
            continue
        affected_groups = sorted({str(issue.get("group_id") or "") for issue in guide_issues if issue.get("group_id")})
        result.append(
            {
                **_without_issue_specific_fields(first_repair),
                "guide_id": guide_id,
                "count": len(guide_issues),
                "affected_groups": affected_groups,
                "sample_locations": _sample_locations(
                    [
                        issue.get("location")
                        for issue in guide_issues
                        if isinstance(issue.get("location"), dict)
                    ]
                ),
            }
        )

    return sorted(result, key=lambda item: (-int(item["count"]), str(item["title"])))[:SUMMARY_GUIDANCE_LIMIT]


def _template_for(group_id: str, rule_id: str) -> dict[str, Any]:
    exact = _EXACT_TEMPLATES.get(rule_id)
    if exact:
        return exact
    return _GROUP_TEMPLATES.get(group_id, _GROUP_TEMPLATES["layout_abnormal"])


def _without_issue_specific_fields(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key not in {"required", "issue_ids", "sample_locations"}
    }


def _sample_locations(locations: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for location in locations:
        label = _location_label(location)
        if label and label not in result:
            result.append(label)
        if len(result) >= MAX_SAMPLE_LOCATIONS:
            break
    return result


def _location_label(location: dict[str, Any]) -> str | None:
    raw = location.get("raw")
    if raw:
        return normalize_vietnamese_display(raw)
    page = location.get("page")
    paragraph_index = location.get("paragraph_index")
    section_index = location.get("section_index")
    if page:
        return f"Trang {page}"
    if section_index:
        return f"Section {section_index}"
    if paragraph_index:
        return f"Đoạn {paragraph_index}"
    return None


_GROUP_TEMPLATES: dict[str, dict[str, Any]] = {
    "document_length": {
        "guide_id": "manual_document_length",
        "title": "Kiểm tra số trang theo phạm vi nội dung chính",
        "repair_scope": "document",
        "difficulty": "medium",
        "estimated_minutes": 5,
        "not_auto_fix_reason": "Số trang phụ thuộc phụ lục, section và bản render; hệ thống không được xóa hoặc rút gọn nội dung.",
        "steps": [
            "Mở file Word và kiểm tra tổng số trang sau khi đã cập nhật mục lục/danh mục.",
            "Xác định phần phụ lục có được loại khỏi giới hạn số trang hay không theo quy định trường.",
            "Nếu số trang vượt chuẩn vì khoảng trắng, bảng hoặc hình bị vỡ trang, sửa layout thay vì xóa nội dung.",
        ],
        "verify": [
            "Xuất hoặc xem bản PDF để kiểm tra số trang cuối cùng.",
            "Đảm bảo phụ lục, tài liệu tham khảo và phần đầu được tính đúng theo quy định.",
        ],
        "warning": "Không rút gọn hoặc viết lại nội dung trong tool; mọi thay đổi nội dung phải do người dùng tự quyết định.",
    },
    "header_footer_page_number": {
        "guide_id": "manual_page_numbering",
        "title": "Sửa header/footer và đánh số trang trong Word",
        "repair_scope": "section",
        "difficulty": "advanced",
        "estimated_minutes": 10,
        "not_auto_fix_reason": "Đánh số trang phụ thuộc section, footer và Link to Previous; tự sửa có thể làm sai toàn bộ tài liệu.",
        "steps": [
            "Mở Word và bật hiển thị header/footer ở section được báo lỗi.",
            "Kiểm tra Different First Page, Link to Previous và Format Page Numbers cho từng section.",
            "Đặt số trang ở footer, căn giữa phía dưới nếu đó là quy chuẩn trường.",
            "Với phần đầu dùng số La Mã và phần nội dung chính dùng số Ả Rập, cấu hình Start at đúng ở section bắt đầu.",
        ],
        "verify": [
            "Trang bìa không hiển thị số trang nếu quy định yêu cầu.",
            "Phần đầu không bị lặp i, ii bất thường.",
            "Chương 1 hoặc nội dung chính bắt đầu đúng số trang theo mẫu.",
        ],
        "warning": "Không nên để fixer tự đổi header/footer phức tạp; hãy kiểm tra bằng mắt trên Word hoặc PDF.",
    },
    "chapter_layout": {
        "guide_id": "manual_chapter_layout",
        "title": "Sửa cấu trúc trình bày chương",
        "repair_scope": "heading",
        "difficulty": "medium",
        "estimated_minutes": 6,
        "not_auto_fix_reason": "Tách số chương và tiêu đề chương có thể làm thay đổi cấu trúc đoạn, nên cần người dùng xác nhận.",
        "steps": [
            "Đặt dòng số chương như 'Chương 1.' trên một dòng riêng.",
            "Đặt tiêu đề chương ở dòng ngay bên dưới, viết hoa nếu mẫu yêu cầu.",
            "Căn giữa và in đậm hai dòng theo quy chuẩn trường.",
            "Kiểm tra các mục 1.1, 1.2 hoặc 2.1 có nằm đúng dưới chương tương ứng.",
        ],
        "verify": [
            "Mục lục cập nhật đúng tên chương và số trang.",
            "Không còn tiểu mục của Chương 2 nằm trong vùng Chương 1.",
        ],
        "warning": "Không tự đổi chữ tiêu đề chương bằng backend vì đó là nội dung của người dùng.",
    },
    "toc": {
        "guide_id": "manual_toc",
        "title": "Tạo hoặc cập nhật mục lục tự động",
        "repair_scope": "document",
        "difficulty": "medium",
        "estimated_minutes": 7,
        "not_auto_fix_reason": "Mục lục là field Word phức tạp; backend không tự tạo/xóa field để tránh làm hỏng cấu trúc tài liệu.",
        "steps": [
            "Gán đúng style Heading 1/2/3 cho các tiêu đề chương và mục.",
            "Vào References > Table of Contents để tạo mục lục tự động.",
            "Nếu đã có mục lục, chọn Update Table và cập nhật toàn bộ bảng.",
            "Không gõ tay dấu chấm dẫn hoặc số trang nếu có thể dùng TOC field.",
        ],
        "verify": [
            "Mục lục có dấu chấm dẫn, số trang đúng và cập nhật được.",
            "Các heading không thuộc nội dung chính không bị kéo nhầm vào mục lục.",
        ],
        "warning": "Sau khi sửa heading/chapter, luôn Update Table lại một lần.",
    },
    "list_of_figures": {
        "guide_id": "manual_figure_table_list",
        "title": "Sửa danh mục hình/bảng",
        "repair_scope": "document",
        "difficulty": "medium",
        "estimated_minutes": 8,
        "not_auto_fix_reason": "Danh mục hình/bảng phụ thuộc caption field và tiêu đề thật; hệ thống không tự viết lại caption.",
        "steps": [
            "Kiểm tra từng caption hình/bảng trong thân bài trước.",
            "Dùng References > Insert Table of Figures để tạo danh mục từ caption.",
            "Nếu số hình/bảng bị trùng hoặc sai chương, sửa caption nguồn rồi cập nhật lại danh mục.",
        ],
        "verify": [
            "Mỗi dòng danh mục có caption tương ứng trong thân bài.",
            "Số hình/bảng không bị lặp và khớp chương hiện tại.",
        ],
        "warning": "Không sửa danh mục bằng cách gõ tay nếu caption nguồn còn sai.",
    },
    "list_of_tables": {
        "guide_id": "manual_figure_table_list",
        "title": "Sửa danh mục hình/bảng",
        "repair_scope": "document",
        "difficulty": "medium",
        "estimated_minutes": 8,
        "not_auto_fix_reason": "Danh mục hình/bảng phụ thuộc caption field và tiêu đề thật; hệ thống không tự viết lại caption.",
        "steps": [
            "Kiểm tra từng caption hình/bảng trong thân bài trước.",
            "Dùng References > Insert Table of Figures để tạo danh mục từ caption.",
            "Nếu số hình/bảng bị trùng hoặc sai chương, sửa caption nguồn rồi cập nhật lại danh mục.",
        ],
        "verify": [
            "Mỗi dòng danh mục có caption tương ứng trong thân bài.",
            "Số hình/bảng không bị lặp và khớp chương hiện tại.",
        ],
        "warning": "Không sửa danh mục bằng cách gõ tay nếu caption nguồn còn sai.",
    },
    "caption": {
        "guide_id": "manual_caption_numbering",
        "title": "Sửa caption hình/bảng",
        "repair_scope": "paragraph",
        "difficulty": "medium",
        "estimated_minutes": 5,
        "not_auto_fix_reason": "Caption chứa số thứ tự và tiêu đề nội dung; hệ thống chỉ báo lỗi, không tự đổi chữ hoặc đánh số.",
        "steps": [
            "Đặt caption sát hình hoặc bảng tương ứng.",
            "Dùng References > Insert Caption để tạo caption đúng loại Hình/Bảng.",
            "Kiểm tra số chương trong caption có khớp chương hiện tại không.",
            "Sửa các caption bị rối như số quá sâu, thiếu dấu phân cách hoặc trùng số.",
        ],
        "verify": [
            "Caption có dạng 'Hình x.y. Tiêu đề' hoặc 'Bảng x.y. Tiêu đề' theo mẫu.",
            "Danh mục hình/bảng cập nhật đúng sau khi sửa caption.",
        ],
        "warning": "Không để backend tự sửa tiêu đề caption vì đó là nội dung mô tả của người dùng.",
    },
    "table": {
        "guide_id": "manual_table_layout",
        "title": "Sửa bảng biểu bị tràn hoặc khó đọc",
        "repair_scope": "table",
        "difficulty": "medium",
        "estimated_minutes": 6,
        "not_auto_fix_reason": "Bảng có thể cần đổi column width, xoay trang hoặc chuyển phụ lục; tự sửa có thể làm mất bố cục.",
        "steps": [
            "Chọn bảng và kiểm tra Table Layout > AutoFit hoặc chiều rộng từng cột.",
            "Nếu bảng quá rộng, cân nhắc đặt trong section ngang hoặc đưa sang phụ lục.",
            "Giữ font/cỡ chữ theo chuẩn, nhưng không ép bảng đến mức mất dữ liệu.",
        ],
        "verify": [
            "Bảng không vượt vùng nội dung khi xem bản PDF.",
            "Tiêu đề bảng và ghi chú bảng vẫn nằm gần bảng.",
        ],
        "warning": "Không dùng tool để xóa cột, xóa dòng hoặc viết lại nội dung bảng.",
    },
    "image_layout": {
        "guide_id": "manual_image_layout",
        "title": "Sửa bố cục ảnh/sơ đồ",
        "repair_scope": "image",
        "difficulty": "medium",
        "estimated_minutes": 5,
        "not_auto_fix_reason": "Ảnh có wrap, anchor và tỷ lệ riêng; tự sửa có thể làm ảnh che chữ hoặc nhảy trang.",
        "steps": [
            "Chọn ảnh và kiểm tra Picture Format > Wrap Text.",
            "Ưu tiên In Line with Text nếu mẫu trường yêu cầu ảnh đi cùng dòng nội dung.",
            "Giữ tỷ lệ ảnh khi thu nhỏ; không kéo méo ảnh.",
            "Đặt caption gần ảnh nếu ảnh nằm trong phần nội dung chính.",
        ],
        "verify": [
            "Ảnh không tràn lề và không che chữ trong bản PDF.",
            "Caption vẫn nằm gần ảnh sau khi cập nhật layout.",
        ],
        "warning": "Logo/trang bìa có thể có quy định riêng; chỉ sửa khi lỗi nằm trong nội dung chính.",
    },
    "character_density": {
        "guide_id": "manual_character_density",
        "title": "Sửa chữ bị nén, kéo giãn hoặc lệch spacing ký tự",
        "repair_scope": "paragraph",
        "difficulty": "easy",
        "estimated_minutes": 4,
        "not_auto_fix_reason": "Spacing ký tự có thể được dùng có chủ ý trong bìa hoặc heading; cần kiểm tra theo ngữ cảnh.",
        "steps": [
            "Chọn đoạn được báo lỗi và mở Font > Advanced.",
            "Đặt Scale về 100%, Spacing về Normal và Position về Normal nếu không có quy định khác.",
            "Áp dụng lại font Times New Roman và cỡ chữ theo template nếu cần.",
        ],
        "verify": [
            "Chữ không bị nén/kéo giãn bất thường.",
            "Khoảng cách ký tự đồng nhất với các đoạn cùng loại.",
        ],
        "warning": "Không dùng chức năng này để thay đổi nội dung chữ.",
    },
    "text_decoration": {
        "guide_id": "manual_text_decoration",
        "title": "Kiểm tra màu chữ, highlight và gạch chân lạ",
        "repair_scope": "paragraph",
        "difficulty": "easy",
        "estimated_minutes": 3,
        "not_auto_fix_reason": "Màu chữ/highlight/underline có thể là nội dung nhấn mạnh hợp lệ; cần người dùng xác nhận trước khi xóa.",
        "steps": [
            "Chọn đoạn được báo lỗi.",
            "Nếu màu chữ, highlight hoặc gạch chân không thuộc quy chuẩn, dùng Clear Formatting hoặc đặt lại style chuẩn.",
            "Giữ lại định dạng đặc biệt nếu đó là yêu cầu của mẫu trường hoặc ký hiệu chuyên ngành.",
        ],
        "verify": [
            "Không còn highlight/màu chữ lạ trong phần nội dung chính.",
            "Heading, hyperlink hoặc caption vẫn giữ định dạng hợp lệ nếu được phép.",
        ],
        "warning": "Không tự động xóa highlight vì có thể làm mất dấu review của người dùng.",
    },
    "equation_layout": {
        "guide_id": "manual_equation_layout",
        "title": "Kiểm tra công thức/ký hiệu",
        "repair_scope": "equation",
        "difficulty": "advanced",
        "estimated_minutes": 6,
        "not_auto_fix_reason": "Công thức có object và numbering riêng; tự sửa có thể làm hỏng công thức.",
        "steps": [
            "Mở đoạn có công thức và kiểm tra công thức có bị cắt trang hoặc lệch dòng không.",
            "Căn giữa công thức nếu quy định yêu cầu.",
            "Nếu có số công thức, đặt số ở vị trí nhất quán và không gõ dính vào công thức.",
        ],
        "verify": [
            "Công thức hiển thị đầy đủ trong Word/PDF.",
            "Số công thức, nếu có, nằm đúng vị trí và không bị tách dòng bất thường.",
        ],
        "warning": "Không chỉnh công thức bằng backend; hãy sửa trực tiếp trong Word Equation Editor.",
    },
    "scope_review": {
        "guide_id": "manual_scope_review",
        "title": "Kiểm tra cụm từ ngoài phạm vi đề tài",
        "repair_scope": "content_review",
        "difficulty": "advanced",
        "estimated_minutes": 10,
        "not_auto_fix_reason": "Đây là kiểm tra nội dung theo cấu hình riêng; hệ thống không được sửa câu chữ hoặc ý nghĩa.",
        "steps": [
            "Xem cụm từ được báo lỗi và đối chiếu với phạm vi đề tài của bạn.",
            "Nếu cụm từ thật sự ngoài phạm vi, tự chỉnh nội dung trong Word theo quyết định của bạn.",
            "Nếu cụm từ hợp lệ, bỏ qua cảnh báo hoặc cập nhật cấu hình forbidden_terms cho dự án.",
        ],
        "verify": [
            "Nội dung sau khi sửa vẫn đúng ý nghĩa và không bị tool tự viết lại.",
            "Danh sách term cấu hình chỉ chứa cụm từ của project hiện tại.",
        ],
        "warning": "Tool không spell-check và không viết lại nội dung.",
    },
    "layout_abnormal": {
        "guide_id": "manual_layout_abnormal",
        "title": "Sửa layout bất thường thủ công",
        "repair_scope": "document",
        "difficulty": "medium",
        "estimated_minutes": 6,
        "not_auto_fix_reason": "Layout bất thường thường liên quan page break, section break, tab, hyperlink hoặc comment; cần xem bằng mắt.",
        "steps": [
            "Bật ký tự ẩn trong Word bằng Home > ¶ để xem khoảng trắng, tab, page break và section break.",
            "Xóa khoảng trắng/tab thủ công nếu chúng được dùng để căn lề.",
            "Nếu cần sang trang, dùng Page Break hoặc Section Break đúng vị trí thay vì nhiều dòng trống.",
            "Xử lý comment hoặc Track Changes trong thẻ Review trước khi nộp.",
        ],
        "verify": [
            "Không còn nhiều dòng trống liên tiếp gây vỡ layout.",
            "File nộp không còn comment/Track Changes nếu quy định yêu cầu.",
            "Section break không làm sai số trang hoặc header/footer.",
        ],
        "warning": "Không tự accept/reject Track Changes trong backend vì có thể thay đổi nội dung.",
    },
    "render_verification": {
        "guide_id": "manual_render_verification",
        "title": "Kiểm tra lỗi chỉ thấy sau khi render PDF",
        "repair_scope": "rendered_page",
        "difficulty": "medium",
        "estimated_minutes": 8,
        "not_auto_fix_reason": "Lỗi render phụ thuộc engine hiển thị, trang trắng, tràn mép hoặc caption nhảy trang; cần đối chiếu bản PDF.",
        "steps": [
            "Mở file Word và xuất hoặc xem bản PDF.",
            "Đi tới trang được báo lỗi để kiểm tra trang trắng, nội dung sát mép hoặc caption tách khỏi hình/bảng.",
            "Sửa layout trong Word bằng page break, section break, kích thước bảng/ảnh hoặc Keep with next nếu cần.",
        ],
        "verify": [
            "Bản PDF không còn trang trắng ngoài chủ ý.",
            "Không có bảng/ảnh/text bị cắt mép.",
            "Caption nằm gần hình/bảng tương ứng.",
        ],
        "warning": "Render verification chỉ là cảnh báo thủ công, không phải lỗi auto-fix.",
    },
}


_EXACT_TEMPLATES: dict[str, dict[str, Any]] = {
    "TOC_MISSING": _GROUP_TEMPLATES["toc"],
    "TOC_NOT_AUTOMATIC": _GROUP_TEMPLATES["toc"],
    "PAGE_NUMBER_FOOTER": _GROUP_TEMPLATES["header_footer_page_number"],
    "PAGE_NUMBER_ALIGNMENT": _GROUP_TEMPLATES["header_footer_page_number"],
    "COVER_PAGE_NUMBER_VISIBLE": _GROUP_TEMPLATES["header_footer_page_number"],
    "ROMAN_PAGE_NUMBER_REPEATED": _GROUP_TEMPLATES["header_footer_page_number"],
    "MAIN_PAGE_NUMBER_FORMAT": _GROUP_TEMPLATES["header_footer_page_number"],
    "MAIN_PAGE_NUMBER_RESET": _GROUP_TEMPLATES["header_footer_page_number"],
    "FIGURE_NUMBERING_MALFORMED": _GROUP_TEMPLATES["caption"],
    "FIGURE_NUMBERING_DUPLICATE": _GROUP_TEMPLATES["caption"],
    "TABLE_NUMBERING_MALFORMED": _GROUP_TEMPLATES["caption"],
    "TABLE_NUMBERING_DUPLICATE": _GROUP_TEMPLATES["caption"],
    "SECTION_LANDSCAPE": {
        **_GROUP_TEMPLATES["header_footer_page_number"],
        "guide_id": "manual_section_orientation",
        "title": "Kiểm tra section hướng ngang",
        "repair_scope": "section",
        "not_auto_fix_reason": "Section ngang có thể hợp lệ cho phụ lục hoặc bảng lớn; cần người dùng xác nhận.",
        "steps": [
            "Đi tới section được báo lỗi và kiểm tra nội dung trong section đó.",
            "Nếu đó là bảng lớn hoặc phụ lục được phép xoay ngang, giữ nguyên.",
            "Nếu không hợp lệ, vào Layout > Orientation và chuyển section về Portrait.",
            "Kiểm tra lại header/footer và số trang sau khi đổi orientation.",
        ],
        "verify": [
            "Nội dung chính dùng hướng dọc.",
            "Bảng/phụ lục hướng ngang, nếu có, vẫn đúng section và số trang.",
        ],
        "warning": "Không đổi orientation tự động khi chưa biết section đó có phải phụ lục hợp lệ hay không.",
    },
}
