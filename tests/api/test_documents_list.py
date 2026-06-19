from __future__ import annotations

import unittest
from unittest.mock import patch

from app.api.documents import list_documents
from app.schemas.auth import CurrentUser


class _FakeSupabaseClient:
    def __init__(self) -> None:
        self.call = None

    def select_many(self, table, *, filters, columns, order=None, limit=None):
        self.call = {
            "table": table,
            "filters": filters,
            "columns": columns,
            "order": order,
            "limit": limit,
        }
        return [
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "document_type": "do_an_tot_nghiep",
                "original_filename": "do-an.docx",
                "status": "analyzed",
                "total_findings": 12,
                "error_count": 2,
                "warning_count": 10,
                "created_at": "2026-06-12T08:00:00+00:00",
                "annotated_at": None,
                "fixed_at": None,
            }
        ]


class DocumentListTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_documents_filters_by_current_user_and_limits_rows(self) -> None:
        client = _FakeSupabaseClient()
        current_user = CurrentUser(
            user_id="22222222-2222-4222-8222-222222222222",
            email="user@example.com",
            role="authenticated",
        )

        with patch("app.api.documents.get_supabase_rest_client", return_value=client):
            response = await list_documents(limit=10, current_user=current_user)

        self.assertEqual(client.call["table"], "documents")
        self.assertEqual(
            client.call["filters"],
            {"user_id": "22222222-2222-4222-8222-222222222222"},
        )
        self.assertEqual(client.call["order"], "created_at.desc")
        self.assertEqual(client.call["limit"], 10)
        self.assertEqual(len(response.documents), 1)
        self.assertEqual(response.documents[0].document_id, "11111111-1111-4111-8111-111111111111")
        self.assertEqual(response.documents[0].total_findings, 12)


if __name__ == "__main__":
    unittest.main()
