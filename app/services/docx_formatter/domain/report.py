from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ReportSeverity = Literal["critical", "major", "minor"]


@dataclass(frozen=True)
class ReportSummary:
    total_issues: int = 0
    critical: int = 0
    major: int = 0
    minor: int = 0
    auto_fixable: int = 0
    manual_review: int = 0
    style_fix_groups: list[dict[str, Any]] = field(default_factory=list)
    manual_repair_guidance: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReportIssueGroup:
    group_id: str
    group_name: str
    total: int
    severity: ReportSeverity
    description: str
    issues: list[dict[str, Any]] = field(default_factory=list)
    recommended_fix_scope: str = "manual_review"
    affected_styles: list[str] = field(default_factory=list)
    manual_repair_guidance: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductionReport:
    ok: bool
    message: str
    document: dict[str, Any]
    reference: dict[str, Any]
    summary: ReportSummary
    issue_groups: list[ReportIssueGroup]
    manual_repair_guidance: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "document": self.document,
            "reference": self.reference,
            "summary": self.summary.to_dict(),
            "issue_groups": [group.to_dict() for group in self.issue_groups],
            "manual_repair_guidance": self.manual_repair_guidance,
        }
