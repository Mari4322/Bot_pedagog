from __future__ import annotations

"""
Настройки проекта (конфигурация).

Мы храним секреты в файле `teacher_bot/.env` (он не должен попадать в GitHub),
а в коде просто читаем переменные окружения:

- BOT_TOKEN          токен Telegram-бота от BotFather
- POLZA_API_KEY      ключ доступа к polza.ai
- ADMIN_TG_ID        Telegram id администратора (кому слать ошибки)
- DB_PATH            путь к файлу SQLite (обычно database/bot.db)
- TZ                 часовой пояс (UTC+7), нужен для планировщика
- BALANCE_THRESHOLD  порог баланса polza.ai в рублях (по умолчанию 100)
                     при падении ниже — автоматически шлём предупреждение админу

Этап 2 (Продамус):
- PRODAMUS_SECRET_KEY  секретный ключ для проверки подписи вебхука Продамуса
- WEBHOOK_URL          публичный URL вашего сервера (https://your-domain.ru)
- WEBHOOK_PORT         порт, на котором слушает FastAPI (по умолчанию 8080)

Если чего-то не хватает — падаем с понятной ошибкой, чтобы это было видно сразу при запуске.
"""

from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    polza_api_key: str
    admin_tg_id: int
    db_path: str
    timezone: str
    balance_threshold: float   # порог баланса (руб.) — при падении ниже шлём предупреждение
    # ── Этап 2: Продамус ──────────────────────────────────────────────────────
    prodamus_secret_key: str   # секрет для проверки подписи вебхука (пусто → подпись не проверяется)
    webhook_url: str           # https://your-domain.ru  (пусто → платёжные ссылки не работают)
    webhook_port: int          # порт FastAPI (по умолчанию 8080)


def load_config() -> Config:
    # Загружаем переменные из .env в окружение процесса.
    load_dotenv()

    bot_token         = os.getenv("BOT_TOKEN", "").strip()
    polza_api_key     = os.getenv("POLZA_API_KEY", "").strip()
    admin_tg_id_raw   = os.getenv("ADMIN_TG_ID", "").strip()
    db_path           = os.getenv("DB_PATH", "database/bot.db").strip()
    timezone          = os.getenv("TZ", "Asia/Novosibirsk").strip()

    # Порог баланса: по умолчанию 100 руб.
    try:
        balance_threshold = float(os.getenv("BALANCE_THRESHOLD", "100").strip())
    except ValueError:
        balance_threshold = 100.0

    # Этап 2: Продамус (необязательные — без них /pay не работает, но бот запускается)
    prodamus_secret_key = os.getenv("PRODAMUS_SECRET_KEY", "").strip()
    webhook_url         = os.getenv("WEBHOOK_URL", "").strip()
    try:
        webhook_port = int(os.getenv("WEBHOOK_PORT", "8080").strip())
    except ValueError:
        webhook_port = 8080

    # Валидируем обязательные настройки
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is empty in .env")
    if not polza_api_key:
        raise RuntimeError("POLZA_API_KEY is empty in .env")
    if not admin_tg_id_raw.isdigit():
        raise RuntimeError("ADMIN_TG_ID must be an integer in .env")

    return Config(
        bot_token=bot_token,
        polza_api_key=polza_api_key,
        admin_tg_id=int(admin_tg_id_raw),
        db_path=db_path,
        timezone=timezone,
        balance_threshold=balance_threshold,
        prodamus_secret_key=prodamus_secret_key,
        webhook_url=webhook_url,
        webhook_port=webhook_port,
    )
