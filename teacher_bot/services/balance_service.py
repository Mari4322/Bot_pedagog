from __future__ import annotations

"""
Сервис проверки баланса polza.ai.

Эндпоинт: GET https://polza.ai/api/v1/balance
Заголовок: Authorization: Bearer <POLZA_API_KEY>
Ответ:    {"amount": "123.45", ...}

Используется:
  - из handlers/admin.py  — по запросу (/balance или кнопка)
  - из services/scheduler.py — автоматически каждый час
"""

import logging

import aiohttp

_log = logging.getLogger("balance_service")

BALANCE_URL = "https://polza.ai/api/v1/balance"
# Таймаут запроса к API баланса (секунды)
REQUEST_TIMEOUT = 15


async def get_balance(api_key: str) -> float:
    """
    Запрашивает текущий баланс polza.ai.

    Возвращает баланс в рублях (float).
    Бросает RuntimeError с понятным текстом если запрос не удался.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(BALANCE_URL, headers=headers) as resp:
                if resp.status == 401:
                    raise RuntimeError("Неверный API-ключ (401)")
                if resp.status == 403:
                    raise RuntimeError("Доступ запрещён (403)")
                if resp.status != 200:
                    raise RuntimeError(f"Неожиданный статус ответа: {resp.status}")

                data = await resp.json()

    except aiohttp.ClientConnectorError as e:
        _log.error("Не удалось подключиться к polza.ai для проверки баланса: %s", e)
        raise RuntimeError("Нет соединения с polza.ai") from e
    except aiohttp.ServerTimeoutError:
        _log.error("Таймаут при запросе баланса polza.ai")
        raise RuntimeError("Таймаут запроса баланса") from None

    # Ответ может содержать "amount" как строку или число
    raw = data.get("amount")
    if raw is None:
        _log.error("В ответе нет поля 'amount': %s", data)
        raise RuntimeError(f"Неожиданный формат ответа: {data}")

    try:
        return float(raw)
    except (ValueError, TypeError) as e:
        _log.error("Не удалось преобразовать баланс '%s' в число: %s", raw, e)
        raise RuntimeError(f"Неверный формат баланса: {raw}") from e
