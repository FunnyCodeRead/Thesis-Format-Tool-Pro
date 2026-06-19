from __future__ import annotations

from typing import Any

DEFAULT_PREVIEW_LIMIT = 10


def build_preview_comments(
    grouped_findings: list[dict[str, Any]],
    *,
    limit: int = DEFAULT_PREVIEW_LIMIT,
) -> list[dict[str, Any]]:
    preview_comments: list[dict[str, Any]] = []

    for finding in grouped_findings:
        metadata = _metadata(finding)
        locations = _locations(finding, metadata)
        title = str(metadata.get("title") or finding.get("message") or "Lỗi định dạng")

        if not locations:
            preview_comments.append(_preview_item(finding, metadata, title, None))
        else:
            for location in locations:
                preview_comments.append(_preview_item(finding, metadata, title, location))

        if len(preview_comments) >= limit:
            return preview_comments[:limit]

    return preview_comments[:limit]


def build_preview_comments_from_report(
    report: dict[str, Any],
    *,
    limit: int = DEFAULT_PREVIEW_LIMIT,
) -> list[dict[str, Any]]:
    preview_comments: list[dict[str, Any]] = []

    issue_groups = report.get("issue_groups")
    if not isinstance(issue_groups, list):
        return []

    for group in issue_groups:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("group_name") or "Lỗi định dạng")
        issues = group.get("issues")
        if not isinstance(issues, list):
            continue

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            location = issue.get("location") if isinstance(issue.get("location"), dict) else {}
            target = issue.get("target") if isinstance(issue.get("target"), dict) else {}
            current = issue.get("current") if isinstance(issue.get("current"), dict) else {}
            expected = issue.get("expected") if isinstance(issue.get("expected"), dict) else {}

            preview_comments.append(
                {
                    "title": group_name,
                    "message": issue.get("message"),
                    "severity": issue.get("severity"),
                    "category": issue.get("group_id"),
                    "location": _location_label(location),
                    "text_preview": target.get("text_preview"),
                    "current_value": _first_public_value(current),
                    "expected_value": _first_public_value(expected),
                    "suggestion": issue.get("suggestion"),
                }
            )

            if len(preview_comments) >= limit:
                return preview_comments[:limit]

    return preview_comments[:limit]


def _preview_item(
    finding: dict[str, Any],
    metadata: dict[str, Any],
    title: str,
    location: str | None,
) -> dict[str, Any]:
    return {
        "title": title,
        "message": finding.get("message"),
        "severity": finding.get("severity"),
        "category": metadata.get("category"),
        "location": location,
        "current_value": finding.get("current_value"),
        "expected_value": finding.get("expected_value"),
        "suggestion": finding.get("suggestion"),
    }


def _metadata(finding: dict[str, Any]) -> dict[str, Any]:
    metadata = finding.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _locations(finding: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
    first_locations = metadata.get("first_locations")
    if isinstance(first_locations, list):
        return [
            str(location)
            for location in first_locations
            if isinstance(location, str) and location.strip()
        ]

    location = finding.get("location")
    if isinstance(location, str) and location.strip():
        return [location]

    return []


def _location_label(location: dict[str, Any]) -> str | None:
    raw = location.get("raw")
    if isinstance(raw, str) and raw.strip():
        return raw

    paragraph_index = location.get("paragraph_index")
    if paragraph_index:
        return f"Paragraph {paragraph_index}"

    section_index = location.get("section_index")
    if section_index:
        return f"Section {section_index}"

    return None


def _first_public_value(values: dict[str, Any]) -> str | None:
    for key, value in values.items():
        if key.startswith("_") or value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None
