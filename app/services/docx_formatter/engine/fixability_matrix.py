from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from app.services.docx_formatter.domain.finding import Finding

FixabilityScope = Literal["safe_auto_fix", "manual_review"]

SAFE_ACTION_REASON = "Lỗi này chỉ thay đổi định dạng Word an toàn, có thể tự sửa."
MANUAL_ACTION_REASON = (
    "Lỗi này có thể ảnh hưởng bố cục, cấu trúc hoặc nội dung hiển thị; cần kiểm tra thủ công."
)
REVIEW_ACTION_REASON = "Rule này chỉ dùng để cảnh báo/review, không tự sửa."

SAFE_EXACT_TYPES = {
    "PAGE_MARGIN_ERROR",
    "PAPER_SIZE_ERROR",
    "HEADER_FOOTER_FONT_NAME_ERROR",
    "HEADER_FOOTER_FONT_SIZE_ERROR",
    "TABLE_CELL_FONT_NAME_ERROR",
    "TABLE_CELL_FONT_SIZE_ERROR",
}

SAFE_PREFIXES = (
    "FRONT_MATTER_HEADING_",
    "PARAGRAPH_",
    "HEADING_",
    "LIST_ITEM_",
    "CAPTION_",
)

SAFE_GROUP_IDS = {
    "page_setup",
    "body_paragraph",
    "front_matter",
    "heading",
    "list_item",
    "caption",
    "table_cell_format",
    "header_footer_format",
}

MANUAL_GROUP_IDS = {
    "chapter_layout",
    "cover_layout",
    "document_length",
    "front_matter",
    "header_footer_page_number",
    "image_layout",
    "layout_abnormal",
    "list_of_figures",
    "list_of_tables",
    "references",
    "render_verification",
    "scope_review",
    "table",
    "toc",
    "character_density",
    "text_decoration",
    "equation_layout",
}


@dataclass(frozen=True)
class FixabilitySpec:
    scope: FixabilityScope
    auto_fixable: bool
    manual_review: bool
    fix_action: dict[str, Any]
    reason: str


def classify_fixability(
    finding_type: str,
    *,
    metadata: dict[str, Any] | None = None,
    group_id: str | None = None,
) -> FixabilitySpec:
    metadata = metadata if isinstance(metadata, dict) else {}
    normalized_type = str(finding_type or "").strip().upper()
    normalized_group = str(group_id or metadata.get("report_group_id") or "").strip()

    if _is_safe_auto_fix(normalized_type, normalized_group):
        return _safe_spec(metadata)

    if _is_forced_manual_review(normalized_type, normalized_group):
        return _manual_spec(_manual_reason(normalized_type, normalized_group))

    return _manual_spec(_manual_reason(normalized_type, normalized_group))


def apply_fixability_to_finding(finding: Finding) -> Finding:
    metadata = finding.metadata if isinstance(finding.metadata, dict) else {}
    spec = classify_fixability(
        finding.type,
        metadata=metadata,
        group_id=str(metadata.get("report_group_id") or ""),
    )
    normalized_metadata = {
        **metadata,
        "auto_fixable": spec.auto_fixable,
        "manual_review": spec.manual_review,
        "fix_action": spec.fix_action,
        "fixability_scope": spec.scope,
        "fixability_reason": spec.reason,
    }
    return replace(finding, metadata=normalized_metadata)


def apply_fixability_to_findings(findings: list[Finding]) -> list[Finding]:
    return [apply_fixability_to_finding(finding) for finding in findings]


def _is_forced_manual_review(finding_type: str, group_id: str) -> bool:
    if finding_type.endswith("_REVIEW"):
        return True
    if group_id in MANUAL_GROUP_IDS:
        return True
    if finding_type.startswith(("HEADER_FOOTER_", "TABLE_CELL_", "FIGURE_", "TABLE_")):
        return True
    return False


def _is_safe_auto_fix(finding_type: str, group_id: str) -> bool:
    if finding_type in SAFE_EXACT_TYPES:
        return True
    if not finding_type.endswith("_ERROR"):
        return False
    if group_id and group_id not in SAFE_GROUP_IDS:
        return False
    return finding_type.startswith(SAFE_PREFIXES)


def _safe_spec(metadata: dict[str, Any]) -> FixabilitySpec:
    existing_action = metadata.get("fix_action")
    if isinstance(existing_action, dict) and existing_action.get("type") != "manual_review":
        fix_action = dict(existing_action)
        fix_action.setdefault("reason", SAFE_ACTION_REASON)
    else:
        fix_action = {
            "type": "safe_format_fix",
            "reason": SAFE_ACTION_REASON,
        }
    return FixabilitySpec(
        scope="safe_auto_fix",
        auto_fixable=True,
        manual_review=False,
        fix_action=fix_action,
        reason=SAFE_ACTION_REASON,
    )


def _manual_spec(reason: str) -> FixabilitySpec:
    return FixabilitySpec(
        scope="manual_review",
        auto_fixable=False,
        manual_review=True,
        fix_action={
            "type": "manual_review",
            "reason": reason,
        },
        reason=reason,
    )


def _manual_reason(finding_type: str, group_id: str) -> str:
    if finding_type.endswith("_REVIEW"):
        return REVIEW_ACTION_REASON
    if group_id in MANUAL_GROUP_IDS:
        return MANUAL_ACTION_REASON
    return MANUAL_ACTION_REASON
