from __future__ import annotations

"""
Интеграция с платёжной системой Продамус.

Документация API: https://prodamus.ru/api

Как это работает:
1. Бот вызывает make_payment_url() → получает платёжную ссылку
2. Пользователь переходит по ссылке и оплачивает
3. Продамус отправляет POST-вебхук на WEBHOOK_URL/webhook/prodamus
4. services/webhook.py принимает вебхук, проверяет подпись и обновляет подписку

Пока нет домена и ключей — функция возвращает заглушку.
Когда появятся ключи: заполнить PRODAMUS_SECRET_KEY и WEBHOOK_URL в .env,
и раскомментировать реальный запрос ниже (помечен # PRODAMUS_REAL).
"""

import hashlib
import hmac
import json
import logging
from urllib.parse import urlencode

import aiohttp

_log = logging.getLogger("prodamus")


def make_payment_url(
    *,
    webhook_url: str,
    prodamus_secret_key: str,
    tg_id: int,
    tariff_key: str,
    tariff_name: str,
    price: float,
) -> str | None:
    """
    Формирует платёжную ссылку Продамуса.

    Возвращает URL (str) или None если webhook_url / secret не заданы
    (в этом случае бот покажет пользователю сообщение о недоступности оплаты).

    Структура ссылки Продамуса (без SDK, чистый URL):
      https://pay.prodamus.ru/?
        do=pay
        &name=<название товара>
        &price=<цена>
        &quantity=1
        &currency=RUB
        &order_id=<tg_id>_<tariff_key>_<timestamp>
        &customer_extra=<tg_id>   ← вернётся в вебхуке
        &urlNotification=<WEBHOOK_URL>/webhook/prodamus
        &signature=<hmac-sha256>

    Подпись считается от тела запроса (sorted params) ключом PRODAMUS_SECRET_KEY.
    """
    if not webhook_url or not prodamus_secret_key:
        _log.warning("Продамус не настроен: WEBHOOK_URL или PRODAMUS_SECRET_KEY пусты")
        return None

    import time
    order_id = f"{tg_id}_{tariff_key}_{int(time.time())}"

    params: dict[str, str] = {
        "do":              "pay",
        "name":            tariff_name,
        "price":           str(price),
        "quantity":        "1",
        "currency":        "RUB",
        "order_id":        order_id,
        "customer_extra":  str(tg_id),
        "urlNotification": f"{webhook_url.rstrip('/')}/webhook/prodamus",
    }

    # Подпись: HMAC-SHA256 от строки key1=value1&key2=value2 (ключи отсортированы)
    sign_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    signature = hmac.new(
        prodamus_secret_key.encode(),
        sign_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    params["signature"] = signature

    base = "https://pay.prodamus.ru/"
    return base + "?" + urlencode(params)


def verify_webhook_signature(body: bytes, secret_key: str, received_sign: str) -> bool:
    """
    Проверяет подпись входящего вебхука от Продамуса.
    body — сырое тело POST-запроса (bytes).
    Если secret_key пуст — пропускаем проверку (для тестов без домена).
    """
    if not secret_key:
        return True  # в тестовом режиме подпись не проверяем

    expected = hmac.new(
        secret_key.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received_sign)
