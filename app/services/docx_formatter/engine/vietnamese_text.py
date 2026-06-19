from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from app.services.docx_formatter.domain.finding import Finding


EXACT_REPLACEMENTS: dict[str, str] = {
    "JUSTIFY": "Căn đều hai bên",
    "LEFT": "Căn trái",
    "CENTER": "Căn giữa",
    "RIGHT": "Căn phải",
    "true": "Có",
    "false": "Không",
    "True": "Có",
    "False": "Không",
    "Dung": "Đúng",
    "Sai": "Sai",
    "Kiem tra dinh dang.": "Kiểm tra định dạng.",
    "Dong trong lien tiep": "Dòng trống liên tiếp",
    "Qua nhieu dong trong lien tiep": "Quá nhiều dòng trống liên tiếp",
    "Co nhieu dong trong lien tiep lam bo cuc co the bi vo.": "Có nhiều dòng trống liên tiếp làm bố cục có thể bị vỡ.",
    "Kiem tra cac dong trong thu cong; neu can xuong trang thi dung page break hoac section dung cach.": "Kiểm tra các dòng trống thủ công; nếu cần xuống trang thì dùng ngắt trang hoặc section đúng cách.",
    "Section dang de huong ngang": "Section đang để hướng ngang",
    "Section dang de huong ngang va can duoc kiem tra.": "Section đang để hướng ngang và cần được kiểm tra.",
    "Section dang de huong ngang can kiem tra.": "Section đang để hướng ngang cần kiểm tra.",
    "Huong doc cho noi dung chinh, tru khi phu luc/bang bieu duoc phep dung huong ngang.": "Hướng dọc cho nội dung chính, trừ khi phụ lục/bảng biểu được phép dùng hướng ngang.",
    "Kiem tra section nay co phai phu luc hoac bang ngang hop le khong; neu khong thi chuyen ve Portrait.": "Kiểm tra section này có phải phụ lục hoặc bảng ngang hợp lệ không; nếu không thì chuyển về Portrait.",
    "Kiem tra section nay co phai phu luc hoac bang ngang hop le khong; neu khong thi chuyen ve Portrait trong Word.": "Kiểm tra section này có phải phụ lục hoặc bảng ngang hợp lệ không; nếu không thì chuyển về Portrait trong Word.",
    "Huong trang ngang co the hop le voi phu luc hoac bang lon, can nguoi dung xac nhan.": "Hướng trang ngang có thể hợp lệ với phụ lục hoặc bảng lớn, cần người dùng xác nhận.",
    "Thieu muc luc": "Thiếu mục lục",
    "Muc luc chua phai field tu dong": "Mục lục chưa phải trường tự động",
    "Tai lieu co chuong nhung chua phat hien muc luc.": "Tài liệu có chương nhưng chưa phát hiện mục lục.",
    "Tai lieu nen co muc luc truoc phan noi dung chinh neu quy dinh yeu cau.": "Tài liệu nên có mục lục trước phần nội dung chính nếu quy định yêu cầu.",
    "Tao muc luc bang References > Table of Contents de Word cap nhat duoc so trang.": "Tạo mục lục bằng References > Table of Contents để Word cập nhật được số trang.",
    "Muc luc co the dang duoc go tay, chua phai TOC field tu dong.": "Mục lục có thể đang được gõ tay, chưa phải trường mục lục tự động.",
    "Muc luc nen duoc tao bang TOC field de cap nhat heading va so trang.": "Mục lục nên được tạo bằng trường mục lục tự động để cập nhật heading và số trang.",
    "Dung References > Table of Contents hoac Update Table trong Word thay vi go tay.": "Dùng chức năng tạo/cập nhật mục lục tự động trong Word thay vì gõ tay.",
    "Muc luc la field/cau truc Word phuc tap nen chi report, khong auto-fix.": "Mục lục là trường/cấu trúc Word phức tạp nên chỉ báo lỗi, không tự sửa.",
    "Can le bang dau cach/tab thu cong": "Căn lề bằng dấu cách/tab thủ công",
    "Doan van co dau hieu can le bang dau cach hoac tab thu cong.": "Đoạn văn có dấu hiệu căn lề bằng dấu cách hoặc tab thủ công.",
    "Can le va thut dau dong nen dung paragraph style, khong dung dau cach/tab thu cong.": "Căn lề và thụt đầu dòng nên dùng paragraph style, không dùng dấu cách/tab thủ công.",
    "Xoa can le thu cong neu co va ap dung lai style dinh dang phu hop trong Word.": "Xóa căn lề thủ công nếu có và áp dụng lại style định dạng phù hợp trong Word.",
    "Bullet/number co the dang go tay": "Bullet/number có thể đang gõ tay",
    "Dong danh sach co the dang dung dau bullet/so thu cong.": "Dòng danh sách có thể đang dùng dấu bullet/số thủ công.",
    "Bullet/number nen duoc tao bang Word list settings.": "Bullet/number nên được tạo bằng thiết lập danh sách của Word.",
    "Kiem tra lai list settings trong Word de tranh le bullet bi lech khi auto format.": "Kiểm tra lại thiết lập danh sách trong Word để tránh lề bullet bị lệch khi tự động định dạng.",
    "Ngat trang thu cong": "Ngắt trang thủ công",
    "Doan nay co page break thu cong.": "Đoạn này có page break thủ công.",
    "Ngat trang trong doan": "Ngắt trang trong đoạn",
    "Ngat trang chi nen dung tai vi tri tach trang co chu y.": "Ngắt trang chỉ nên dùng tại vị trí tách trang có chủ ý.",
    "Kiem tra page break thu cong; neu no lam sai danh so trang hoac bo cuc thi dieu chinh trong Word.": "Kiểm tra page break thủ công; nếu nó làm sai đánh số trang hoặc bố cục thì điều chỉnh trong Word.",
    "Ngat section": "Ngắt section",
    "Ngat section can kiem tra": "Ngắt section cần kiểm tra",
    "Doan nay co section break can kiem tra.": "Đoạn này có section break cần kiểm tra.",
    "Section break trong paragraph": "Section break trong paragraph",
    "Section break phai khop voi vung bia, phan dau, noi dung chinh va phu luc.": "Section break phải khớp với vùng bìa, phần đầu, nội dung chính và phụ lục.",
    "Kiem tra section break, footer va danh so trang quanh vi tri nay.": "Kiểm tra section break, footer và đánh số trang quanh vị trí này.",
    "Lien ket": "Liên kết",
    "Lien ket can kiem tra style": "Liên kết cần kiểm tra style",
    "Doan nay co hyperlink can kiem tra style.": "Đoạn này có hyperlink cần kiểm tra style.",
    "Lien ket neu duoc phep dung van phai theo style trinh bay cua tai lieu.": "Liên kết nếu được phép dùng vẫn phải theo style trình bày của tài liệu.",
    "Kiem tra mau chu, gach chan va tinh hop le cua hyperlink trong Word.": "Kiểm tra màu chữ, gạch chân và tính hợp lệ của hyperlink trong Word.",
    "Lich su sua": "Lịch sử sửa",
    "Lich su sua can kiem tra": "Lịch sử sửa cần kiểm tra",
    "Nhan xet/lich su sua": "Nhận xét/lịch sử sửa",
    "Nhan xet/lich su sua con trong file": "Nhận xét/lịch sử sửa còn trong file",
    "Tai lieu co dau vet comment hoac track changes can kiem tra.": "Tài liệu có dấu vết comment hoặc track changes cần kiểm tra.",
    "Tai lieu co track changes can kiem tra truoc khi nop.": "Tài liệu có track changes cần kiểm tra trước khi nộp.",
    "Tai lieu con comment hoac dau vet review can kiem tra.": "Tài liệu còn comment hoặc dấu vết review cần kiểm tra.",
    "Phat hien dau vet comment/track changes trong goi .docx": "Phát hiện dấu vết comment/track changes trong gói .docx",
    "File nop nen sach comment va track changes neu quy dinh yeu cau.": "File nộp nên sạch comment và track changes nếu quy định yêu cầu.",
    "Mo Word va kiem tra muc Theo doi thay doi truoc khi nop.": "Mở Word và kiểm tra mục Theo dõi thay đổi trước khi nộp.",
    "Mo Word va kiem tra muc Nhan xet/Theo doi thay doi truoc khi nop.": "Mở Word và kiểm tra mục Nhận xét/Theo dõi thay đổi trước khi nộp.",
    "Bang co the tran le": "Bảng có thể tràn lề",
    "Bang co the rong hon vung noi dung cua trang.": "Bảng có thể rộng hơn vùng nội dung của trang.",
    "Do rong bang": "Độ rộng bảng",
    "Khong vuot qua vung noi dung": "Không vượt quá vùng nội dung",
    "Khong vuot qua vùng nội dung": "Không vượt quá vùng nội dung",
    "Kiem tra lai do rong bang, co the can chinh column width hoac dua bang lon sang phu luc/section ngang.": "Kiểm tra lại độ rộng bảng, có thể cần chỉnh column width hoặc đưa bảng lớn sang phụ lục/section ngang.",
    "Kiem tra do rong bang, column width hoac dua bang lon sang phu luc/section ngang.": "Kiểm tra độ rộng bảng, column width hoặc đưa bảng lớn sang phụ lục/section ngang.",
    "Kich thuoc anh/so do": "Kích thước ảnh/sơ đồ",
    "Kieu boc chu quanh anh/so do": "Kiểu bọc chữ quanh ảnh/sơ đồ",
    "Kieu boc chu quanh anh/so do can kiem tra": "Kiểu bọc chữ quanh ảnh/sơ đồ cần kiểm tra",
    "Anh/so do dang dung floating hoac wrap text can kiem tra.": "Ảnh/sơ đồ đang dùng floating hoặc wrap text cần kiểm tra.",
    "Anh dang dung kieu floating/wrap text": "Ảnh đang dùng kiểu floating/wrap text",
    "Anh trong noi dung nen co wrapping nhat quan va khong che len chu.": "Ảnh trong nội dung nên có wrapping nhất quán và không che lên chữ.",
    "Kiem tra tuy chon bo cuc cua anh; uu tien dat anh nam cung dong voi chu neu mau truong yeu cau.": "Kiểm tra tùy chọn bố cục của ảnh; ưu tiên đặt ảnh nằm cùng dòng với chữ nếu mẫu trường yêu cầu.",
    "Anh/so do co the tran le": "Ảnh/sơ đồ có thể tràn lề",
    "Anh/so do co the rong hon vung noi dung.": "Ảnh/sơ đồ có thể rộng hơn vùng nội dung.",
    "Kiem tra kich thuoc anh/so do va thu nho neu anh tran le.": "Kiểm tra kích thước ảnh/sơ đồ và thu nhỏ nếu ảnh tràn lề.",
    "Header/footer chua dung font chu.": "Header/footer chưa đúng font chữ.",
    "Header/footer chua dung co chu.": "Header/footer chưa đúng cỡ chữ.",
    "Font chu header/footer": "Font chữ header/footer",
    "Co chu header/footer": "Cỡ chữ header/footer",
    "Kiem tra style header/footer theo mau truong.": "Kiểm tra style header/footer theo mẫu trường.",
    "Kiem tra co chu header/footer theo mau truong.": "Kiểm tra cỡ chữ header/footer theo mẫu trường.",
    "Document appears to exceed the expected page count.": "Tài liệu có dấu hiệu vượt quá số trang quy định.",
    "Document appears shorter than the expected page count.": "Tài liệu có dấu hiệu ngắn hơn số trang quy định.",
    "Page number appears to be merged into document body text.": "Số trang có dấu hiệu bị dính vào nội dung văn bản.",
    "Page numbers should be in the footer, not merged into body text.": "Số trang nên nằm trong footer, không dính vào nội dung văn bản.",
    "Review this location manually and move page numbering back to the footer if it was converted into normal text.": "Kiểm tra thủ công vị trí này và đưa số trang về footer nếu nó bị chuyển thành chữ thường.",
    "Chapter number and chapter title are on the same paragraph.": "Số chương và tiêu đề chương đang nằm cùng một đoạn.",
    "Chapter number label should use the standard format.": "Dòng số chương chưa đúng mẫu chuẩn.",
    "Chapter number line is not centered.": "Dòng số chương chưa được căn giữa.",
    "Chapter number line is not bold.": "Dòng số chương chưa in đậm.",
    "Chapter title line is missing after chapter number.": "Thiếu dòng tiêu đề chương ngay sau dòng số chương.",
    "Chapter title is not uppercase.": "Tiêu đề chương chưa viết hoa.",
    "Chapter title is not centered.": "Tiêu đề chương chưa được căn giữa.",
    "Chapter title is not bold.": "Tiêu đề chương chưa in đậm.",
}

PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("dong trong lien tiep", "dòng trống liên tiếp"),
    ("Dong trong lien tiep", "Dòng trống liên tiếp"),
    ("Khong qua", "Không quá"),
    ("Khong vuot qua", "Không vượt quá"),
    ("trong phan noi dung", "trong phần nội dung"),
    ("phan noi dung", "phần nội dung"),
    ("bo cuc", "bố cục"),
    ("can kiem tra", "cần kiểm tra"),
    ("thu cong", "thủ công"),
    ("dung cach", "đúng cách"),
    ("danh so trang", "đánh số trang"),
    ("vi tri", "vị trí"),
    ("noi dung", "nội dung"),
    ("phu luc", "phụ lục"),
    ("bang bieu", "bảng biểu"),
    ("mau truong", "mẫu trường"),
    ("co chu", "cỡ chữ"),
    ("font chu", "font chữ"),
    ("huong ngang", "hướng ngang"),
    ("huong doc", "hướng dọc"),
    ("vung", "vùng"),
    ("dot leader", "dấu chấm dẫn"),
    ("Dot leader", "Dấu chấm dẫn"),
    ("field tu dong", "field tự động"),
    ("field tự động", "trường tự động"),
    ("anh/so do", "ảnh/sơ đồ"),
    ("Anh/so do", "Ảnh/sơ đồ"),
    ("tran le", "tràn lề"),
    ("page break", "ngắt trang"),
    ("body text", "nội dung văn bản"),
    ("Different First Page", "tùy chọn trang đầu khác biệt"),
    ("Page Number Format", "định dạng số trang"),
    ("Start at", "bắt đầu từ"),
    ("style", "kiểu định dạng"),
    ("Style", "Kiểu định dạng"),
)


