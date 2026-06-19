from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

COMMENT_PARTS = {
    "word/comments.xml",
    "word/commentsExtended.xml",
    "word/commentsIds.xml",
}
COMMENT_REL_TYPES = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments",
    "http://schemas.microsoft.com/office/2011/relationships/commentsExtended",
    "http://schemas.microsoft.com/office/2016/09/relationships/commentsIds",
}
WORD_ARTIFACT_TAGS = {
    f"{{{W_NS}}}commentRangeStart",
    f"{{{W_NS}}}commentRangeEnd",
    f"{{{W_NS}}}commentReference",
    f"{{{W_NS}}}highlight",
}
TRACK_CHANGE_TAGS = {
    f"{{{W_NS}}}trackRevisions",
    f"{{{W_NS}}}ins",
    f"{{{W_NS}}}del",
    f"{{{W_NS}}}moveFrom",
    f"{{{W_NS}}}moveTo",
}


def inspect_submission_artifacts(docx_path: str) -> dict[str, int]:
    report = {
        "comment_parts": 0,
        "comment_relationships": 0,
        "comment_markers": 0,
        "highlights": 0,
        "comment_reference_runs": 0,
    }

    try:
        with zipfile.ZipFile(docx_path, "r") as docx_zip:
            names = set(docx_zip.namelist())
            report["comment_parts"] = sum(1 for name in COMMENT_PARTS if name in names)

            for item_name in names:
                content = docx_zip.read(item_name)
                if item_name.endswith(".rels"):
                    report["comment_relationships"] += _count_comment_relationships(content)
                if item_name.startswith("word/") and item_name.endswith(".xml"):
                    xml_report = _inspect_word_xml(content)
                    for key, value in xml_report.items():
                        report[key] += value
    except (OSError, zipfile.BadZipFile):
        return report

    return report


def has_submission_artifacts(report: dict[str, int]) -> bool:
    return any(value > 0 for value in report.values())


def inspect_tracked_changes(docx_path: str) -> dict[str, int]:
    report = {
        "track_revisions": 0,
        "insertions": 0,
        "deletions": 0,
        "moves_from": 0,
        "moves_to": 0,
        "total": 0,
    }

    try:
        with zipfile.ZipFile(docx_path, "r") as docx_zip:
            for item_name in docx_zip.namelist():
                if item_name.startswith("word/") and item_name.endswith(".xml"):
                    xml_report = _inspect_tracked_changes_xml(docx_zip.read(item_name))
                    for key, value in xml_report.items():
                        report[key] += value
    except (OSError, zipfile.BadZipFile):
        return report

    report["total"] = (
        report["track_revisions"]
        + report["insertions"]
        + report["deletions"]
        + report["moves_from"]
        + report["moves_to"]
    )
    return report


def has_tracked_changes(report: dict[str, int]) -> bool:
    return report.get("total", 0) > 0


def clean_submission_artifacts(docx_path: str) -> None:
    source_path = Path(docx_path)
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        with zipfile.ZipFile(source_path, "r") as input_zip:
            with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as output_zip:
                for item in input_zip.infolist():
                    name = item.filename
                    if name in COMMENT_PARTS:
                        continue

                    content = input_zip.read(item)
                    if name == "[Content_Types].xml":
                        content = _clean_content_types(content)
                    elif name.endswith(".rels"):
                        content = _clean_relationships(content)
                    elif name.startswith("word/") and name.endswith(".xml"):
                        content = _clean_word_xml(content)

                    output_zip.writestr(item, content)

        shutil.move(str(temp_path), source_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _clean_word_xml(content: bytes) -> bytes:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return content

    changed = _remove_matching_children(root, WORD_ARTIFACT_TAGS)
    if _remove_comment_reference_runs(root):
        changed = True
    return _serialize_xml(root) if changed else content


def _clean_relationships(content: bytes) -> bytes:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return content

    changed = False
    for child in list(root):
        if child.attrib.get("Type") in COMMENT_REL_TYPES:
            root.remove(child)
            changed = True

    return _serialize_xml(root) if changed else content


def _clean_content_types(content: bytes) -> bytes:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return content

    changed = False
    for child in list(root):
        part_name = child.attrib.get("PartName", "").lstrip("/")
        if part_name in COMMENT_PARTS:
            root.remove(child)
            changed = True

    return _serialize_xml(root) if changed else content


def _remove_matching_children(root: ElementTree.Element, tags: set[str]) -> bool:
    changed = False

    for child in list(root):
        if child.tag in tags:
            root.remove(child)
            changed = True
            continue
        if _remove_matching_children(child, tags):
            changed = True

    return changed


def _remove_comment_reference_runs(root: ElementTree.Element) -> bool:
    changed = False
    run_tag = f"{{{W_NS}}}r"

    for child in list(root):
        if child.tag == run_tag and _is_empty_comment_reference_run(child):
            root.remove(child)
            changed = True
            continue
        if _remove_comment_reference_runs(child):
            changed = True

    return changed


def _count_comment_relationships(content: bytes) -> int:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return 0

    return sum(1 for child in root if child.attrib.get("Type") in COMMENT_REL_TYPES)


def _inspect_word_xml(content: bytes) -> dict[str, int]:
    report = {
        "comment_markers": 0,
        "highlights": 0,
        "comment_reference_runs": 0,
    }

    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return report

    for descendant in root.iter():
        if descendant.tag in {
            f"{{{W_NS}}}commentRangeStart",
            f"{{{W_NS}}}commentRangeEnd",
            f"{{{W_NS}}}commentReference",
        }:
            report["comment_markers"] += 1
        elif descendant.tag == f"{{{W_NS}}}highlight":
            report["highlights"] += 1

    report["comment_reference_runs"] = _count_comment_reference_runs(root)
    return report


def _inspect_tracked_changes_xml(content: bytes) -> dict[str, int]:
    report = {
        "track_revisions": 0,
        "insertions": 0,
        "deletions": 0,
        "moves_from": 0,
        "moves_to": 0,
    }

    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return report

    tag_to_key = {
        f"{{{W_NS}}}trackRevisions": "track_revisions",
        f"{{{W_NS}}}ins": "insertions",
        f"{{{W_NS}}}del": "deletions",
        f"{{{W_NS}}}moveFrom": "moves_from",
        f"{{{W_NS}}}moveTo": "moves_to",
    }
    for descendant in root.iter():
        key = tag_to_key.get(descendant.tag)
        if key:
            report[key] += 1
    return report


def _count_comment_reference_runs(root: ElementTree.Element) -> int:
    run_tag = f"{{{W_NS}}}r"
    count = 0

    for child in root.iter():
        if child.tag == run_tag and _is_empty_comment_reference_run(child):
            count += 1

    return count


def _is_empty_comment_reference_run(run: ElementTree.Element) -> bool:
    has_comment_reference_style = False
    for descendant in run.iter():
        if descendant.tag == f"{{{W_NS}}}rStyle" and descendant.attrib.get(f"{{{W_NS}}}val") == "CommentReference":
            has_comment_reference_style = True
            break

    if not has_comment_reference_style:
        return False

    return not any(
        descendant.tag in {
            f"{{{W_NS}}}t",
            f"{{{W_NS}}}drawing",
            f"{{{W_NS}}}pict",
        }
        and (descendant.text or descendant.attrib)
        for descendant in run.iter()
    )


def _serialize_xml(root: ElementTree.Element) -> bytes:
    ElementTree.register_namespace("w", W_NS)
    ElementTree.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
    ElementTree.register_namespace("rel", REL_NS)
    ElementTree.register_namespace("ct", CONTENT_TYPES_NS)
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
