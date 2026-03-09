from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from openai import AsyncOpenAI, APIConnectionError, APIStatusError, RateLimitError


def get_prompt() -> str:
    # Путь к prompt.txt относительно этого файла (ai_service.py в services/)
    path = Path(__file__).resolve().parent.parent / "prompt.txt"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()



def make_client(polza_api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(base_url="https://polza.ai/api/v1", api_key=polza_api_key)



@dataclass(frozen=True)
class AIResult:
    text: str
    tokens_used: int | None
    cost_rub: float | None
    model_used: str | None



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
    print(f"[ai_service] using model={model}, base_url={client.base_url}")

    user_message = _build_user_message(
        child_name=child_name,
        child_age=child_age,
        hobby=hobby,
        topic=topic,
        anxiety_level=anxiety_level,
        comment=comment,
    )

    backoff_seconds = [5, 10, 20]
    for attempt in range(len(backoff_seconds) + 1):
        try:
            print(f"[ai_service] attempt={attempt}, sending request...")
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": get_prompt()},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body={
                    "provider": {
                        "allow_fallbacks": True,
                        "sort": "price"
                    }
                },
            )

            usage = getattr(resp, "usage", None)
            tokens_used = getattr(usage, "total_tokens", None) if usage else None
            cost_rub = getattr(usage, "cost_rub", None) if usage else None

            print(f"[ai_service] success, tokens={tokens_used}, cost_rub={cost_rub}")

            return AIResult(
                text=resp.choices[0].message.content,
                tokens_used=tokens_used,
                cost_rub=cost_rub,
                model_used=getattr(resp, "model", None),
            )

        except RateLimitError as e:
            print(f"[ai_service] RateLimitError attempt={attempt}: {e}")
            if attempt >= len(backoff_seconds):
                raise
            await asyncio.sleep(backoff_seconds[attempt])

        except APIStatusError as e:
            print(f"[ai_service] APIStatusError {e.status_code}: {e.message}")
            if e.status_code in (502, 503) and attempt < len(backoff_seconds):
                await asyncio.sleep(backoff_seconds[attempt])
                continue
            raise

        except APIConnectionError as e:
            print(f"[ai_service] APIConnectionError attempt={attempt}: {e}")
            if attempt >= len(backoff_seconds):
                raise
            await asyncio.sleep(backoff_seconds[attempt])

        except Exception as e:
            print(f"[ai_service] Unexpected error: {type(e).__name__}: {e}")
            raise
