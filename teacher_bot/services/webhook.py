from __future__ import annotations

"""
FastAPI-сервер для приёма вебхуков от Продамуса.

Запускается параллельно с Telegram-ботом в том же asyncio event loop (см. bot.py).

Эндпоинт: POST /webhook/prodamus
  — проверяет подпись запроса
  — извлекает tg_id и tariff из тела
  — обновляет подписку в БД
  — отправляет пользователю уведомление об успешной оплате через бота

Пока нет домена: сервер запускается на порту WEBHOOK_PORT (по умолчанию 8080),
но вебхук до него не доходит. Когда появится домен+SSL — Продамус начнёт слать запросы.
"""

import hashlib
import hmac
import json
import logging

from fastapi import FastAPI, Request, Response, status
from aiogram import Bot

from database.queries import update_subscription
from services.prodamus import verify_webhook_signature
from tariffs import TARIFFS

_log = logging.getLogger("webhook")

# Эти объекты инжектируются из bot.py перед запуском uvicorn
_bot: Bot | None = None
_db = None
_prodamus_secret_key: str = ""


def setup(bot: Bot, db, prodamus_secret_key: str) -> None:
    """Вызывается из bot.py после создания объектов bot и db."""
    global _bot, _db, _prodamus_secret_key
    _bot = bot
    _db = db
    _prodamus_secret_key = prodamus_secret_key


app = FastAPI(docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/webhook/prodamus")
async def prodamus_webhook(request: Request) -> Response:
    """
    Принимает уведомление об успешной оплате от Продамуса.

    Продамус шлёт POST с Content-Type: application/x-www-form-urlencoded
    или application/json — поддерживаем оба варианта.

    Ожидаемые поля:
      payment_status  — "success"
      customer_extra  — tg_id пользователя
      order_id        — "<tg_id>_<tariff_key>_<timestamp>"
      signature       — HMAC-SHA256 подпись (если настроен secret_key)
    """
    body = await request.body()

    # Проверяем подпись
    received_sign = request.headers.get("X-Signature", "") or request.query_params.get("signature", "")
    if not verify_webhook_signature(body, _prodamus_secret_key, received_sign):
        _log.warning("Webhook: неверная подпись")
        return Response(status_code=status.HTTP_403_FORBIDDEN, content="Invalid signature")

    # Парсим тело
    content_type = request.headers.get("content-type", "")
    try:
        if "json" in content_type:
            data: dict = await request.json()
        else:
            from urllib.parse import parse_qs
            parsed = parse_qs(body.decode())
            data = {k: v[0] for k, v in parsed.items()}
    except Exception as e:
        _log.error("Webhook: ошибка парсинга тела: %s", e)
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content="Bad body")

    _log.info("Webhook получен: %s", data)

    # Проверяем статус платежа
    payment_status = data.get("payment_status", "")
    if payment_status != "success":
        _log.info("Webhook: payment_status=%s — игнорируем", payment_status)
        return Response(content="ok")

    # Извлекаем tg_id и tariff_key из order_id: "<tg_id>_<tariff_key>_<timestamp>"
    order_id = data.get("order_id", "")
    customer_extra = data.get("customer_extra", "")

    try:
        tg_id = int(customer_extra or order_id.split("_")[0])
    except (ValueError, IndexError):
        _log.error("Webhook: не удалось извлечь tg_id из order_id=%s customer_extra=%s", order_id, customer_extra)
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content="Bad tg_id")

    try:
        tariff_key = order_id.split("_")[1]
    except IndexError:
        _log.error("Webhook: не удалось извлечь tariff_key из order_id=%s", order_id)
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content="Bad tariff")

    tariff = TARIFFS.get(tariff_key)
    if not tariff:
        _log.error("Webhook: неизвестный тариф %s", tariff_key)
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content="Unknown tariff")

    # Обновляем подписку в БД
    try:
        await update_subscription(
            _db,
            tg_id=tg_id,
            tariff=tariff_key,
            daily_limit=tariff.daily_limit,
        )
        _log.info("Webhook: подписка обновлена tg_id=%d tariff=%s", tg_id, tariff_key)
    except Exception as e:
        _log.exception("Webhook: ошибка обновления подписки tg_id=%d: %s", tg_id, e)
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content="DB error")

    # Уведомляем пользователя
    if _bot:
        try:
            from datetime import datetime
            from database.queries import get_subscription
            # Получаем актуальную дату из БД после обновления
            sub = await get_subscription(_db, tg_id)
            if sub and sub.get("next_payment_at"):
                next_pay_dt = datetime.fromisoformat(sub["next_payment_at"])
                next_pay = next_pay_dt.strftime("%d.%m.%Y")
            else:
                next_pay = "—"
            
            await _bot.send_message(
                tg_id,
                f"✅ <b>Оплата прошла успешно!</b>\n\n"
                f"📦 Тариф: <b>{tariff.name}</b>\n"
                f"📅 Следующий платёж: <b>{next_pay}</b>\n\n"
                f"Используйте /cabinet чтобы посмотреть статус подписки.",
            )
        except Exception as e:
            _log.warning("Webhook: не удалось отправить уведомление пользователю %d: %s", tg_id, e)

    return Response(content="ok")
