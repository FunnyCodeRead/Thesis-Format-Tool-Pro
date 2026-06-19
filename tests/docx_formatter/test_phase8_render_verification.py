from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document

from app.services.docx_formatter.analyzer import analyze_document_with_details
from app.services.docx_formatter.render_verifier import (
    LibreOfficeRenderer,
    PdfImageBox,
    PdfPageSnapshot,
    PdfRenderInspector,
    PdfWordBox,
    verify_docx_render,
)


class Phase8RenderVerificationTests(unittest.TestCase):
    def test_pdf_page_snapshots_create_manual_review_findings(self) -> None:
        pages = [
            PdfPageSnapshot(page_number=1, width=595, height=842, text=""),
            PdfPageSnapshot(
                page_number=2,
                width=595,
                height=842,
                text="Noi dung trang",
                words=[PdfWordBox(text="TranLe", x0=4, x1=45, top=120, bottom=135)],
            ),
            PdfPageSnapshot(
                page_number=3,
                width=595,
                height=842,
                text="Hình 2.1. Mô hình tổng quan\nNội dung tiếp theo",
                words=[],
                images=[],
            ),
            PdfPageSnapshot(
                page_number=4,
                width=595,
                height=842,
                text="Anh qua lon",
                images=[PdfImageBox(x0=10, x1=590, top=100, bottom=500)],
            ),
        ]

        findings = PdfRenderInspector().findings_from_pages(pages, _config())
        finding_types = {finding.type for finding in findings}

        self.assertIn("RENDER_BLANK_PAGE_REVIEW", finding_types)
        self.assertIn("RENDER_EDGE_OVERFLOW_REVIEW", finding_types)
        self.assertIn("RENDER_CAPTION_PAGE_BREAK_REVIEW", finding_types)
        for finding in findings:
            self.assertEqual(finding.metadata["report_group_id"], "render_verification")
            self.assertFalse(finding.metadata["auto_fixable"])
            self.assertTrue(finding.metadata["manual_review"])

    def test_pdf_page_snapshots_limit_repeated_findings_per_type(self) -> None:
        pages = [
            PdfPageSnapshot(page_number=index, width=595, height=842, text="")
            for index in range(1, 6)
        ]

        findings = PdfRenderInspector().findings_from_pages(
            pages,
            {
                **_config(),
                "render_verification": {
                    **_config()["render_verification"],
                    "max_findings_per_type": 2,
                },
            },
        )

        self.assertEqual(
            sum(1 for finding in findings if finding.type == "RENDER_BLANK_PAGE_REVIEW"),
            2,
        )

    def test_libreoffice_renderer_uses_isolated_profile_and_pdf_export_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.docx"
            output_dir = Path(temp_dir) / "out"
            output_dir.mkdir()
            input_path.write_bytes(b"fake-docx")
            expected_pdf = output_dir / "input.pdf"

            def fake_run(command, **kwargs):
                expected_pdf.write_bytes(b"%PDF-1.4")
                fake_run.command = command
                fake_run.kwargs = kwargs

                class Completed:
                    returncode = 0
                    stdout = b""
                    stderr = b""

                return Completed()

            with patch("app.services.docx_formatter.render_verifier.subprocess.run", side_effect=fake_run):
                pdf_path = LibreOfficeRenderer("soffice").render_pdf(
                    str(input_path),
                    str(output_dir),
                    timeout_seconds=30,
                )

        self.assertEqual(pdf_path.name, "input.pdf")
        self.assertIn("--headless", fake_run.command)
        self.assertIn("pdf:writer_pdf_Export", fake_run.command)
        self.assertTrue(
            any(str(item).startswith("-env:UserInstallation=file:///") for item in fake_run.command)
        )
        self.assertEqual(fake_run.kwargs["timeout"], 30)
        self.assertIn("HOME", fake_run.kwargs["env"])

    def test_verify_docx_render_returns_completed_metadata_when_renderer_and_reader_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.docx"
            input_path.write_bytes(b"fake-docx")

            def fake_render_pdf(self, docx_path, output_dir, timeout_seconds):
                pdf_path = Path(output_dir) / "input.pdf"
                pdf_path.write_bytes(b"%PDF-1.4")
                return pdf_path

            def fake_inspect(self, pdf_path, config):
                return 3, [], "fake_pdf_reader"

            with (
                patch("app.services.docx_formatter.render_verifier.LibreOfficeRenderer.available", return_value=True),
                patch("app.services.docx_formatter.render_verifier.LibreOfficeRenderer.render_pdf", fake_render_pdf),
                patch("app.services.docx_formatter.render_verifier.PdfRenderInspector.inspect", fake_inspect),
            ):
                result = verify_docx_render(str(input_path), _config())

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["page_count"], 3)
        self.assertEqual(result["checked_pages"], 3)
        self.assertEqual(result["inspector"], "fake_pdf_reader")
        self.assertEqual(result["pdf_size_bytes"], 8)
        self.assertEqual(result["findings_by_type"], {})
        self.assertIsInstance(result["duration_ms"], int)

    def test_analyze_returns_skipped_render_status_when_renderer_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.docx"
            doc = Document()
            doc.add_paragraph("Doan van test du dai de analyzer co the chay ma khong can render PDF.")
            doc.save(input_path)

            result = analyze_document_with_details(str(input_path), "do_an_tot_nghiep")

        render_status = result["render_verification"]
        self.assertIn(render_status["status"], {"skipped", "completed"})
        if render_status["status"] == "skipped":
            self.assertTrue(render_status["skipped_reason"])


def _config() -> dict:
    return {
        "page_setup": {
            "margin_left_cm": 3.5,
            "margin_right_cm": 2.0,
            "margin_top_cm": 2.5,
            "margin_bottom_cm": 2.5,
        },
        "render_verification": {
            "blank_page_min_text_chars": 5,
            "edge_tolerance_pt": 6,
            "caption_page_edge_lines": 2,
        },
    }


if __name__ == "__main__":
    unittest.main()
