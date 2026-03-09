from __future__ import annotations

import csv
import io
from typing import Any

import aiosqlite


def _to_csv_bytes(rows: list[dict[str, Any]], fieldnames: list[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k) for k in fieldnames})
    return buf.getvalue().encode("utf-8-sig")


async def export_users(db: aiosqlite.Connection) -> tuple[str, bytes]:
    rows = await db.execute_fetchall(
        """
        SELECT u.tg_id, u.username, u.registered_at, s.tariff, u.is_active
        FROM users u
        LEFT JOIN subscriptions s ON s.tg_id = u.tg_id
        ORDER BY u.registered_at DESC
        """
    )
    dict_rows = [dict(r) for r in rows]
    fields = ["tg_id", "username", "registered_at", "tariff", "is_active"]
    return ("users.csv", _to_csv_bytes(dict_rows, fields))


async def export_children(db: aiosqlite.Connection) -> tuple[str, bytes]:
    rows = await db.execute_fetchall(
        """
        SELECT
            c.parent_tg_id AS parent_tg_id,
            c.name AS child_name,
            c.age AS child_age,
            GROUP_CONCAT(h.hobby, '; ') AS hobbies
        FROM children c
        LEFT JOIN hobbies h ON h.child_id = c.id
        GROUP BY c.id
        ORDER BY c.id DESC
        """
    )
    dict_rows = [dict(r) for r in rows]
    fields = ["parent_tg_id", "child_name", "child_age", "hobbies"]
    return ("children.csv", _to_csv_bytes(dict_rows, fields))


async def export_logs(db: aiosqlite.Connection) -> tuple[str, bytes]:
    rows = await db.execute_fetchall(
        """
        SELECT
            id, tg_id, child_name, child_age, hobby_used, topic, anxiety_level,
            tokens_used, cost, model_used, created_at
        FROM requests_log
        ORDER BY id DESC
        """
    )
    dict_rows = [dict(r) for r in rows]
    fields = [
        "id",
        "tg_id",
        "child_name",
        "child_age",
        "hobby_used",
        "topic",
        "anxiety_level",
        "tokens_used",
        "cost",
        "model_used",
        "created_at",
    ]
    return ("logs.csv", _to_csv_bytes(dict_rows, fields))

