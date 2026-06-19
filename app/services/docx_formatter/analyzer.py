from __future__ import annotations

from typing import Any

from docx import Document

from app.services.docx_formatter.config.config_loader import AnalyzerConfigError, ConfigLoader
from app.services.docx_formatter.engine.analyzer_engine import AnalyzerEngine
from app.services.docx_formatter.engine.finding_grouper import FindingGrouper
from app.services.docx_formatter.engine.fixability_matrix import apply_fixability_to_findings
from app.services.docx_formatter.engine.preview_comment_builder import build_preview_comments
from app.services.docx_formatter.engine.vietnamese_text import normalize_vietnamese_finding
from app.services.docx_formatter.factories.rule_factory import RuleFactory
from app.services.docx_formatter.render_verifier import verify_docx_render

# Backward-compatible exports for old imports
from app.services.docx_formatter.rules.common_format import ALIGNMENT_BY_NAME
from app.services.docx_formatter.utils.text_utils import heading_key as _heading_key
from app.services.docx_formatter.utils.text_utils import should_skip_paragraph as _should_skip_paragraph


class DocumentAnalysisError(RuntimeError):
    pass


def load_config(
    document_type: str,
    config_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return ConfigLoader().load(document_type, config_override=config_override)


def analyze_document(
    local_file_path: str,
    document_type: str,
    *,
    config_override: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return analyze_document_with_details(
        local_file_path,
        document_type,
        config_override=config_override,
    )["findings"]


def analyze_document_with_details(
    local_file_path: str,
    document_type: str,
    *,
    config_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        config = load_config(document_type, config_override=config_override)
        doc = Document(local_file_path)
    except AnalyzerConfigError:
        raise
    except Exception as exc:
        raise DocumentAnalysisError("Failed to load .docx document.") from exc

    engine = AnalyzerEngine(RuleFactory.create_analyze_rules())
    raw_findings = engine.analyze(doc, config)
    render_verification = verify_docx_render(local_file_path, config)
    raw_findings.extend(render_verification["findings"])
    raw_findings = apply_fixability_to_findings(raw_findings)
    raw_findings = [normalize_vietnamese_finding(finding) for finding in raw_findings]
    grouped_findings = FindingGrouper().group(raw_findings)
    grouped_dicts = [finding.to_dict() for finding in grouped_findings]
    render_verification_payload = {
        key: value
        for key, value in render_verification.items()
        if key != "findings"
    }

    return {
        "raw_findings": [finding.to_dict() for finding in raw_findings],
        "findings": grouped_dicts,
        "preview_comments": build_preview_comments(grouped_dicts),
        "render_verification": render_verification_payload,
    }
