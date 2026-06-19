from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.services.docx_formatter.domain.finding import Finding

POINTS_PER_CM = 72 / 2.54


@dataclass(frozen=True)
class PdfWordBox:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass(frozen=True)
class PdfImageBox:
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass(frozen=True)
class PdfPageSnapshot:
    page_number: int
    width: float
    height: float
    text: str = ""
    words: list[PdfWordBox] = field(default_factory=list)
    images: list[PdfImageBox] = field(default_factory=list)


class RenderVerificationError(RuntimeError):
    pass


class LibreOfficeRenderer:
    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or _find_libreoffice()

    def available(self) -> bool:
        return bool(self.executable)

    def render_pdf(self, docx_path: str, output_dir: str, timeout_seconds: int) -> Path:
        if not self.executable:
            raise RenderVerificationError("Không tìm thấy LibreOffice/soffice.")

        source_path = Path(docx_path)
        output_path = Path(output_dir)
        profile_dir = output_path / "lo-profile"
        profile_dir.mkdir(parents=True, exist_ok=True)

        command = [
            self.executable,
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            "--nodefault",
            "--nolockcheck",
            "--norestore",
            "--invisible",
            f"-env:UserInstallation={_file_uri(profile_dir)}",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(output_path),
            str(source_path),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            env=_subprocess_env(output_path),
        )
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="ignore").strip()
            stdout = completed.stdout.decode("utf-8", errors="ignore").strip()
            detail = stderr or stdout or "LibreOffice không chuyển DOCX sang PDF thành công."
            raise RenderVerificationError(detail)

        expected_pdf = output_path / f"{source_path.stem}.pdf"
        if expected_pdf.exists() and expected_pdf.stat().st_size > 0:
            return expected_pdf

        candidates = [
            candidate for candidate in output_path.glob("*.pdf")
            if candidate.stat().st_size > 0
        ]
        if candidates:
            return candidates[0]

        raise RenderVerificationError("LibreOffice không tạo được file PDF đầu ra.")


