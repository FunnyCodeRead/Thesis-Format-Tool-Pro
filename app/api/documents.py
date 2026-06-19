import hashlib
import json
import re
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.security import get_current_user
from app.db.supabase_client import SupabaseAPIError, get_supabase_rest_client
from app.schemas.auth import CurrentUser
from app.schemas.document import (
    DocumentAnalyzeResponse,
    DocumentAnnotateResponse,
    DocumentDownloadTokenResponse,
    DocumentFixResponse,
    DocumentFixRequest,
    DocumentListItem,
    DocumentListResponse,
    DocumentUploadResponse,
)
from app.services.docx_formatter.analyzer import (
    AnalyzerConfigError,
    DocumentAnalysisError,
    analyze_document_with_details as analyze_docx_document,
)
from app.services.docx_formatter.annotator import (
    DocumentAnnotationError,
    annotate_document as annotate_docx_document,
)
from app.services.docx_formatter.fixer import (
    DocumentFixError,
    fix_document as fix_docx_document,
)
from app.services.docx_formatter.engine.preview_comment_builder import (
    build_preview_comments_from_report,
)
from app.services.docx_formatter.engine.report_builder import ReportBuilder
from app.services.storage.r2_storage import (
    DOCX_MIME_TYPE,
    JSON_MIME_TYPE,
    R2StorageError,
    build_annotated_document_key,
    build_fixed_document_key,
    build_original_document_key,
    build_report_document_key,
    get_r2_storage_client,
)
from app.services.wallets import purchase_document_with_wallet
from app.utils.file_validation import read_and_validate_docx_upload

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

DOWNLOAD_KIND_FIXED = "fixed"
DOWNLOAD_KIND_ANNOTATED = "annotated"


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    *,
    limit: int = Query(default=20, ge=1, le=50),
    current_user: CurrentUser = Depends(get_current_user),
) -> DocumentListResponse:
    try:
        rows = get_supabase_rest_client().select_many(
            "documents",
            filters={"user_id": current_user.user_id},
            columns=(
                "id,document_type,original_filename,status,total_findings,error_count,"
                "warning_count,created_at,annotated_at,fixed_at"
            ),
            order="created_at.desc",
            limit=limit,
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return DocumentListResponse(
        documents=[
            DocumentListItem(
                document_id=row["id"],
                document_type=row["document_type"],
                original_filename=row["original_filename"],
                status=row["status"],
                total_findings=int(row.get("total_findings") or 0),
                error_count=int(row.get("error_count") or 0),
                warning_count=int(row.get("warning_count") or 0),
                created_at=row["created_at"],
                annotated_at=row.get("annotated_at"),
                fixed_at=row.get("fixed_at"),
            )
            for row in rows
        ]
    )


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    *,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> DocumentUploadResponse:
    normalized_document_type = document_type.strip()
    if not normalized_document_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="document_type is required.",
        )

    original_filename, content = await read_and_validate_docx_upload(
        file,
        max_upload_size_bytes=settings.max_upload_size_bytes,
    )

    try:
        supabase = get_supabase_rest_client()
        template = supabase.select_one(
            "document_templates",
            filters={"key": normalized_document_type, "is_active": "true"},
            columns="key,name,price_vnd",
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if template is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown or inactive document_type.",
        )

    document_id = str(uuid4())
    original_file_key = build_original_document_key(current_user.user_id, document_id)

    try:
        r2_storage = get_r2_storage_client()
        r2_storage.upload_bytes(
            object_key=original_file_key,
            content=content,
            content_type=DOCX_MIME_TYPE,
        )
    except R2StorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    try:
        inserted = supabase.insert_one(
            "documents",
            payload={
                "id": document_id,
                "user_id": current_user.user_id,
                "document_type": normalized_document_type,
                "original_filename": original_filename,
                "original_file_key": original_file_key,
                "status": "uploaded",
            },
            columns="id,status,original_filename",
        )
    except SupabaseAPIError as exc:
        try:
            r2_storage.delete_object(original_file_key)
        except R2StorageError:
            pass
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return DocumentUploadResponse(
        document_id=inserted["id"],
        status=inserted["status"],
        original_filename=inserted["original_filename"],
    )


