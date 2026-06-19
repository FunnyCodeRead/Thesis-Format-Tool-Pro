from __future__ import annotations

from typing import Any

from app.services.docx_formatter.annotator import (
    DocumentAnnotationError,
    annotate_document,
)


class AnnotatedReportError(DocumentAnnotationError):
    pass


def create_annotated_report(
    input_path: str,
    output_path: str,
    findings: list[dict[str, Any]],
) -> dict[str, int]:
    try:
        return annotate_document(input_path, output_path, findings)
    except DocumentAnnotationError as exc:
        raise AnnotatedReportError(str(exc)) from exc
