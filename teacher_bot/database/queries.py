from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

NEW_USER_FREE_REQUESTS = 10


# ─── вспомогательные функции ───────────────────────────────────────────────

async def _fetchone(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> Any | None:
    async with db.execute(sql, params) as cur:
        cur.row_factory = aiosqlite.Row
        return await cur.fetchone()

async def _fetchall(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> list:
    async with db.execute(sql, params) as cur:
        cur.row_factory = aiosqlite.Row
        return await cur.fetchall()


# ─── вспомогательные утилиты ───────────────────────────────────────────────

@dataclass(frozen=True)
class AccessState:
    is_active: bool
    daily_limit: int | None
    daily_count: int

    @property
    def can_generate(self) -> bool:
        if not self.is_active:
            return False
        if self.daily_limit is None:
            return True
        return self.daily_count < self.daily_limit


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plus_30d_iso(now: datetime | None = None) -> str:
    base = now or datetime.now(timezone.utc)
    return (base + timedelta(days=30)).isoformat()


# ─── settings ──────────────────────────────────────────────────────────────

async def get_setting(db: aiosqlite.Connection, key: str) -> str | None:
    row = await _fetchone(db, "SELECT value FROM settings WHERE key = ?", (key,))
    return row[0] if row else None


async def set_setting(db: aiosqlite.Connection, key: str, value: str) -> None:
    await db.execute(
        """
        INSERT INTO settings(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )
    await db.commit()


# ─── users ─────────────────────────────────────────────────────────────────

async def ensure_user(db: aiosqlite.Connection, tg_id: int, username: str | None, is_bot: bool = False) -> bool:
    """
    Регистрирует пользователя при первом визите.
    Returns True если пользователь только что создан (первый визит).

    is_bot=True → не создаём запись, возвращаем False (бот не регистрируется).
    """
    if is_bot:
        return False

    existed = await _fetchone(db, "SELECT 1 FROM users WHERE tg_id = ? LIMIT 1", (tg_id,))
    if existed:
        await db.execute("UPDATE users SET username = ? WHERE tg_id = ?", (username, tg_id))
        await db.commit()
        return False

    await db.execute(
        """
        INSERT INTO users(tg_id, username, registered_at, daily_limit, daily_count, is_active, is_admin)
        VALUES (?, ?, ?, ?, 0, 1, 0)
        """,
        (tg_id, username, _now_iso(), NEW_USER_FREE_REQUESTS),
    )
    await db.execute(
        """
        INSERT INTO subscriptions(tg_id, tariff, paid_at, next_payment_at, auto_renew, total_cost)
        VALUES (?, 'free', NULL, NULL, 0, 0)
        """,
        (tg_id,),
    )
    await db.commit()
    return True


async def get_user(db: aiosqlite.Connection, tg_id: int) -> dict[str, Any] | None:
    row = await _fetchone(db, "SELECT * FROM users WHERE tg_id = ?", (tg_id,))
    return dict(row) if row else None


async def set_admin(db: aiosqlite.Connection, tg_id: int, is_admin: bool) -> None:
    await db.execute("UPDATE users SET is_admin = ? WHERE tg_id = ?", (1 if is_admin else 0, tg_id))
    await db.commit()


async def get_access_state(db: aiosqlite.Connection, tg_id: int) -> AccessState:
    row = await _fetchone(
        db,
        "SELECT is_active, daily_limit, daily_count, is_admin FROM users WHERE tg_id = ?",
        (tg_id,),
    )
    if not row:
        return AccessState(is_active=False, daily_limit=0, daily_count=0)
    if bool(row["is_admin"]):
        return AccessState(is_active=True, daily_limit=None, daily_count=0)
    return AccessState(
        is_active=bool(row["is_active"]),
        daily_limit=row["daily_limit"],
        daily_count=int(row["daily_count"]),
    )

async def increment_daily_count(db: aiosqlite.Connection, tg_id: int) -> None:
    await db.execute("UPDATE users SET daily_count = daily_count + 1 WHERE tg_id = ?", (tg_id,))
    await db.commit()


async def reset_daily_counts(db: aiosqlite.Connection) -> None:
    await db.execute("UPDATE users SET daily_count = 0")
    await db.commit()


# ─── subscriptions ─────────────────────────────────────────────────────────

async def add_subscription_cost(db: aiosqlite.Connection, tg_id: int, cost_rub: float) -> None:
    await db.execute(
        "UPDATE subscriptions SET total_cost = total_cost + ? WHERE tg_id = ?",
        (float(cost_rub or 0), tg_id),
    )
    await db.commit()


async def get_subscription(db: aiosqlite.Connection, tg_id: int) -> dict[str, Any] | None:
    row = await _fetchone(db, "SELECT * FROM subscriptions WHERE tg_id = ?", (tg_id,))
    return dict(row) if row else None


# ─── children ──────────────────────────────────────────────────────────────

async def list_children(db: aiosqlite.Connection, parent_tg_id: int) -> list[dict[str, Any]]:
    rows = await _fetchall(
        db,
        "SELECT id, name, age FROM children WHERE parent_tg_id = ? ORDER BY id ASC",
        (parent_tg_id,),
    )
    return [dict(r) for r in rows]


async def add_child(db: aiosqlite.Connection, parent_tg_id: int, name: str) -> int:
    cur = await db.execute(
        "INSERT INTO children(parent_tg_id, name, age) VALUES (?, ?, NULL)",
        (parent_tg_id, name.strip()),
    )
    await db.commit()
    return int(cur.lastrowid)


async def rename_child(db: aiosqlite.Connection, child_id: int, parent_tg_id: int, new_name: str) -> None:
    await db.execute(
        "UPDATE children SET name = ? WHERE id = ? AND parent_tg_id = ?",
        (new_name.strip(), child_id, parent_tg_id),
    )
    await db.commit()


async def set_child_age(db: aiosqlite.Connection, child_id: int, parent_tg_id: int, age: int) -> None:
    await db.execute(
        "UPDATE children SET age = ? WHERE id = ? AND parent_tg_id = ?",
        (int(age), child_id, parent_tg_id),
    )
    await db.commit()


async def get_child(db: aiosqlite.Connection, child_id: int, parent_tg_id: int) -> dict[str, Any] | None:
    row = await _fetchone(
        db,
        "SELECT id, parent_tg_id, name, age FROM children WHERE id = ? AND parent_tg_id = ?",
        (child_id, parent_tg_id),
    )
    return dict(row) if row else None


# ─── hobbies ───────────────────────────────────────────────────────────────

async def list_hobbies(db: aiosqlite.Connection, child_id: int, parent_tg_id: int) -> list[dict[str, Any]]:
    rows = await _fetchall(
        db,
        """
        SELECT h.id, h.hobby
        FROM hobbies h
        JOIN children c ON c.id = h.child_id
        WHERE h.child_id = ? AND c.parent_tg_id = ?
        ORDER BY h.id ASC
        """,
        (child_id, parent_tg_id),
    )
    return [dict(r) for r in rows]


async def add_hobby(db: aiosqlite.Connection, child_id: int, parent_tg_id: int, hobby: str) -> int | None:
    child = await get_child(db, child_id, parent_tg_id)
    if not child:
        return None
    cur = await db.execute(
        "INSERT INTO hobbies(child_id, hobby) VALUES (?, ?)",
        (child_id, hobby.strip()),
    )
    await db.commit()
    return int(cur.lastrowid)


async def delete_hobby(db: aiosqlite.Connection, hobby_id: int, parent_tg_id: int) -> None:
    await db.execute(
        """
        DELETE FROM hobbies
        WHERE id = ?
          AND child_id IN (SELECT id FROM children WHERE parent_tg_id = ?)
        """,
        (hobby_id, parent_tg_id),
    )
    await db.commit()


# ─── requests_log ──────────────────────────────────────────────────────────

async def log_request(
    db: aiosqlite.Connection,
    tg_id: int,
    child_name: str,
    child_age: int | None,
    hobby_used: str,
    topic: str,
    anxiety_level: int,
    response_text: str,
    tokens_used: int | None,
    cost: float | None,
    model_used: str | None,
) -> None:
    await db.execute(
        """
        INSERT INTO requests_log(
            tg_id, child_name, child_age, hobby_used, topic, anxiety_level,
            response, tokens_used, cost, model_used, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tg_id, child_name, child_age, hobby_used, topic, anxiety_level,
            response_text, tokens_used, cost, model_used, _now_iso(),
        ),
    )
    await db.commit()


# ─── scheduler tasks ───────────────────────────────────────────────────────

async def deactivate_expired_without_renew(db: aiosqlite.Connection, now_iso: str | None = None) -> int:
    now = now_iso or _now_iso()
    cur = await db.execute(
        """
        UPDATE users
        SET is_active = 0
        WHERE tg_id IN (
            SELECT s.tg_id
            FROM subscriptions s
            WHERE s.next_payment_at IS NOT NULL
              AND s.next_payment_at <= ?
              AND s.auto_renew = 0
        )
        """,
        (now,),
    )
    await db.commit()
    return cur.rowcount


async def get_users_expiring_tomorrow(
    db: aiosqlite.Connection,
    now_iso: str | None = None,
) -> list[dict]:
    """
    Возвращает список пользователей, у которых next_payment_at попадает
    в окно [сейчас + 23 часа, сейчас + 25 часов] — то есть «ровно через 1 день».
    Широкое окно (±1 час) защищает от накопленного drift планировщика.
    """
    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
    window_start = (now + timedelta(hours=23)).isoformat()
    window_end   = (now + timedelta(hours=25)).isoformat()

    rows = await _fetchall(
        db,
        """
        SELECT u.tg_id, s.tariff, s.next_payment_at
        FROM subscriptions s
        JOIN users u ON u.tg_id = s.tg_id
        WHERE s.next_payment_at IS NOT NULL
          AND s.next_payment_at >= ?
          AND s.next_payment_at <= ?
          AND u.is_active = 1
        """,
        (window_start, window_end),
    )
    return [dict(r) for r in rows]
