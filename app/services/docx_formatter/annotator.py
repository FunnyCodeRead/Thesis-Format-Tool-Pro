from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.docx_formatter.engine.annotation_engine import AnnotationEngine
from app.services.docx_formatter.writers.word_comment_writer import (
    WordCommentWriter,
    WordCommentWriterError,
)


class DocumentAnnotationError(RuntimeError):
    pass


def annotate_document(
    input_path: str,
    output_path: str,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise DocumentAnnotationError("Output path must be different from the original input path.")

    comments = AnnotationEngine().build_comments(findings)

    try:
        result = WordCommentWriter().write(
            input_path=input_path,
            output_path=output_path,
            comments=comments,
        )
    except WordCommentWriterError as exc:
        raise DocumentAnnotationError(str(exc)) from exc

    return {
        **result,
        "comment_mode": "hybrid",
        "comment_strategy": "hybrid",
        "planned_comment_count": len(comments),
        "output_path": output_path,
    }
