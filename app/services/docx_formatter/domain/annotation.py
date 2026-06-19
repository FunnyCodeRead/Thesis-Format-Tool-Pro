from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Literal

AnnotationTargetKind = Literal[
    "section",
    "paragraph",
    "heading",
    "caption",
    "table_cell",
    "header",
    "footer",
]


@dataclass(frozen=True)
class AnnotationTarget:
    target: AnnotationTargetKind
    section_index: int | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None
    table_paragraph_index: int | None = None
    part_paragraph_index: int | None = None
    field: str | None = None
    location: str | None = None

    def locator_key(self) -> tuple[object, ...]:
        if self.target in {"paragraph", "heading", "caption"} and self.paragraph_index is not None:
            return (self.target, self.paragraph_index)
        if self.target == "table_cell" and self.table_index is not None:
            return (
                self.target,
                self.table_index,
                self.row_index,
                self.cell_index,
                self.table_paragraph_index,
            )
        if self.target in {"header", "footer"}:
            return (self.target, self.section_index, self.part_paragraph_index)
        if self.target == "section":
            return (self.target, self.section_index)
        return (
            self.target,
            self.section_index,
            self.paragraph_index,
            self.table_index,
            self.row_index,
            self.cell_index,
            self.table_paragraph_index,
            self.location,
        )


@dataclass(frozen=True)
class AnnotationIssue:
    issue_id: str
    title: str
    message: str
    source_type: str
    current_value: str | None = None
    expected_value: str | None = None
    suggestion: str | None = None
    field: str | None = None

    def to_text(self, index: int | None = None) -> str:
        prefix = f"{index}. " if index is not None else ""
        parts = [f"{prefix}Lỗi: {self.title}"]

        if self.message and self.message != self.title:
            parts.append(f"Mô tả: {self.message}")
        if self.current_value:
            parts.append(f"Hiện tại: {self.current_value}")
        if self.expected_value:
            parts.append(f"Yêu cầu: {self.expected_value}")
        if self.suggestion:
            parts.append(f"Gợi ý: {self.suggestion}")

        return "\n".join(
            unicodedata.normalize("NFC", part)
            for part in parts
            if part
        )


@dataclass(frozen=True)
class AnnotationComment:
    title: str
    message: str
    severity: str
    target: AnnotationTarget
    current_value: str | None = None
    expected_value: str | None = None
    suggestion: str | None = None
    source_type: str | None = None
    issues: list[AnnotationIssue] = field(default_factory=list)
    source_count_override: int | None = None
    source_ids_override: list[str] | None = None

    @property
    def source_count(self) -> int:
        if self.source_count_override is not None:
            return self.source_count_override
        return len(self.issues) if self.issues else 1

    @property
    def source_ids(self) -> list[str]:
        if self.source_ids_override is not None:
            return self.source_ids_override
        return [issue.issue_id for issue in self.issues]

    def to_text(self) -> str:
        if not self.issues:
            issue = AnnotationIssue(
                issue_id=self.source_type or "UNKNOWN",
                title=self.title,
                message=self.message,
                source_type=self.source_type or "UNKNOWN",
                current_value=self.current_value,
                expected_value=self.expected_value,
                suggestion=self.suggestion,
            )
            return issue.to_text()

        if len(self.issues) == 1:
            return self.issues[0].to_text()

        parts = [f"Có {len(self.issues)} lỗi định dạng tại vị trí này."]
        parts.extend(issue.to_text(index=index) for index, issue in enumerate(self.issues, start=1))
        return "\n\n".join(parts)
