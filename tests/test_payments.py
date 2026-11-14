import asyncio
import json
import sqlite3

import httpx
import pytest

import modules.shop as shop
import utils.core as core
from utils.db import DB
from utils.premium import (DONATE_MIN, PLANS, RUB, RUB_PLANS, RUB_THEMES, STARS, THEMES, price, price_label,
                           product_title)
from utils.yookassa import YooKassa, YooKassaError, payment_body, receipt_for


def test_every_paid_product_has_both_prices():
    for plan in PLANS:
        for kind in ("plan", "gift"):
            assert price(f"{kind}:{plan}", STARS) == PLANS[plan][1]
            assert price(f"{kind}:{plan}", RUB) == RUB_PLANS[plan]
    paid_themes = {tid for tid, (_, _, cost) in THEMES.items() if cost > 0}
    assert paid_themes == set(RUB_THEMES), "у каждой платной темы должна быть цена в рублях"
    assert price("theme:classic", STARS) is None and price("theme:classic", RUB) is None


def test_prices_are_democratic():
    assert PLANS["month"][1] <= 20 and RUB_PLANS["month"] <= 39
    assert all(cost <= 15 for _, _, cost in THEMES.values())
    assert PLANS["year"][1] < PLANS["month"][1] * 12 < PLANS["forever"][1] * 2
    assert RUB_PLANS["year"] < RUB_PLANS["month"] * 12 and RUB_PLANS["forever"] > RUB_PLANS["year"]


def test_donations_any_amount_from_one():
    assert DONATE_MIN == 1
    for currency in (STARS, RUB):
        assert price("donate:1", currency) == 1
        assert price("donate:987654", currency) == 987654
        assert price("donate:0", currency) is None
        assert price("donate:-5", currency) is None
        assert price("donate:abc", currency) is None


def test_price_label_and_titles():
    assert price_label("plan:month", rub=False) == f"{PLANS['month'][1]} ⭐"
    assert price_label("plan:month", rub=True) == f"{PLANS['month'][1]} ⭐ / {RUB_PLANS['month']} ₽"
    assert product_title("gift:month")[0].startswith("🎁 Подарок")
    assert "Неон" in product_title("theme:neon")[0]


@pytest.mark.parametrize(("text", "rub", "expected"), [
    ("7", True, (7, STARS)),
    (" 1 ", False, (1, STARS)),
    ("150 р", True, (150, RUB)),
    ("150₽", True, (150, RUB)),
    ("1000 руб", True, (1000, RUB)),
    ("25 звёзд", True, (25, STARS)),
    ("150 р", False, None),
    ("0", True, None),
    ("много", True, None),
    ("1.5", True, None),
])
def test_parse_donation(text, rub, expected):
    assert shop.parse_donation(text, rub) == expected


class FakeQuery:
    def __init__(self, payload: str, currency: str, total: int):
        self.invoice_payload, self.currency, self.total_amount = payload, currency, total
        self.result = None

    async def answer(self, ok: bool, error_message: str | None = None):
        self.result = ok


@pytest.mark.parametrize(("payload", "currency", "total", "ok"), [
    ("plan:month", STARS, PLANS["month"][1], True),
    ("plan:month", STARS, PLANS["month"][1] - 1, False),
    ("donate:4321", STARS, 4321, True),
    ("plan:month", RUB, RUB_PLANS["month"] * 100, False),
    ("theme:classic", STARS, 0, False),
])
def test_pre_checkout(payload, currency, total, ok):
    q = FakeQuery(payload, currency, total)
    asyncio.run(shop.pre_checkout(q))
    assert q.result is ok


def test_payment_body_and_receipt():
    body = payment_body(29, "⭐ Premium на месяц", "https://t.me/bot", {"user_id": 5, "product": "plan:month"},
                        receipt_for("⭐ Premium на месяц", 29, "a@b.ru"))
    assert body["amount"] == {"value": "29.00", "currency": "RUB"}
    assert body["capture"] is True and body["confirmation"]["type"] == "redirect"
    assert body["metadata"] == {"user_id": "5", "product": "plan:month"}
    item = body["receipt"]["items"][0]
    assert body["receipt"]["customer"] == {"email": "a@b.ru"}
    assert item["amount"]["value"] == "29.00" and "⭐" not in item["description"]
    json.dumps(body)


