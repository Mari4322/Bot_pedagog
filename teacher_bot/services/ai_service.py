from __future__ import annotations

"""
Сервис взаимодействия с polza.ai (OpenAI-совместимый API).

Стратегия повторных попыток (по ТЗ):
  429               → повтор через 5 сек  (до MAX_RETRIES раз)
  502 / 503         → повтор через 10 сек (до MAX_RETRIES раз)
  408               → НЕ повторяем, бросаем TimeoutAPIError (сообщение пользователю)
  401 / 402         → НЕ повторяем, бросаем как есть (лог + уведомление админу)
  500               → НЕ повторяем, бросаем как есть (лог + сообщение пользователю)
  любая другая      → бросаем как есть

При ЛЮБОЙ ошибке счётчик daily_count НЕ увеличивается (контролируется в generate.py).
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from openai import AsyncOpenAI, APIConnectionError, APIStatusError, RateLimitError

_log = logging.getLogger("ai_service")

# Максимальное число повторных попыток для 429 / 502 / 503
MAX_RETRIES = 3

# Задержки строго по ТЗ
RETRY_DELAY_429      = 5    # сек — превышен лимит запросов
RETRY_DELAY_502_503  = 10   # сек — провайдер / сервис недоступен


# ─── Кастомные исключения (для удобной обработки в generate.py) ────────────

class TimeoutAPIError(Exception):
    """Код 408 — таймаут запроса."""


class ServerAPIError(Exception):
    """Код 500 — ошибка сервера."""
    def __init__(self, message: str = ""):
        super().__init__(message)
        self.message = message


# ─── Вспомогательные функции ───────────────────────────────────────────────

def get_prompt() -> str:
    """Читаем системный промпт из prompt.txt (рядом с корнем teacher_bot/)."""
    path = Path(__file__).resolve().parent.parent / "prompt.txt"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def make_client(polza_api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(base_url="https://polza.ai/api/v1", api_key=polza_api_key)


# ─── Результат успешного запроса ───────────────────────────────────────────

@dataclass(frozen=True)
class AIResult:
    text: str
    tokens_used: int | None
    cost_rub: float | None
    model_used: str | None


# ─── Сборка user-сообщения ─────────────────────────────────────────────────

def _build_user_message(
    child_name: str,
    child_age: int,
    hobby: str,
    topic: str,
    anxiety_level: int,
    comment: str | None = None,
) -> str:
    parts = [
        f"Ребёнок: {child_name}, {child_age} лет",
        f"Увлечение: {hobby}",
        f"Тема для объяснения: {topic}",
        f"Уровень тревожности ребёнка по этой теме: {anxiety_level} из 10",
    ]
    if comment:
        parts.append(f"Комментарий родителя: {comment}")
    return "\n".join(parts).strip()


# ─── Основная функция генерации ────────────────────────────────────────────

async def generate_response(
    *,
    client: AsyncOpenAI,
    model: str,
    child_name: str,
    child_age: int,
    hobby: str,
    topic: str,
    anxiety_level: int,
    comment: str | None = None,
    temperature: float = 0.8,
    max_tokens: int = 2000,
) -> AIResult:
    """
    Отправляет запрос к polza.ai и возвращает AIResult.

    Коды ошибок и поведение:
      200           → возвращаем AIResult
      408           → бросаем TimeoutAPIError (без повтора)
      429           → повтор через 5 сек, до MAX_RETRIES раз; потом бросаем RateLimitError
      500           → бросаем ServerAPIError (без повтора)
      502 / 503     → повтор через 10 сек, до MAX_RETRIES раз; потом бросаем APIStatusError
      401 / 402     → бросаем APIStatusError (без повтора, логируется в generate.py)
      прочие 4xx    → бросаем APIStatusError (без повтора)
    """
    _log.debug("generate_response model=%s base_url=%s", model, client.base_url)

    user_message = _build_user_message(
        child_name=child_name,
        child_age=child_age,
        hobby=hobby,
        topic=topic,
        anxiety_level=anxiety_level,
        comment=comment,
    )

    attempt = 0

    while True:
        try:
            _log.debug("Attempt %d — sending request to polza.ai", attempt)

            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": get_prompt()},
                    {"role": "user",   "content": user_message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body={
                    "provider": {
                        "allow_fallbacks": True,
                        "sort": "price",
                    }
                },
            )

            usage      = getattr(resp, "usage", None)
            tokens     = getattr(usage, "total_tokens", None) if usage else None
            cost_rub   = getattr(usage, "cost_rub", None)     if usage else None

            _log.debug("Success tokens=%s cost_rub=%s", tokens, cost_rub)

            return AIResult(
                text=resp.choices[0].message.content,
                tokens_used=tokens,
                cost_rub=cost_rub,
                model_used=getattr(resp, "model", None),
            )

        # ── 429: превышен лимит — повтор через 5 сек ─────────────────────
        except RateLimitError as e:
            _log.warning("RateLimitError (429) attempt=%d: %s", attempt, e)
            if attempt < MAX_RETRIES:
                attempt += 1
                await asyncio.sleep(RETRY_DELAY_429)
                continue
            _log.error("RateLimitError: исчерпаны попытки (%d)", MAX_RETRIES)
            raise

        except APIStatusError as e:
            code = e.status_code

            # ── 408: таймаут — без повтора, кастомное исключение ─────────
            if code == 408:
                _log.warning("Timeout (408) от polza.ai: %s", e.message)
                raise TimeoutAPIError() from e

            # ── 500: ошибка сервера — без повтора, кастомное исключение ──
            if code == 500:
                _log.error("Server error (500) от polza.ai: %s", e.message)
                raise ServerAPIError(e.message or "Internal Server Error") from e

            # ── 502 / 503: провайдер недоступен — повтор через 10 сек ────
            if code in (502, 503):
                _log.warning("Unavailable (%d) attempt=%d: %s", code, attempt, e.message)
                if attempt < MAX_RETRIES:
                    attempt += 1
                    await asyncio.sleep(RETRY_DELAY_502_503)
                    continue
                _log.error("%d: исчерпаны попытки (%d)", code, MAX_RETRIES)
                raise

            # ── 401 / 402 / 400 / прочие — без повтора, бросаем как есть ─
            _log.error("APIStatusError %d: %s", code, e.message)
            raise

        # ── Проблемы соединения — повтор через 10 сек ────────────────────
        except APIConnectionError as e:
            _log.warning("APIConnectionError attempt=%d: %s", attempt, e)
            if attempt < MAX_RETRIES:
                attempt += 1
                await asyncio.sleep(RETRY_DELAY_502_503)
                continue
            _log.error("APIConnectionError: исчерпаны попытки")
            raise

        except Exception as e:
            _log.error("Неожиданная ошибка: %s: %s", type(e).__name__, e)
            raise