@router.post("/{document_id}/analyze", response_model=DocumentAnalyzeResponse)
async def analyze_document(
    *,
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> DocumentAnalyzeResponse:
    document_id = str(document_id)
    try:
        supabase = get_supabase_rest_client()
        document = supabase.select_one(
            "documents",
            filters={"id": document_id, "user_id": current_user.user_id},
            columns="id,user_id,document_type,original_file_key,status,original_filename",
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    if document["status"] not in {"uploaded", "analyzed", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document cannot be analyzed from status {document['status']}.",
        )

    try:
        r2_storage = get_r2_storage_client()
        original_content = r2_storage.download_bytes(document["original_file_key"])
    except R2StorageError as exc:
        _mark_document_failed(supabase, document_id, current_user.user_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    try:
        template = _get_document_template_or_fallback(supabase, document["document_type"])
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    temp_path = _write_temp_docx(original_content)
    try:
        analysis = analyze_docx_document(
            str(temp_path),
            document["document_type"],
            config_override=template.get("config_json"),
        )
    except AnalyzerConfigError as exc:
        _mark_document_failed(supabase, document_id, current_user.user_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DocumentAnalysisError as exc:
        _mark_document_failed(supabase, document_id, current_user.user_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)

    raw_findings = analysis["raw_findings"]
    grouped_findings = analysis["findings"]
    render_verification = analysis.get("render_verification", {})

    error_count = sum(1 for finding in raw_findings if finding["severity"] == "error")
    warning_count = sum(1 for finding in raw_findings if finding["severity"] == "warning")
    report_file_key = build_report_document_key(current_user.user_id, document_id)
    generated_at = datetime.now(timezone.utc).isoformat()
    production_report = ReportBuilder().build(
        raw_findings=raw_findings,
        document_id=document_id,
        document_type=document["document_type"],
        filename=document.get("original_filename"),
        template_name=template.get("name") or document["document_type"],
        generated_at=generated_at,
    )
    production_report["reference"]["config_source"] = template.get("config_source", "local")
    preview_comments = build_preview_comments_from_report(production_report)

    report_payload = {
        **production_report,
        "document_id": document_id,
        "document_type": document["document_type"],
        "generated_at": generated_at,
        "total_findings": len(raw_findings),
        "error_count": error_count,
        "warning_count": warning_count,
        "findings": grouped_findings,
        "manual_repair_guidance": production_report.get("manual_repair_guidance", []),
        "preview_comments": preview_comments,
        "render_verification": render_verification,
    }

    try:
        r2_storage.upload_bytes(
            object_key=report_file_key,
            content=json.dumps(report_payload, ensure_ascii=False).encode("utf-8"),
            content_type=JSON_MIME_TYPE,
        )
        supabase.delete_many("findings", filters={"document_id": document_id})
        supabase.insert_many("findings", payloads=_build_finding_rows(document_id, raw_findings))
        updated_document = supabase.update_one(
            "documents",
            filters={"id": document_id, "user_id": current_user.user_id},
            payload={
                "status": "analyzed",
                "total_findings": len(raw_findings),
                "error_count": error_count,
                "warning_count": warning_count,
                "report_file_key": report_file_key,
                "last_analyzed_at": generated_at,
                "annotated_file_key": None,
                "annotated_at": None,
            },
            columns="id,status,total_findings,error_count,warning_count,report_file_key",
        )
    except R2StorageError as exc:
        _mark_document_failed(supabase, document_id, current_user.user_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return DocumentAnalyzeResponse(
        document_id=updated_document["id"],
        status=updated_document["status"],
        total_findings=updated_document["total_findings"],
        error_count=updated_document["error_count"],
        warning_count=updated_document["warning_count"],
        report_file_key=updated_document.get("report_file_key"),
        findings=grouped_findings,
        document=production_report["document"],
        reference=production_report["reference"],
        summary=production_report["summary"],
        issue_groups=production_report["issue_groups"],
        manual_repair_guidance=production_report.get("manual_repair_guidance", []),
        preview_comments=preview_comments,
        render_verification=render_verification,
    )


@router.post("/{document_id}/annotate", response_model=DocumentAnnotateResponse)
async def annotate_document(
    *,
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> DocumentAnnotateResponse:
    return _create_annotated_document_response(
        document_id=str(document_id),
        current_user=current_user,
    )


@router.post("/{document_id}/annotated-report", response_model=DocumentAnnotateResponse)
async def create_annotated_report_alias(
    *,
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> DocumentAnnotateResponse:
    return _create_annotated_document_response(
        document_id=str(document_id),
        current_user=current_user,
    )


@router.post("/{document_id}/fix", response_model=DocumentFixResponse)
async def fix_document(
    *,
    document_id: UUID,
    fix_request: DocumentFixRequest | None = Body(default=None),
    current_user: CurrentUser = Depends(get_current_user),
) -> DocumentFixResponse:
    document_id = str(document_id)
    try:
        supabase = get_supabase_rest_client()
        document = supabase.select_one(
            "documents",
            filters={"id": document_id, "user_id": current_user.user_id},
            columns="id,user_id,document_type,original_file_key,status",
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    if document["status"] not in {"uploaded", "analyzed", "pending_payment", "paid", "fixed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document cannot be fixed from status {document['status']}.",
        )

    try:
        r2_storage = get_r2_storage_client()
        original_content = r2_storage.download_bytes(document["original_file_key"])
    except R2StorageError as exc:
        _mark_document_failed(supabase, document_id, current_user.user_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    try:
        template = _get_document_template_or_fallback(supabase, document["document_type"])
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    input_path = _write_temp_docx(original_content)
    output_path = _create_temp_docx_path()
    try:
        fix_result = fix_docx_document(
            str(input_path),
            document["document_type"],
            str(output_path),
            config_override=template.get("config_json"),
            fix_options=fix_request.model_dump() if fix_request is not None else None,
        )
        fixed_content = output_path.read_bytes()
    except AnalyzerConfigError as exc:
        _mark_document_failed(supabase, document_id, current_user.user_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DocumentFixError as exc:
        _mark_document_failed(supabase, document_id, current_user.user_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)

    fixed_file_key = build_fixed_document_key(current_user.user_id, document_id)
    fixed_at = datetime.now(timezone.utc).isoformat()

    try:
        r2_storage.upload_bytes(
            object_key=fixed_file_key,
            content=fixed_content,
            content_type=DOCX_MIME_TYPE,
        )
        updated_document = supabase.update_one(
            "documents",
            filters={"id": document_id, "user_id": current_user.user_id},
            payload={
                "status": "fixed",
                "fixed_file_key": fixed_file_key,
                "fixed_at": fixed_at,
                "last_fixed_at": fixed_at,
            },
            columns="id,status,fixed_file_key",
        )
    except R2StorageError as exc:
        _mark_document_failed(supabase, document_id, current_user.user_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except SupabaseAPIError as exc:
        try:
            r2_storage.delete_object(fixed_file_key)
        except R2StorageError:
            pass
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return DocumentFixResponse(
        document_id=updated_document["id"],
        status=updated_document["status"],
        fixed_file_key=updated_document["fixed_file_key"],
        style_changes=fix_result.get("style_changes", 0),
        page_setup_changes=fix_result["page_setup_changes"],
        front_matter_heading_changes=fix_result.get("front_matter_heading_changes", 0),
        list_item_changes=fix_result.get("list_item_changes", 0),
        caption_changes=fix_result.get("caption_changes", 0),
        table_cell_changes=fix_result.get("table_cell_changes", 0),
        header_footer_changes=fix_result.get("header_footer_changes", 0),
        paragraph_changes=fix_result["paragraph_changes"],
        heading_changes=fix_result["heading_changes"],
        total_changes=fix_result["total_changes"],
        fix_mode=fix_result.get("fix_mode", "safe_all"),
        applied_fix_scope=fix_result.get("applied_fix_scope", []),
        available_fix_scope=fix_result.get("available_fix_scope", []),
        style_fix_mode=fix_result.get("style_fix_mode", "conservative_exclusive_style"),
        style_fix_groups_applied=fix_result.get("style_fix_groups_applied", 0),
        style_changes_by_style=fix_result.get("style_changes_by_style", []),
        style_fix_skipped=fix_result.get("style_fix_skipped", []),
        safe_fix_rules=fix_result.get("safe_fix_rules", []),
        skipped_safe_fix_rules=fix_result.get("skipped_safe_fix_rules", []),
        blocked_fix_rules=fix_result.get("blocked_fix_rules", []),
        safe_fix_scope=fix_result.get("safe_fix_scope", []),
        changes_by_rule=fix_result.get("changes_by_rule", {}),
        safety_checks=fix_result.get("safety_checks", {}),
        cleanup_report=fix_result.get("cleanup_report", {}),
        post_fix_validation=fix_result.get("post_fix_validation", {}),
    )


@router.post("/{document_id}/download-token", response_model=DocumentDownloadTokenResponse)
async def create_download_token(
    *,
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> DocumentDownloadTokenResponse | JSONResponse:
    document_id = str(document_id)
    try:
        supabase = get_supabase_rest_client()
        document = _get_owned_document_for_download(
            supabase,
            document_id=document_id,
            user_id=current_user.user_id,
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    _ensure_document_is_downloadable(document)

    try:
        purchase_result = purchase_document_with_wallet(
            supabase,
            document_id=document_id,
            user_id=current_user.user_id,
        )
        if not purchase_result.get("ok"):
            return _wallet_purchase_error_response(document_id, purchase_result)

        return _create_download_token_response(
            supabase,
            document_id=document_id,
            user_id=current_user.user_id,
            kind=DOWNLOAD_KIND_FIXED,
            download_path=f"/api/v1/documents/{document_id}/download",
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{document_id}/annotated-download-token", response_model=DocumentDownloadTokenResponse)
async def create_annotated_download_token(
    *,
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> DocumentDownloadTokenResponse:
    document_id = str(document_id)
    try:
        supabase = get_supabase_rest_client()
        document = _get_owned_document_for_annotation_download(
            supabase,
            document_id=document_id,
            user_id=current_user.user_id,
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    _ensure_annotated_document_is_downloadable(document)

    try:
        return _create_download_token_response(
            supabase,
            document_id=document_id,
            user_id=current_user.user_id,
            kind=DOWNLOAD_KIND_ANNOTATED,
            download_path=f"/api/v1/documents/{document_id}/annotated-download",
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{document_id}/download")
async def download_fixed_document(
    *,
    document_id: UUID,
    token: str = Query(..., min_length=16),
    current_user: CurrentUser = Depends(get_current_user),
) -> Response:
    document_id = str(document_id)
    token_hash = _hash_download_token(token)
    now = datetime.now(timezone.utc)

    try:
        supabase = get_supabase_rest_client()
        document = _get_owned_document_for_download(
            supabase,
            document_id=document_id,
            user_id=current_user.user_id,
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    _ensure_document_is_downloadable(document)

    try:
        _ensure_fixed_file_payment_allowed(
            supabase,
            document_id=document_id,
            user_id=current_user.user_id,
            error_detail="A paid order is required before downloading this document.",
        )
        token_row = _get_download_token(
            supabase,
            document_id=document_id,
            user_id=current_user.user_id,
            token_hash=token_hash,
            kind=DOWNLOAD_KIND_FIXED,
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    _ensure_token_is_valid(token_row, now)

    try:
        r2_storage = get_r2_storage_client()
        fixed_content = r2_storage.download_bytes(document["fixed_file_key"])
    except R2StorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    used_at = datetime.now(timezone.utc)
    try:
        _consume_download_token(
            supabase,
            token_row=token_row,
            user_id=current_user.user_id,
            used_at=used_at,
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    try:
        supabase.update_one(
            "documents",
            filters={"id": document_id, "user_id": current_user.user_id},
            payload={"status": "downloaded"},
            columns="id,status",
        )
    except SupabaseAPIError:
        pass

    filename = _build_fixed_download_filename(document.get("original_filename"))
    return Response(
        content=fixed_content,
        media_type=DOCX_MIME_TYPE,
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.get("/{document_id}/annotated-download")
async def download_annotated_document(
    *,
    document_id: UUID,
    token: str = Query(..., min_length=16),
    current_user: CurrentUser = Depends(get_current_user),
) -> Response:
    document_id = str(document_id)
    token_hash = _hash_download_token(token)
    now = datetime.now(timezone.utc)

    try:
        supabase = get_supabase_rest_client()
        document = _get_owned_document_for_annotation_download(
            supabase,
            document_id=document_id,
            user_id=current_user.user_id,
        )
        token_row = _get_download_token(
            supabase,
            document_id=document_id,
            user_id=current_user.user_id,
            token_hash=token_hash,
            kind=DOWNLOAD_KIND_ANNOTATED,
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    _ensure_annotated_document_is_downloadable(document)
    _ensure_token_is_valid(token_row, now)

    try:
        r2_storage = get_r2_storage_client()
        annotated_content = r2_storage.download_bytes(document["annotated_file_key"])
    except R2StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotated file has not been created yet.",
        ) from exc

    used_at = datetime.now(timezone.utc)
    try:
        _consume_download_token(
            supabase,
            token_row=token_row,
            user_id=current_user.user_id,
            used_at=used_at,
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    filename = _build_annotated_report_filename(document.get("original_filename"))
    return Response(
        content=annotated_content,
        media_type=DOCX_MIME_TYPE,
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.get("/{document_id}/annotated-report/download")
async def download_annotated_report_alias(
    *,
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> Response:
    document_id = str(document_id)

    try:
        supabase = get_supabase_rest_client()
        document = _get_owned_document_for_annotation_download(
            supabase,
            document_id=document_id,
            user_id=current_user.user_id,
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    _ensure_annotated_document_is_downloadable(document)

    try:
        r2_storage = get_r2_storage_client()
        annotated_content = r2_storage.download_bytes(document["annotated_file_key"])
    except R2StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotated file has not been created yet.",
        ) from exc

    filename = _build_annotated_report_filename(document.get("original_filename"))
    return Response(
        content=annotated_content,
        media_type=DOCX_MIME_TYPE,
        headers={"Content-Disposition": _content_disposition(filename)},
    )


def _create_annotated_document_response(
    *,
    document_id: str,
    current_user: CurrentUser,
) -> DocumentAnnotateResponse:
    try:
        supabase = get_supabase_rest_client()
        document = _get_owned_document_for_annotation(
            supabase,
            document_id=document_id,
            user_id=current_user.user_id,
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    _ensure_document_has_analysis(document)

    try:
        findings = _get_document_findings(supabase, document_id)
        r2_storage = get_r2_storage_client()
        original_content = r2_storage.download_bytes(document["original_file_key"])
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except R2StorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    input_path = _write_temp_docx(original_content)
    output_path = _create_temp_docx_path()
    try:
        annotation_result = annotate_docx_document(
            str(input_path),
            str(output_path),
            findings,
        )
        annotated_content = output_path.read_bytes()
    except DocumentAnnotationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)

    annotated_file_key = build_annotated_document_key(current_user.user_id, document_id)
    annotated_at = datetime.now(timezone.utc).isoformat()

    try:
        r2_storage.upload_bytes(
            object_key=annotated_file_key,
            content=annotated_content,
            content_type=DOCX_MIME_TYPE,
        )
        updated_document = supabase.update_one(
            "documents",
            filters={"id": document_id, "user_id": current_user.user_id},
            payload={
                "annotated_file_key": annotated_file_key,
                "annotated_at": annotated_at,
            },
            columns="id,status,annotated_file_key",
        )
    except R2StorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except SupabaseAPIError as exc:
        try:
            r2_storage.delete_object(annotated_file_key)
        except R2StorageError:
            pass
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return DocumentAnnotateResponse(
        document_id=updated_document["id"],
        status=updated_document["status"],
        annotated_file_key=updated_document["annotated_file_key"],
        annotated_report_file_key=updated_document["annotated_file_key"],
        comment_mode=annotation_result["comment_mode"],
        comment_strategy=annotation_result.get("comment_strategy", annotation_result["comment_mode"]),
        comment_count=annotation_result["comment_count"],
        grouped_findings_in_comments=annotation_result.get("grouped_findings_in_comments", 0),
        skipped_count=annotation_result["skipped_count"],
        total_findings=annotation_result["total_findings"],
        total_comments_created=annotation_result["total_comments_created"],
        skipped_comments=annotation_result["skipped_comments"],
        skipped_findings=annotation_result["skipped_findings"],
        skipped_reason=annotation_result["skipped_reason"],
        comment_note=annotation_result["comment_note"],
        download_url=f"/api/v1/documents/{document_id}/annotated-download",
    )


def _write_temp_docx(content: bytes) -> Path:
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as temp_file:
        temp_file.write(content)
        return Path(temp_file.name)


def _create_temp_docx_path() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as temp_file:
        return Path(temp_file.name)


def _get_document_template_or_fallback(supabase, document_type: str) -> dict[str, Any]:
    template = supabase.select_one(
        "document_templates",
        filters={"key": document_type, "is_active": "true"},
        columns="key,name,config_json",
    )
    if template is None:
        return {
            "key": document_type,
            "name": document_type,
            "config_json": None,
            "config_source": "local",
        }

    config_json = template.get("config_json")
    return {
        "key": template.get("key") or document_type,
        "name": template.get("name") or document_type,
        "config_json": config_json if isinstance(config_json, dict) else None,
        "config_source": "document_templates" if isinstance(config_json, dict) else "local",
    }


def _get_owned_document_for_download(
    supabase,
    *,
    document_id: str,
    user_id: str,
) -> dict | None:
    return supabase.select_one(
        "documents",
        filters={"id": document_id, "user_id": user_id},
        columns="id,user_id,status,fixed_file_key,original_filename",
    )


def _get_owned_document_for_annotation(
    supabase,
    *,
    document_id: str,
    user_id: str,
) -> dict | None:
    return supabase.select_one(
        "documents",
        filters={"id": document_id, "user_id": user_id},
        columns=(
            "id,user_id,status,original_file_key,report_file_key,original_filename,"
            "annotated_file_key,annotated_at,total_findings"
        ),
    )


def _get_owned_document_for_annotation_download(
    supabase,
    *,
    document_id: str,
    user_id: str,
) -> dict | None:
    return supabase.select_one(
        "documents",
        filters={"id": document_id, "user_id": user_id},
        columns="id,user_id,status,annotated_file_key,original_filename",
    )


def _get_document_findings(supabase, document_id: str) -> list[dict]:
    return supabase.select_many(
        "findings",
        filters={"document_id": document_id},
        columns="type,severity,location,message,current_value,expected_value,suggestion,metadata,created_at",
        order="created_at.asc",
    )


def _create_download_token_response(
    supabase,
    *,
    document_id: str,
    user_id: str,
    kind: str,
    download_path: str,
) -> DocumentDownloadTokenResponse:
    token = secrets.token_urlsafe(32)
    token_hash = _hash_download_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.download_token_ttl_minutes)

    supabase.insert_one(
        "download_tokens",
        payload={
            "user_id": user_id,
            "document_id": document_id,
            "kind": kind,
            "token_hash": token_hash,
            "expires_at": expires_at.isoformat(),
        },
        columns="id",
    )

    return DocumentDownloadTokenResponse(
        document_id=document_id,
        token=token,
        expires_at=expires_at.isoformat(),
        download_url=f"{download_path}?token={token}",
    )


def _get_download_token(
    supabase,
    *,
    document_id: str,
    user_id: str,
    token_hash: str,
    kind: str,
) -> dict | None:
    return supabase.select_one(
        "download_tokens",
        filters={
            "document_id": document_id,
            "user_id": user_id,
            "token_hash": token_hash,
            "kind": kind,
        },
        columns="id,expires_at,used_at,kind",
    )


def _ensure_token_is_valid(token_row: dict | None, now: datetime) -> None:
    if token_row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid download token.",
        )
    if token_row.get("used_at"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download token has already been used.",
        )

    expires_at = _parse_timestamptz(token_row.get("expires_at"))
    if expires_at is None or expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Download token has expired.",
        )


def _consume_download_token(
    supabase,
    *,
    token_row: dict,
    user_id: str,
    used_at: datetime,
) -> None:
    consumed = supabase.update_maybe_one(
        "download_tokens",
        filters={"id": token_row["id"], "user_id": user_id},
        raw_filters={
            "used_at": "is.null",
            "expires_at": f"gt.{used_at.isoformat()}",
        },
        payload={"used_at": used_at.isoformat()},
        columns="id,used_at",
    )
    if consumed is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download token has already been used or expired.",
        )


def _ensure_document_has_analysis(document: dict) -> None:
    if document.get("status") not in {"analyzed", "pending_payment", "paid", "fixed", "downloaded"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document must be analyzed before creating an annotated file.",
        )
    if not document.get("report_file_key"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document analysis report is missing.",
        )
    if not document.get("original_file_key"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document does not have an original file.",
        )


def _ensure_paid_order(
    supabase,
    *,
    document_id: str,
    user_id: str,
    error_detail: str,
) -> None:
    paid_order = supabase.select_one(
        "orders",
        filters={"document_id": document_id, "user_id": user_id, "status": "paid"},
        columns="id,status,paid_at",
    )
    if paid_order is None:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=error_detail)


def _ensure_fixed_file_payment_allowed(
    supabase,
    *,
    document_id: str,
    user_id: str,
    error_detail: str,
) -> None:
    if not settings.fixed_file_payment_required:
        return

    _ensure_paid_order(
        supabase,
        document_id=document_id,
        user_id=user_id,
        error_detail=error_detail,
    )


def _ensure_document_is_downloadable(document: dict) -> None:
    if document["status"] not in {"fixed", "downloaded"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document cannot be downloaded from status {document['status']}.",
        )
    if not document.get("fixed_file_key"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document does not have a fixed file yet.",
        )


def _ensure_annotated_document_is_downloadable(document: dict) -> None:
    if document.get("status") not in {"analyzed", "pending_payment", "paid", "fixed", "downloaded"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Annotated file cannot be downloaded from status {document.get('status')}.",
        )
    if not document.get("annotated_file_key"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Annotated file has not been created yet.",
        )


def _hash_download_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_timestamptz(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_fixed_download_filename(original_filename: str | None) -> str:
    base_name = PurePosixPath((original_filename or "document.docx").replace("\\", "/")).name
    stem = base_name[:-5] if base_name.lower().endswith(".docx") else base_name
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-") or "document"
    return f"fixed-{safe_stem}.docx"


def _build_annotated_report_filename(original_filename: str | None) -> str:
    base_name = PurePosixPath((original_filename or "document.docx").replace("\\", "/")).name
    stem = base_name[:-5] if base_name.lower().endswith(".docx") else base_name
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-") or "document"
    return f"report-loi-{safe_stem}.docx"


def _content_disposition(filename: str) -> str:
    quoted_filename = quote(filename)
    return f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quoted_filename}'


def _build_finding_rows(document_id: str, findings: list[dict]) -> list[dict]:
    return [
        {
            "document_id": document_id,
            "type": finding["type"],
            "severity": finding["severity"],
            "location": finding.get("location"),
            "message": finding["message"],
            "current_value": finding.get("current_value"),
            "expected_value": finding.get("expected_value"),
            "suggestion": finding.get("suggestion"),
            "metadata": finding.get("metadata", {}),
        }
        for finding in findings
    ]


def _mark_document_failed(supabase, document_id: str, user_id: str) -> None:
    try:
        supabase.update_one(
            "documents",
            filters={"id": document_id, "user_id": user_id},
            payload={"status": "failed"},
            columns="id,status",
        )
    except SupabaseAPIError:
        pass