def test_client_requests():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v3/payments" and request.method == "POST":
            return httpx.Response(200, json={"id": "pay-1", "status": "pending", "amount": {"value": "1.00"},
                                             "confirmation": {"confirmation_url": "https://yoomoney.ru/pay"}})
        if request.url.path == "/v3/payments/pay-1":
            return httpx.Response(200, json={"id": "pay-1", "status": "succeeded", "amount": {"value": "1.00"}})
        if request.url.path == "/v3/refunds":
            return httpx.Response(200, json={"id": "ref-1", "status": "succeeded"})
        return httpx.Response(404, json={"description": "нет такого"})

    yk = YooKassa("123", "secret", transport=httpx.MockTransport(handler))
    created = asyncio.run(yk.create_payment(1, "Донат", "https://t.me/bot", {"user_id": 1}))
    assert (created.id, created.amount, created.confirmation_url) == ("pay-1", 1, "https://yoomoney.ru/pay")
    assert asyncio.run(yk.get_payment("pay-1")).status == "succeeded"
    assert asyncio.run(yk.refund("pay-1", 1)) == "succeeded"
    post = seen[0]
    assert post.headers["Idempotence-Key"] and post.headers["Authorization"].startswith("Basic ")
    assert json.loads(post.content)["amount"]["value"] == "1.00"
    with pytest.raises(YooKassaError, match="нет такого"):
        asyncio.run(yk.get_payment("nope"))
    with pytest.raises(YooKassaError):
        asyncio.run(yk.create_payment(0, "Донат", "https://t.me/bot", {}))
    assert YooKassa("", "").enabled is False


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product TEXT, "
                "stars INTEGER, charge_id TEXT, created_at TEXT, refunded INTEGER NOT NULL DEFAULT 0)")
    con.execute("INSERT INTO purchases(user_id, product, stars, charge_id, created_at) "
                "VALUES (1, 'plan:month', 30, 'old', '2026-01-05 10:00:00')")
    con.commit()
    con.close()
    d = core.db
    monkeypatch.setattr(d, "path", str(path))
    asyncio.run(d.connect())
    yield d
    asyncio.run(d.close())


def test_revenue_split_by_currency(db: DB):
    async def scenario():
        await db.add_purchase(2, "plan:year", 99, "tg1")
        await db.add_purchase(3, "plan:month", 29, "yk-1", currency=RUB, provider_charge_id="yk-1")
        await db.add_purchase(5, "trial", 0, None)
        return await db.premium_stats("2026-11-16 00:00:00", "2026-11-01 00:00:00")

    stats = asyncio.run(scenario())
    assert stats["total"] == 129 and stats["total_rub"] == 29 and stats["cnt"] == 3


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


def test_rub_payment_settles_once(db: DB):
    bot = FakeBot()

    async def scenario():
        await db.touch_user(42, "anna", "Анна")
        await db.add_pending("pay-1", 42, "plan:month", RUB_PLANS["month"], 42)
        pending = await db.get_pending("pay-1")
        assert await shop.settle(bot, pending, "pending") is False
        assert await shop.settle(bot, pending, "succeeded") is True
        assert await shop.settle(bot, pending, "succeeded") is True
        return await db.get_user(42), await db.purchases(5), await db.get_pending("pay-1")

    user, purchases, pending = asyncio.run(scenario())
    assert user["premium_until"]
    rub = [p for p in purchases if p["currency"] == RUB]
    assert len(rub) == 1 and rub[0]["stars"] == RUB_PLANS["month"] and rub[0]["provider_charge_id"] == "pay-1"
    assert pending["status"] == "succeeded"
    assert sum("Оплата прошла" in text for _, text in bot.sent) == 1


def test_rub_payment_canceled(db: DB):
    bot = FakeBot()

    async def scenario():
        await db.add_pending("pay-2", 7, "donate:1", 1, 7)
        assert await shop.settle(bot, await db.get_pending("pay-2"), "canceled") is True
        return await db.get_pending("pay-2"), await db.purchases(5)

    pending, purchases = asyncio.run(scenario())
    assert pending["status"] == "canceled"
    assert not any(p["product"] == "donate:1" for p in purchases)
    assert "отменён" in bot.sent[0][1]


class FakeMessage:
    def __init__(self, chat_id: int):
        self.chat = type("Chat", (), {"id": chat_id})()
        self.answers: list[tuple[str, object]] = []

    async def answer(self, text, reply_markup=None, **kwargs):
        self.answers.append((text, reply_markup))


def test_start_rub_payment_creates_link(db: DB, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["amount"]["value"] == "1.00" and body["metadata"]["product"] == "donate:1"
        return httpx.Response(200, json={"id": "pay-9", "status": "pending", "amount": {"value": "1.00"},
                                         "confirmation": {"confirmation_url": "https://yoomoney.ru/checkout/pay-9"}})

    monkeypatch.setattr(shop, "yookassa", YooKassa("1", "s", transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(shop, "YOOKASSA_RECEIPT", False)
    msg = FakeMessage(chat_id=77)
    asyncio.run(shop.send_invoice(msg, "donate:1", RUB, uid=77))
    pending = asyncio.run(db.get_pending("pay-9"))
    assert (pending["user_id"], pending["amount"], pending["status"]) == (77, 1, "pending")
    text, kb = msg.answers[-1]
    assert "1 ₽" in text
    assert kb.inline_keyboard[0][0].url == "https://yoomoney.ru/checkout/pay-9"
    assert kb.inline_keyboard[1][0].callback_data == "pay:chk:pay-9"
