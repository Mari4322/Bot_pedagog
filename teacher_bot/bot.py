from __future__ import annotations

"""
Точка входа в Telegram-бота.

Задачи этого файла:
- загрузить настройки из `.env` (см. `config.py`)
- подключиться к SQLite (см. `database/db.py`)
- создать таблицы при первом запуске (см. `database/models.py`)
- зарегистрировать хендлеры (папка `handlers/`)
- положить общие зависимости в контекст `Dispatcher`:
  - db: подключение к SQLite
  - ai_client: клиент polza.ai (OpenAI SDK с подменённым base_url)
  - admin_tg_id: TG id администратора для уведомлений об ошибках
- запустить планировщик (сброс daily_count по расписанию)
- запустить polling (приём апдейтов от Telegram)
"""

import asyncio

import uvicorn

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeDefault

from config import load_config
from database.db import connect
from database.models import init_db
from services.ai_service import make_client
from services.scheduler import start_scheduler
from services import webhook as webhook_service

from handlers.start import router as start_router
from handlers.dialog import router as dialog_router
from handlers.generate import router as generate_router
from handlers.cabinet import router as cabinet_router
from handlers.admin import router as admin_router


async def main() -> None:
    # 1) Загружаем секреты/настройки из окружения.
    cfg = load_config()

    # 2) Поднимаем соединение с базой SQLite и убеждаемся, что таблицы существуют.
    db = await connect(cfg.db_path)
    await init_db(db)

    # 3) Создаём объект бота. ParseMode.HTML нужен, потому что в сообщениях
    # мы используем <b>...</b> для жирного текста (как в ТЗ).
    bot = Bot(
        token=cfg.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # 4) Dependency Injection (простой способ): кладём общие объекты в dp.
    # После этого в хендлерах можно просто добавить аргументы `db`, `ai_client`,
    # `admin_tg_id` в сигнатуру функции, и aiogram сам подставит их из dp.
    dp["db"] = db
    dp["ai_client"] = make_client(cfg.polza_api_key)
    dp["admin_tg_id"] = cfg.admin_tg_id
    dp["polza_api_key"] = cfg.polza_api_key          # нужен для /balance в admin хендлере
    dp["balance_threshold"] = cfg.balance_threshold  # порог для отображения предупреждения
    dp["prodamus_secret_key"] = cfg.prodamus_secret_key  # для генерации платёжных ссылок
    dp["webhook_url"] = cfg.webhook_url                  # публичный URL сервера

    # 5) Подключаем роутеры (разделение логики по файлам).
    dp.include_router(start_router)
    dp.include_router(dialog_router)
    dp.include_router(generate_router)
    dp.include_router(cabinet_router)
    dp.include_router(admin_router)

    # 6) Запускаем планировщик задач по часовому поясу UTC+7 (настраивается в .env).
    # Пока в “этапе 1” используются только:
    # - 00:00 сброс daily_count
    # - 00:01 отключение доступа тем, у кого подписка истекла и auto_renew=False
    start_scheduler(
        bot=bot,
        db=db,
        timezone=cfg.timezone,
        admin_tg_id=cfg.admin_tg_id,
        polza_api_key=cfg.polza_api_key,
        balance_threshold=cfg.balance_threshold,
    )

    # 7) Регистрируем команды в меню Telegram (видны всем пользователям).
    await bot.set_my_commands(
        commands=[
            BotCommand(command="start",      description="Начать / вернуться в главное меню"),
            BotCommand(command="help",       description="Краткая инструкция по боту"),
            BotCommand(command="cabinet",    description="Личный кабинет (тариф, лимиты)"),
            BotCommand(command="pay",        description="Оплатить или сменить тариф"),
            BotCommand(command="cancel_sub", description="Отменить подписку"),
        ],
        scope=BotCommandScopeDefault(),
    )

    # 8) Инициализируем FastAPI-сервер для вебхуков Продамуса и запускаем параллельно.
    webhook_service.setup(
        bot=bot,
        db=db,
        prodamus_secret_key=cfg.prodamus_secret_key,
    )
    uvicorn_config = uvicorn.Config(
        app=webhook_service.app,
        host="0.0.0.0",
        port=cfg.webhook_port,
        log_level="warning",
        loop="none",          # используем уже запущенный asyncio loop
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    # 9) Запускаем polling и uvicorn конкурентно в одном event loop.
    await asyncio.gather(
        dp.start_polling(bot),
        uvicorn_server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())

