from __future__ import annotations

from datetime import datetime, timezone

from app.db.supabase_client import get_supabase_rest_client


def expire_pending_orders() -> int:
    now = datetime.now(timezone.utc).isoformat()
    rows = get_supabase_rest_client().update_many(
        "orders",
        filters={"status": "pending"},
        raw_filters={"expires_at": f"lte.{now}"},
        payload={"status": "expired"},
        columns="id",
    )
    return len(rows)


if __name__ == "__main__":
    count = expire_pending_orders()
    print(f"Expired pending orders: {count}")
