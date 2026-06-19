from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import Response

from app.api.health import read_readiness


class HealthReadinessTests(unittest.TestCase):
    def test_ready_reports_missing_required_groups_without_secret_values(self) -> None:
        response = Response()

        with (
            patch("app.api.health.settings.supabase_url", ""),
            patch("app.api.health.settings.supabase_service_role_key", "secret"),
            patch("app.api.health.settings.r2_account_id", ""),
            patch("app.api.health.settings.r2_access_key_id", ""),
            patch("app.api.health.settings.r2_secret_access_key", ""),
            patch("app.api.health.settings.r2_bucket_name", ""),
            patch("app.api.health.settings.payos_client_id", ""),
            patch("app.api.health.settings.payos_api_key", ""),
            patch("app.api.health.settings.payos_checksum_key", ""),
        ):
            payload = read_readiness(response)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["status"], "not_ready")
        serialized = str(payload)
        self.assertNotIn("secret", serialized)
        self.assertIn("SUPABASE_URL", serialized)

    def test_ready_allows_optional_libreoffice_to_be_missing(self) -> None:
        response = Response()

        with (
            patch("app.api.health.settings.supabase_url", "https://project.supabase.co"),
            patch("app.api.health.settings.supabase_service_role_key", "secret"),
            patch("app.api.health.settings.r2_account_id", "account"),
            patch("app.api.health.settings.r2_access_key_id", "access"),
            patch("app.api.health.settings.r2_secret_access_key", "r2-secret"),
            patch("app.api.health.settings.r2_bucket_name", "bucket"),
            patch("app.api.health.settings.payos_client_id", "client"),
            patch("app.api.health.settings.payos_api_key", "api"),
            patch("app.api.health.settings.payos_checksum_key", "checksum"),
            patch("app.api.health.shutil.which", return_value=None),
        ):
            payload = read_readiness(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ready")
        libreoffice = next(
            check for check in payload["checks"] if check["name"] == "libreoffice_render"
        )
        pdf_reader = next(
            check for check in payload["checks"] if check["name"] == "pdf_render_reader"
        )
        self.assertFalse(libreoffice["required"])
        self.assertFalse(libreoffice["ok"])
        self.assertFalse(pdf_reader["required"])


if __name__ == "__main__":
    unittest.main()