class PdfRenderInspector:
    def inspect(self, pdf_path: str, config: dict[str, Any]) -> tuple[int | None, list[Finding], str]:
        pages, engine_name = self._load_pages(pdf_path)
        if pages is None:
            return None, [], engine_name
        findings = self.findings_from_pages(pages, config)
        return len(pages), findings, engine_name

    def findings_from_pages(
        self,
        pages: list[PdfPageSnapshot],
        config: dict[str, Any],
    ) -> list[Finding]:
        render_config = config.get("render_verification", {})
        min_text_chars = int(render_config.get("blank_page_min_text_chars", 5))
        edge_tolerance_pt = float(render_config.get("edge_tolerance_pt", 6))
        caption_edge_lines = int(render_config.get("caption_page_edge_lines", 2))
        max_findings_per_type = int(render_config.get("max_findings_per_type", 25))
        margins = _expected_margins_pt(config)

        findings: list[Finding] = []
        type_counts: dict[str, int] = {}
        for page in pages:
            normalized_text = _normalize_pdf_text(page.text)
            if (
                render_config.get("blank_page_enabled", True) is not False
                and len(normalized_text) < min_text_chars
                and not page.images
            ):
                _append_limited(
                    findings,
                    _render_finding(
                        finding_type="RENDER_BLANK_PAGE_REVIEW",
                        page_number=page.page_number,
                        message="Trang render gần như trống, cần kiểm tra lại bố cục.",
                        current_value="Không phát hiện text hoặc ảnh đáng kể trên trang.",
                        expected_value="Tài liệu không nên có trang trắng ngoài chủ ý.",
                        suggestion=(
                            "Mở bản Word/PDF render để kiểm tra page break, section break "
                            "hoặc bảng/ảnh bị đẩy trang."
                        ),
                        field="blank_page",
                    ),
                    type_counts,
                    max_findings_per_type,
                )

            edge_items = _edge_items(page, margins, edge_tolerance_pt)
            if render_config.get("edge_overflow_enabled", True) is not False and edge_items:
                _append_limited(
                    findings,
                    _render_finding(
                        finding_type="RENDER_EDGE_OVERFLOW_REVIEW",
                        page_number=page.page_number,
                        message="Nội dung render nằm quá sát mép trang, có nguy cơ tràn lề hoặc bị cắt.",
                        current_value=", ".join(edge_items[:4]),
                        expected_value=(
                            "Text, bảng, ảnh và đầu trang/chân trang không được vượt vùng in an toàn."
                        ),
                        suggestion=(
                            "Kiểm tra trang render này; nếu bảng, ảnh, đầu trang/chân trang "
                            "hoặc chữ bị sát mép/mất chữ thì chỉnh thủ công trong Word."
                        ),
                        field="render_edge_overflow",
                    ),
                    type_counts,
                    max_findings_per_type,
                )

            if (
                render_config.get("caption_page_break_enabled", True) is not False
                and _caption_starts_page(page, caption_edge_lines)
            ):
                _append_limited(
                    findings,
                    _render_finding(
                        finding_type="RENDER_CAPTION_PAGE_BREAK_REVIEW",
                        page_number=page.page_number,
                        message="Caption xuất hiện ở đầu trang render, cần kiểm tra có bị tách khỏi hình/bảng không.",
                        current_value=_first_non_empty_line(page.text),
                        expected_value=(
                            "Caption nên nằm gần hình/bảng tương ứng và không bị tách trang bất thường."
                        ),
                        suggestion=(
                            "Mở trang render để kiểm tra caption có còn đi cùng hình/bảng "
                            "hay bị nhảy sang trang mới."
                        ),
                        field="caption_page_break",
                    ),
                    type_counts,
                    max_findings_per_type,
                )

        return findings

    def _load_pages(self, pdf_path: str) -> tuple[list[PdfPageSnapshot] | None, str]:
        pages = self._load_with_pdfplumber(pdf_path)
        if pages is not None:
            return pages, "pdfplumber"

        pages = self._load_with_pypdf(pdf_path)
        if pages is not None:
            return pages, "pypdf"

        return None, "missing_pdf_reader"

    def _load_with_pdfplumber(self, pdf_path: str) -> list[PdfPageSnapshot] | None:
        try:
            import pdfplumber  # type: ignore[import-not-found]
        except Exception:
            return None

        pages: list[PdfPageSnapshot] = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for index, page in enumerate(pdf.pages, start=1):
                    words = [
                        PdfWordBox(
                            text=str(word.get("text") or ""),
                            x0=float(word.get("x0") or 0),
                            x1=float(word.get("x1") or 0),
                            top=float(word.get("top") or 0),
                            bottom=float(word.get("bottom") or 0),
                        )
                        for word in page.extract_words() or []
                    ]
                    images = [
                        PdfImageBox(
                            x0=float(image.get("x0") or 0),
                            x1=float(image.get("x1") or 0),
                            top=float(image.get("top") or 0),
                            bottom=float(image.get("bottom") or 0),
                        )
                        for image in page.images or []
                    ]
                    pages.append(
                        PdfPageSnapshot(
                            page_number=index,
                            width=float(page.width),
                            height=float(page.height),
                            text=page.extract_text() or "",
                            words=words,
                            images=images,
                        )
                    )
        except Exception:
            return None

        return pages

    def _load_with_pypdf(self, pdf_path: str) -> list[PdfPageSnapshot] | None:
        try:
            from pypdf import PdfReader  # type: ignore[import-not-found]
        except Exception:
            return None

        pages: list[PdfPageSnapshot] = []
        try:
            reader = PdfReader(pdf_path)
            for index, page in enumerate(reader.pages, start=1):
                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
                pages.append(
                    PdfPageSnapshot(
                        page_number=index,
                        width=width,
                        height=height,
                        text=page.extract_text() or "",
                    )
                )
        except Exception:
            return None

        return pages


def verify_docx_render(local_file_path: str, config: dict[str, Any]) -> dict[str, Any]:
    render_config = config.get("render_verification", {})
    if render_config.get("enabled", True) is False:
        return _result(status="disabled", findings=[])

    renderer = LibreOfficeRenderer(str(render_config.get("libreoffice_path") or "") or None)
    if not renderer.available():
        return _result(
            status="skipped",
            findings=[],
            skipped_reason="Không tìm thấy LibreOffice/soffice trong môi trường backend.",
        )

    timeout_seconds = int(render_config.get("timeout_seconds", 90))
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="thesis-render-") as temp_dir:
        try:
            pdf_path = renderer.render_pdf(local_file_path, temp_dir, timeout_seconds)
            pdf_size_bytes = pdf_path.stat().st_size
            page_count, findings, inspector_engine = PdfRenderInspector().inspect(str(pdf_path), config)
        except subprocess.TimeoutExpired:
            return _result(
                status="skipped",
                findings=[],
                renderer=renderer.executable,
                skipped_reason="LibreOffice render quá thời gian cho phép.",
                duration_ms=_elapsed_ms(started),
            )
        except RenderVerificationError as exc:
            return _result(
                status="skipped",
                findings=[],
                renderer=renderer.executable,
                skipped_reason=str(exc),
                duration_ms=_elapsed_ms(started),
            )

    if inspector_engine == "missing_pdf_reader":
        return _result(
            status="skipped",
            findings=[],
            renderer=renderer.executable,
            skipped_reason="Chưa cài thư viện đọc PDF. Cần cài pdfplumber hoặc pypdf để kiểm tra render.",
            duration_ms=_elapsed_ms(started),
        )

    return _result(
        status="completed",
        findings=findings,
        renderer=renderer.executable,
        inspector=inspector_engine,
        page_count=page_count,
        checked_pages=page_count,
        duration_ms=_elapsed_ms(started),
        pdf_size_bytes=pdf_size_bytes,
    )


