from __future__ import annotations

"""
Тарифы бота «Педагог».

Структура каждого тарифа:
  name        — отображаемое название
  daily_limit — лимит генераций в сутки (None = безлимит)
  price       — цена за 30 дней в рублях (0 = бесплатно)
  description — короткое описание для кнопки /pay

Чтобы поменять цены — редактируйте только этот файл.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Tariff:
    key: str
    name: str
    daily_limit: int | None
    price: float          # руб. за 30 дней
    description: str


TARIFFS: dict[str, Tariff] = {
    "free": Tariff(
        key="free",
        name="Пробный",
        daily_limit=10,
        price=0.0,
        description="10 генераций · бесплатно",
    ),
    "basic": Tariff(
        key="basic",
        name="Базовый",
        daily_limit=None,       # безлимит
        price=1.0,              # 1 руб. (тестовая цена)
        description="Безлимит · 1 руб / 30 дней",
    ),
    "premium": Tariff(
        key="premium",
        name="Премиум",
        daily_limit=None,       # безлимит
        price=2.0,              # 2 руб. (тестовая цена)
        description="Безлимит + приоритет · 2 руб / 30 дней",
    ),
}

# Тарифы, доступные для покупки через /pay (без free)
PAID_TARIFFS = [t for t in TARIFFS.values() if t.price > 0]
