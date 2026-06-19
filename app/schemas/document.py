from typing import Any, Literal

from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    document_id: str
    status: str
    original_filename: str


class DocumentListItem(BaseModel):
    document_id: str
    document_type: str
    original_filename: str
    status: str
    total_findings: int = 0
    error_count: int = 0
    warning_count: int = 0
    created_at: str
    annotated_at: str | None = None
    fixed_at: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentListItem] = Field(default_factory=list)


class DocumentFinding(BaseModel):
    type: str
    severity: str
    location: str | None = None
    message: str
    current_value: str | None = None
    expected_value: str | None = None
    suggestion: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentAnalyzeResponse(BaseModel):
    ok: bool = True
    message: str = "Phân tích định dạng hoàn tất."
    document_id: str
    status: str
    total_findings: int
    error_count: int
    warning_count: int
    report_file_key: str | None = None
    findings: list[DocumentFinding]
    document: dict[str, Any] = Field(default_factory=dict)
    reference: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    issue_groups: list[dict[str, Any]] = Field(default_factory=list)
    manual_repair_guidance: list[dict[str, Any]] = Field(default_factory=list)
    preview_comments: list[dict[str, Any]] = Field(default_factory=list)
    render_verification: dict[str, Any] = Field(default_factory=dict)


class DocumentFixRequest(BaseModel):
    fix_mode: Literal["safe_all", "safe_scope"] = "safe_all"
    fix_scope: list[str] = Field(default_factory=list)


class DocumentFixResponse(BaseModel):
    document_id: str
    status: str
    fixed_file_key: str
    style_changes: int = 0
    page_setup_changes: int
    front_matter_heading_changes: int = 0
    list_item_changes: int = 0
    caption_changes: int = 0
    table_cell_changes: int = 0
    header_footer_changes: int = 0
    paragraph_changes: int
    heading_changes: int
    total_changes: int
    fix_mode: str = "safe_all"
    applied_fix_scope: list[str] = Field(default_factory=list)
    available_fix_scope: list[dict[str, Any]] = Field(default_factory=list)
    style_fix_mode: str = "conservative_exclusive_style"
    style_fix_groups_applied: int = 0
    style_changes_by_style: list[dict[str, Any]] = Field(default_factory=list)
    style_fix_skipped: list[dict[str, Any]] = Field(default_factory=list)
    safe_fix_rules: list[str] = Field(default_factory=list)
    skipped_safe_fix_rules: list[str] = Field(default_factory=list)
    blocked_fix_rules: list[str] = Field(default_factory=list)
    safe_fix_scope: list[str] = Field(default_factory=list)
    changes_by_rule: dict[str, int] = Field(default_factory=dict)
    safety_checks: dict[str, bool] = Field(default_factory=dict)
    cleanup_report: dict[str, dict[str, int]] = Field(default_factory=dict)
    post_fix_validation: dict[str, Any] = Field(default_factory=dict)


class DocumentDownloadTokenResponse(BaseModel):
    document_id: str
    token: str
    expires_at: str
    download_url: str


class DocumentAnnotatedReportResponse(BaseModel):
    document_id: str
    status: str
    annotated_file_key: str
    comment_mode: str = "hybrid"
    comment_strategy: str = "hybrid"
    comment_count: int
    grouped_findings_in_comments: int = 0
    skipped_count: int
    total_findings: int = 0
    total_comments_created: int = 0
    skipped_comments: int = 0
    skipped_findings: int = 0
    skipped_reason: list[dict[str, Any]] = Field(default_factory=list)
    comment_note: str | None = None
    download_url: str | None = None
    annotated_report_file_key: str | None = None


class DocumentAnnotateResponse(DocumentAnnotatedReportResponse):
    pass