def _find_libreoffice() -> str | None:
    for candidate in ("soffice", "libreoffice"):
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _subprocess_env(output_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("HOME", str(output_dir))
    env.setdefault("TMPDIR", str(output_dir))
    return env


def _file_uri(path: Path) -> str:
    resolved = path.resolve()
    return "file:///" + quote(str(resolved).replace("\\", "/").lstrip("/"), safe=":/")


def _expected_margins_pt(config: dict[str, Any]) -> dict[str, float]:
    page_setup = config.get("page_setup", {})
    return {
        "left": _cm_to_pt(float(page_setup.get("margin_left_cm", 2.0))),
        "right": _cm_to_pt(float(page_setup.get("margin_right_cm", 2.0))),
        "top": _cm_to_pt(float(page_setup.get("margin_top_cm", 2.0))),
        "bottom": _cm_to_pt(float(page_setup.get("margin_bottom_cm", 2.0))),
    }


def _cm_to_pt(value: float) -> float:
    return value * POINTS_PER_CM


def _edge_items(
    page: PdfPageSnapshot,
    margins: dict[str, float],
    tolerance_pt: float,
) -> list[str]:
    items: list[str] = []

    for word in page.words:
        if word.x0 < margins["left"] - tolerance_pt:
            items.append(f"text sát/vượt lề trái: {word.text}")
            break
    for word in page.words:
        if word.x1 > page.width - margins["right"] + tolerance_pt:
            items.append(f"text sát/vượt lề phải: {word.text}")
            break
    for word in page.words:
        if word.top < margins["top"] - tolerance_pt:
            items.append(f"text sát/vượt lề trên: {word.text}")
            break
    for word in page.words:
        if word.bottom > page.height - margins["bottom"] + tolerance_pt:
            items.append(f"text sát/vượt lề dưới: {word.text}")
            break

    for image in page.images:
        if image.x0 < margins["left"] - tolerance_pt or image.x1 > page.width - margins["right"] + tolerance_pt:
            items.append("ảnh/sơ đồ sát hoặc vượt lề ngang")
            break
        if image.top < margins["top"] - tolerance_pt or image.bottom > page.height - margins["bottom"] + tolerance_pt:
            items.append("ảnh/sơ đồ sát hoặc vượt lề dọc")
            break

    return items


def _caption_starts_page(page: PdfPageSnapshot, edge_lines: int) -> bool:
    lines = [line.strip() for line in page.text.splitlines() if line.strip()]
    if not lines:
        return False
    first_lines = lines[: max(edge_lines, 1)]
    return any(
        re.match(r"^(Hình|Hinh|Bảng|Bang)\s+\d+(?:\.\d+)+", line, re.IGNORECASE)
        for line in first_lines
    )


def _first_non_empty_line(value: str) -> str | None:
    for line in value.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned
    return None


def _normalize_pdf_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _append_limited(
    findings: list[Finding],
    finding: Finding,
    type_counts: dict[str, int],
    max_findings_per_type: int,
) -> None:
    current_count = type_counts.get(finding.type, 0)
    if current_count >= max_findings_per_type:
        return
    type_counts[finding.type] = current_count + 1
    findings.append(finding)


def _render_finding(
    *,
    finding_type: str,
    page_number: int,
    message: str,
    current_value: str | None,
    expected_value: str,
    suggestion: str,
    field: str,
) -> Finding:
    return Finding(
        type=finding_type,
        severity="warning",
        location=f"Trang render {page_number}",
        message=message,
        current_value=current_value,
        expected_value=expected_value,
        suggestion=suggestion,
        metadata={
            "target": "rendered_page",
            "context": "render_verification",
            "report_group_id": "render_verification",
            "report_severity": "major",
            "page": page_number,
            "field": field,
            "text_preview": current_value,
            "auto_fixable": False,
            "manual_review": True,
            "fix_action": {
                "type": "manual_review",
                "reason": "Lỗi render cần kiểm tra bằng mắt trên PDF/Word; hệ thống không tự sửa.",
            },
        },
    )


def _result(
    *,
    status: str,
    findings: list[Finding],
    renderer: str | None = None,
    inspector: str | None = None,
    page_count: int | None = None,
    checked_pages: int | None = None,
    duration_ms: int | None = None,
    pdf_size_bytes: int | None = None,
    skipped_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "renderer": renderer,
        "inspector": inspector,
        "page_count": page_count,
        "checked_pages": checked_pages or 0,
        "findings_count": len(findings),
        "findings_by_type": _findings_by_type(findings),
        "duration_ms": duration_ms,
        "pdf_size_bytes": pdf_size_bytes,
        "skipped_reason": skipped_reason,
        "findings": findings,
    }


def _findings_by_type(findings: list[Finding]) -> dict[str, int]:
    result: dict[str, int] = {}
    for finding in findings:
        result[finding.type] = result.get(finding.type, 0) + 1
    return result


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))
