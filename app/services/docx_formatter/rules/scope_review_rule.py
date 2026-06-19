from __future__ import annotations

from typing import Any

from app.services.docx_formatter.domain.finding import Finding
from app.services.docx_formatter.domain.rule import AnalyzeRule
from app.services.docx_formatter.engine.context_classifier import classify_paragraph_context
from app.services.docx_formatter.utils.text_utils import normalize_text


class ScopeReviewRule(AnalyzeRule):
    def analyze(self, doc: Any, config: dict[str, Any]) -> list[Finding]:
        scope_config = _merged_scope_config(config)
        if not scope_config["enabled"]:
            return []

        disallowed_terms = [
            str(term).strip()
            for term in scope_config["terms"]
            if str(term).strip()
        ]
        if not disallowed_terms:
            return []

        normalized_terms = [(term, normalize_text(term)) for term in disallowed_terms]
        findings: list[Finding] = []

        for paragraph_index, paragraph in enumerate(doc.paragraphs, start=1):
            text = paragraph.text.strip()
            if not text:
                continue

            normalized_text = normalize_text(text)
            matched_terms = [
                term
                for term, normalized_term in normalized_terms
                if normalized_term and normalized_term in normalized_text
            ]
            if not matched_terms:
                continue

            context = classify_paragraph_context(paragraph, paragraph_index)
            findings.append(
                Finding(
                    type="OUT_OF_SCOPE_TERM_REVIEW",
                    severity="warning",
                    location=f"Paragraph {paragraph_index}",
                    message="Đoạn văn chứa cụm từ được cấu hình là ngoài phạm vi đề tài.",
                    current_value=", ".join(matched_terms),
                    expected_value="Không xuất hiện nội dung ngoài phạm vi đề tài đã cấu hình.",
                    suggestion="Kiểm tra thủ công xem nội dung này còn thuộc phạm vi đề tài hiện tại không.",
                    metadata={
                        "target": "paragraph",
                        "context": context.context,
                        "report_group_id": "scope_review",
                        "report_severity": "major",
                        "paragraph_index": paragraph_index,
                        "field": "scope_term",
                        "text_preview": context.text_preview,
                        "style_name": context.style_name,
                        "matched_terms": matched_terms,
                        "auto_fixable": False,
                        "manual_review": True,
                        "fix_action": {
                            "type": "manual_review",
                            "reason": "Cần người dùng xác nhận phạm vi đề tài; hệ thống không tự xóa hoặc sửa nội dung.",
                        },
                    },
                )
            )

        return findings


def _merged_scope_config(config: dict[str, Any]) -> dict[str, Any]:
    scope_review = config.get("scope_review", {})
    content_scope = config.get("content_scope", {})
    scope_review = scope_review if isinstance(scope_review, dict) else {}
    content_scope = content_scope if isinstance(content_scope, dict) else {}

    enabled = bool(scope_review.get("enabled", False) or content_scope.get("enabled", False))
    terms: list[Any] = []
    terms.extend(scope_review.get("disallowed_terms", []) or [])
    terms.extend(scope_review.get("forbidden_terms", []) or [])
    terms.extend(content_scope.get("forbidden_terms", []) or [])
    terms.extend(content_scope.get("disallowed_terms", []) or [])
    return {"enabled": enabled, "terms": terms}
