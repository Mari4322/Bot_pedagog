from __future__ import annotations

import aiosqlite


async def init_db(db: aiosqlite.Connection) -> None:
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            tg_id INTEGER PRIMARY KEY,
            username TEXT,
            registered_at TEXT NOT NULL,
            daily_limit INTEGER,
            daily_count INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_admin INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS children (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_tg_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            age INTEGER,
            FOREIGN KEY(parent_tg_id) REFERENCES users(tg_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS hobbies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            child_id INTEGER NOT NULL,
            hobby TEXT NOT NULL,
            FOREIGN KEY(child_id) REFERENCES children(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            tg_id INTEGER PRIMARY KEY,
            tariff TEXT NOT NULL,
            paid_at TEXT,
            next_payment_at TEXT,
            auto_renew INTEGER NOT NULL DEFAULT 0,
            total_cost REAL NOT NULL DEFAULT 0,
            FOREIGN KEY(tg_id) REFERENCES users(tg_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS requests_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER NOT NULL,
            child_name TEXT,
            child_age INTEGER,
            hobby_used TEXT,
            topic TEXT,
            anxiety_level INTEGER,
            response TEXT,
            tokens_used INTEGER,
            cost REAL,
            model_used TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(tg_id) REFERENCES users(tg_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        INSERT OR IGNORE INTO settings(key, value)
        VALUES ('current_model', 'openai/gpt-4o-mini');
        """
    )
    await db.commit()

