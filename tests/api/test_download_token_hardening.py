from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi import HTTPException

from app.api.documents import _consume_download_token


class _TokenSupabase:
    def __init__(self, result):
        self.result = result
        self.call = None

    def update_maybe_one(self, table, *, filters, raw_filters, payload, columns):
        self.call = {
            "table": table,
            "filters": filters,
            "raw_filters": raw_filters,
            "payload": payload,
            "columns": columns,
        }
        return self.result


class DownloadTokenHardeningTests(unittest.TestCase):
    def test_token_consumption_is_conditional_and_atomic(self) -> None:
        client = _TokenSupabase({"id": "token-id", "used_at": "now"})
        used_at = datetime.now(timezone.utc)

        _consume_download_token(
            client,
            token_row={"id": "token-id"},
            user_id="user-id",
            used_at=used_at,
        )

        self.assertEqual(client.call["raw_filters"]["used_at"], "is.null")
        self.assertTrue(client.call["raw_filters"]["expires_at"].startswith("gt."))

    def test_already_consumed_token_is_rejected(self) -> None:
        client = _TokenSupabase(None)

        with self.assertRaises(HTTPException) as caught:
            _consume_download_token(
                client,
                token_row={"id": "token-id"},
                user_id="user-id",
                used_at=datetime.now(timezone.utc),
            )

        self.assertEqual(caught.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
