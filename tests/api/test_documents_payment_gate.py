from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.documents import _ensure_fixed_file_payment_allowed
from app.api.payments import _payment_status_response


class _SupabaseOrdersStub:
    def __init__(self, paid_order=None) -> None:
        self.paid_order = paid_order
        self.select_one_calls = []

    def select_one(self, table, *, filters, columns):
        self.select_one_calls.append(
            {
                "table": table,
                "filters": filters,
                "columns": columns,
            }
        )
        if table == "orders" and filters.get("status") == "paid":
            return self.paid_order
        return None


class FixedFilePaymentGateTests(unittest.TestCase):
    def test_fixed_file_payment_gate_bypasses_orders_when_disabled(self) -> None:
        supabase = _SupabaseOrdersStub()

        with patch("app.api.documents.settings.fixed_file_payment_required", False):
            _ensure_fixed_file_payment_allowed(
                supabase,
                document_id="document-id",
                user_id="user-id",
                error_detail="Payment required.",
            )

        self.assertEqual(supabase.select_one_calls, [])

    def test_fixed_file_payment_gate_requires_paid_order_when_enabled(self) -> None:
        supabase = _SupabaseOrdersStub()

        with patch("app.api.documents.settings.fixed_file_payment_required", True):
            with self.assertRaises(HTTPException) as raised:
                _ensure_fixed_file_payment_allowed(
                    supabase,
                    document_id="document-id",
                    user_id="user-id",
                    error_detail="Payment required.",
                )

        self.assertEqual(raised.exception.status_code, 402)
        self.assertEqual(supabase.select_one_calls[0]["table"], "orders")

    def test_payment_status_allows_fix_when_fixed_payment_is_disabled(self) -> None:
        with patch("app.api.payments.settings.fixed_file_payment_required", False):
            response = _payment_status_response(
                {
                    "id": "order-id",
                    "document_id": "document-id",
                    "status": "pending",
                    "amount": 19000,
                    "currency": "VND",
                    "provider_order_code": "ORDER-1",
                    "checkout_url": "https://pay.example/checkout",
                    "expires_at": "2026-06-15T10:00:00+00:00",
                    "paid_at": None,
                },
                provider_status="PENDING",
            )

        self.assertTrue(response.can_fix)
        self.assertTrue(response.can_download)


if __name__ == "__main__":
    unittest.main()