def normalize_vietnamese_display(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return text

    exact = EXACT_REPLACEMENTS.get(text)
    if exact is not None:
        return exact

    normalized = text
    normalized = re.sub(
        r"\b(\d+)\s+dong trong lien tiep\b",
        lambda match: f"{match.group(1)} dòng trống liên tiếp",
        normalized,
    )
    normalized = re.sub(
        r"\b(\d+)\s+dòng trống liên tiếp\b",
        lambda match: f"{match.group(1)} dòng trống liên tiếp",
        normalized,
    )
    normalized = re.sub(
        r"^(\d+)\s+pages$",
        lambda match: f"{match.group(1)} trang",
        normalized,
    )
    normalized = re.sub(
        r"^(\d+)\s+page$",
        lambda match: f"{match.group(1)} trang",
        normalized,
    )
    normalized = re.sub(
        r"^(\d+)-(\d+)\s+pages,\s*excluding appendix$",
        lambda match: f"{match.group(1)}-{match.group(2)} trang, không kể phụ lục",
        normalized,
    )
    normalized = re.sub(
        r"^(CHƯƠNG\s+\d+\.)\s+on one centered line;\s*title on the next centered uppercase line\.$",
        lambda match: f'Dòng "{match.group(1)}" căn giữa; tiêu đề chương ở dòng ngay dưới, viết hoa và căn giữa.',
        normalized,
    )
    normalized = re.sub(
        r"^(CHUONG\s+\d+\.)\s+on one centered line;\s*title on the next centered uppercase line\.$",
        lambda match: f'Dòng "{match.group(1).replace("CHUONG", "CHƯƠNG")}" căn giữa; tiêu đề chương ở dòng ngay dưới, viết hoa và căn giữa.',
        normalized,
    )
    for old, new in PHRASE_REPLACEMENTS:
        normalized = normalized.replace(old, new)

    return EXACT_REPLACEMENTS.get(normalized, normalized)


def normalize_vietnamese_optional(value: Any) -> str | None:
    if value is None:
        return None
    normalized = normalize_vietnamese_display(value)
    return normalized or None


def normalize_vietnamese_finding(finding: Finding) -> Finding:
    metadata = _normalize_metadata(finding.metadata)
    return replace(
        finding,
        message=normalize_vietnamese_display(finding.message),
        current_value=normalize_vietnamese_optional(finding.current_value),
        expected_value=normalize_vietnamese_optional(finding.expected_value),
        suggestion=normalize_vietnamese_optional(finding.suggestion),
        metadata=metadata,
    )


def normalize_vietnamese_finding_dict(finding: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(finding)
    for key in ("message", "current_value", "expected_value", "suggestion"):
        if key in normalized:
            normalized[key] = normalize_vietnamese_optional(normalized[key])
    metadata = normalized.get("metadata")
    if isinstance(metadata, dict):
        normalized["metadata"] = _normalize_metadata(metadata)
    return normalized


def normalize_fix_action(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    for key in ("reason", "message", "label", "suggestion"):
        if key in normalized and normalized[key] is not None:
            normalized[key] = normalize_vietnamese_display(normalized[key])
    return normalized


def _normalize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(metadata)
    if "fix_action" in normalized:
        normalized["fix_action"] = normalize_fix_action(normalized["fix_action"])
    if "text_preview" in normalized and normalized["text_preview"] is not None:
        normalized["text_preview"] = normalize_vietnamese_display(normalized["text_preview"])
    return normalized
