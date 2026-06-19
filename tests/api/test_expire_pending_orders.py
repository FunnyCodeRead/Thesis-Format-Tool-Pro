from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.expire_pending_orders import expire_pending_orders


class _FakeSupabase:
    def __init__(self) -> None:
        self.call = None

    def update_many(self, table, *, filters, raw_filters, payload, columns):
        self.call = {
            "table": table,
            "filters": filters,
            "raw_filters": raw_filters,
            "payload": payload,
            "columns": columns,
        }
        return [{"id": "one"}, {"id": "two"}]


class ExpirePendingOrdersTests(unittest.TestCase):
    def test_expire_pending_orders_uses_atomic_filtered_update(self) -> None:
        client = _FakeSupabase()

        with patch(
            "scripts.expire_pending_orders.get_supabase_rest_client",
            return_value=client,
        ):
            count = expire_pending_orders()

        self.assertEqual(count, 2)
        self.assertEqual(client.call["filters"], {"status": "pending"})
        self.assertEqual(client.call["payload"], {"status": "expired"})
        self.assertTrue(client.call["raw_filters"]["expires_at"].startswith("lte."))


if __name__ == "__main__":
    unittest.main()
