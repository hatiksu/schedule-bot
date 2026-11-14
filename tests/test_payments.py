"""Оплата звёздами и рублями (ЮKassa): цены, проверка суммы перед оплатой, чек, учёт выручки по валютам."""
import asyncio
import json
import sqlite3

import pytest

import modules.shop as shop
from utils.db import DB
from utils.premium import (DONATES, PLANS, RUB, RUB_DONATES, RUB_PLANS, RUB_THEMES, STARS, THEMES, price,
                           price_label, product_title, receipt)


def test_every_paid_product_has_both_prices():
    for plan in PLANS:
        for kind in ("plan", "gift"):
            assert price(f"{kind}:{plan}", STARS) == PLANS[plan][1]
            assert price(f"{kind}:{plan}", RUB) == RUB_PLANS[plan]
    paid_themes = {tid for tid, (_, _, cost) in THEMES.items() if cost > 0}
    assert paid_themes == set(RUB_THEMES), "у каждой платной темы должна быть цена в рублях"
    assert price("theme:classic", STARS) is None and price("theme:classic", RUB) is None


def test_donates_and_unknown_products():
    assert price(f"donate:{DONATES[0]}", STARS) == DONATES[0]
    assert price(f"donate:{RUB_DONATES[0]}", RUB) == RUB_DONATES[0]
    assert price("donate:7", RUB) is None  # только суммы из списка
    assert price("plan:week", STARS) is None
    assert price("plan:month", "USD") is None


def test_price_label():
    assert price_label("plan:month", rub=False) == "30 ⭐"
    assert price_label("plan:month", rub=True) == f"30 ⭐ / {RUB_PLANS['month']} ₽"


def test_product_title():
    assert product_title("plan:year")[0] == PLANS["year"][0]
    assert product_title("gift:month")[0].startswith("🎁 Подарок")
    assert "Неон" in product_title("theme:neon")[0]


def test_receipt_for_yookassa():
    r = receipt("plan:month", 79, vat_code=1)
    item = r["receipt"]["items"][0]
    assert item["amount"] == {"value": "79.00", "currency": "RUB"}
    assert item["quantity"] == "1.00" and item["vat_code"] == 1
    assert item["payment_subject"] == "service" and item["payment_mode"] == "full_payment"
    assert "⭐" not in item["description"] and item["description"]
    json.dumps(r)  # уходит в provider_data строкой


def test_expected_total_depends_on_yookassa(monkeypatch):
    monkeypatch.setattr(shop, "YOOKASSA_TOKEN", "")
    assert shop.expected_total("plan:month", STARS) == 30
    assert shop.expected_total("plan:month", RUB) is None  # ЮKassa не подключена — рубли не принимаем
    monkeypatch.setattr(shop, "YOOKASSA_TOKEN", "381764678:TEST:00000")
    assert shop.expected_total("plan:month", RUB) == RUB_PLANS["month"] * 100  # Telegram считает в копейках
    assert shop.expected_total("plan:week", RUB) is None


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    # Старая схема покупок — без валюты: миграция должна добавить колонки
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product TEXT, "
                "stars INTEGER, charge_id TEXT, created_at TEXT, refunded INTEGER NOT NULL DEFAULT 0)")
    con.execute("INSERT INTO purchases(user_id, product, stars, charge_id, created_at) "
                "VALUES (1, 'plan:month', 30, 'old', '2026-01-05 10:00:00')")
    con.commit()
    con.close()
    d = DB(str(path))
    asyncio.run(d.connect())
    yield d
    asyncio.run(d.close())


def test_revenue_split_by_currency(db):
    async def scenario():
        await db.add_purchase(2, "plan:year", 200, "tg1")
        await db.add_purchase(3, "plan:month", 79, "tg2", currency=RUB, provider_charge_id="yk-1")
        await db.add_purchase(4, "theme:neon", 39, "tg3", currency=RUB, provider_charge_id="yk-2")
        await db.add_purchase(5, "trial", 0, None)  # без оплаты — не выручка
        return await db.premium_stats("2026-11-16 00:00:00", "2026-11-01 00:00:00"), await db.purchases(10)

    stats, items = asyncio.run(scenario())
    assert stats["total"] == 230 and stats["total_rub"] == 118  # старая покупка мигрировала как звёзды
    assert stats["month_rub"] == 118 and stats["cnt"] == 4
    assert {(r["product"], r["currency"]) for r in stats["by_product"]} >= {("plan:month", "XTR"), ("plan:month", "RUB")}
    rub = next(p for p in items if p["provider_charge_id"] == "yk-1")
    assert (rub["currency"], rub["stars"]) == (RUB, 79)


class FakeQuery:
    """Минимальная замена PreCheckoutQuery: запоминает ответ бота."""

    def __init__(self, payload: str, currency: str, total: int):
        self.invoice_payload, self.currency, self.total_amount = payload, currency, total
        self.result = None

    async def answer(self, ok: bool, error_message: str | None = None):
        self.result = ok


@pytest.mark.parametrize(("payload", "currency", "total", "ok"), [
    ("plan:month", STARS, 30, True),
    ("plan:month", STARS, 29, False),          # подменённая сумма
    ("plan:month", RUB, RUB_PLANS["month"] * 100, True),
    ("plan:month", RUB, RUB_PLANS["month"], False),  # рубли без копеек — неверно
    ("plan:month", "USD", 100, False),
    ("theme:classic", STARS, 0, False),
])
def test_pre_checkout(monkeypatch, payload, currency, total, ok):
    monkeypatch.setattr(shop, "YOOKASSA_TOKEN", "381764678:TEST:00000")
    q = FakeQuery(payload, currency, total)
    asyncio.run(shop.pre_checkout(q))
    assert q.result is ok
