"""
Бэкап базы данных на S3-хранилище Beget.

Запуск вручную:
    python3 utils/backup.py

Запуск через crontab (каждый день в 03:00):
    0 3 * * * cd /home/bot/teacher_bot && /home/bot/teacher_bot/venv/bin/python3 utils/backup.py >> /home/bot/backups/backup.log 2>&1

Политика хранения:
  - Все бэкапы за последние 2 месяца — хранятся полностью
  - Старше 2 месяцев — оставляем только первый и последний день каждого месяца
  - Остальные удаляются
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

# ─── загрузка .env ─────────────────────────────────────────────────────────
# Ищем .env в родительской папке (teacher_bot/.env)
_BASE = Path(__file__).resolve().parent.parent
load_dotenv(_BASE / ".env")

# ─── логирование ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_log = logging.getLogger("backup")

# ─── конфигурация ──────────────────────────────────────────────────────────
S3_ENDPOINT    = os.getenv("S3_ENDPOINT",    "https://s3.ru1.storage.beget.cloud")
S3_BUCKET      = os.getenv("S3_BUCKET",      "")
S3_ACCESS_KEY  = os.getenv("S3_ACCESS_KEY",  "")
S3_SECRET_KEY  = os.getenv("S3_SECRET_KEY",  "")
S3_PREFIX      = os.getenv("S3_PREFIX",      "backups/")   # папка внутри бакета

DB_PATH        = Path(os.getenv("DB_PATH", _BASE / "database" / "bot.db"))

# Сколько полных месяцев хранить все бэкапы
FULL_RETENTION_MONTHS = 2


def _s3_client():
    """Создаёт boto3-клиент для Beget S3."""
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )


def _backup_key(dt: datetime) -> str:
    """Имя файла в S3: backups/bot_2026-04-01.db"""
    date_str = dt.strftime("%Y-%m-%d")
    return f"{S3_PREFIX}bot_{date_str}.db"


def upload_backup(client, db_path: Path) -> str:
    """Загружает db_path в S3, возвращает ключ объекта."""
    now = datetime.now(timezone.utc)
    key = _backup_key(now)

    _log.info("Загружаю %s → s3://%s/%s", db_path, S3_BUCKET, key)
    client.upload_file(str(db_path), S3_BUCKET, key)
    _log.info("Загрузка завершена.")
    return key


def rotate_backups(client) -> None:
    """
    Применяет политику хранения:
    - Последние 2 месяца: все бэкапы
    - Старше 2 месяцев: только первый и последний день каждого месяца
    """
    now        = datetime.now(timezone.utc)
    keep_all_from = now - timedelta(days=FULL_RETENTION_MONTHS * 30)

    # Получаем список всех объектов в папке backups/
    paginator = client.get_paginator("list_objects_v2")
    pages     = paginator.paginate(Bucket=S3_BUCKET, Prefix=S3_PREFIX)

    all_keys: list[tuple[str, datetime]] = []
    for page in pages:
        for obj in page.get("Contents", []):
            key  = obj["Key"]
            name = Path(key).name  # bot_2026-04-01.db
            # Парсим дату из имени файла
            try:
                date_str = name.removeprefix("bot_").removesuffix(".db")
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                all_keys.append((key, dt))
            except ValueError:
                _log.warning("Пропускаю файл с неизвестным именем: %s", key)

    if not all_keys:
        _log.info("Бэкапов в S3 не найдено, ротация не нужна.")
        return

    _log.info("Всего бэкапов в S3: %d", len(all_keys))

    # Группируем старые бэкапы (старше 2 месяцев) по месяцам
    old_keys = [(k, dt) for k, dt in all_keys if dt < keep_all_from]

    # По каждому месяцу оставляем только первый и последний день
    by_month: dict[str, list[tuple[str, datetime]]] = {}
    for key, dt in old_keys:
        month_key = dt.strftime("%Y-%m")
        by_month.setdefault(month_key, []).append((key, dt))

    to_delete: list[str] = []
    for month, entries in by_month.items():
        entries_sorted = sorted(entries, key=lambda x: x[1])
        # Оставляем первый и последний
        keep = {entries_sorted[0][0], entries_sorted[-1][0]}
        for key, _ in entries_sorted:
            if key not in keep:
                to_delete.append(key)

    if not to_delete:
        _log.info("Нечего удалять — все старые бэкапы уже в норме.")
        return

    _log.info("Удаляю %d устаревших бэкапов...", len(to_delete))
    # S3 позволяет удалять до 1000 объектов за раз
    chunk_size = 1000
    for i in range(0, len(to_delete), chunk_size):
        chunk = to_delete[i : i + chunk_size]
        client.delete_objects(
            Bucket=S3_BUCKET,
            Delete={"Objects": [{"Key": k} for k in chunk]},
        )
        _log.info("Удалено %d объектов.", len(chunk))

    _log.info("Ротация завершена.")


def main() -> None:
    # Проверка конфигурации
    missing = [v for v in ("S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY") if not os.getenv(v)]
    if missing:
        _log.error("Не заданы переменные окружения: %s", ", ".join(missing))
        sys.exit(1)

    if not DB_PATH.exists():
        _log.error("База данных не найдена: %s", DB_PATH)
        sys.exit(1)

    client = _s3_client()

    try:
        upload_backup(client, DB_PATH)
        rotate_backups(client)
        _log.info("Бэкап успешно завершён.")
    except (BotoCoreError, ClientError) as e:
        _log.error("Ошибка S3: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
