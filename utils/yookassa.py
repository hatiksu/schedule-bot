from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx

API = "https://api.yookassa.ru/v3"


class YooKassaError(Exception):
    pass


@dataclass(frozen=True)
class Payment:
    id: str
    status: str
    amount: int
    confirmation_url: str | None = None


def rub(amount: int) -> dict:
    return {"value": f"{amount}.00", "currency": "RUB"}


def payment_body(amount: int, description: str, return_url: str, metadata: dict,
                 receipt: dict | None = None) -> dict:
    body = {
        "amount": rub(amount),
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": description[:128],
        "metadata": {k: str(v) for k, v in metadata.items()},
    }
    if receipt:
        body["receipt"] = receipt
    return body


def receipt_for(description: str, amount: int, email: str, vat_code: int = 1) -> dict:
    clean = "".join(ch for ch in description if ch.isalnum() or ch in " «»:-.,").strip()[:128] or "Услуга"
    return {
        "customer": {"email": email},
        "items": [{
            "description": clean,
            "quantity": "1.00",
            "amount": rub(amount),
            "vat_code": vat_code,
            "payment_mode": "full_payment",
            "payment_subject": "service",
        }],
    }


def _payment(data: dict) -> Payment:
    return Payment(
        id=data["id"],
        status=data["status"],
        amount=int(float(data["amount"]["value"])),
        confirmation_url=(data.get("confirmation") or {}).get("confirmation_url"),
    )


class YooKassa:
    def __init__(self, shop_id: str, secret_key: str, transport: httpx.AsyncBaseTransport | None = None):
        self.enabled = bool(shop_id and secret_key)
        self._auth = (shop_id, secret_key)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=API, auth=self._auth, timeout=20, transport=self._transport)

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        headers = {"Idempotence-Key": str(uuid.uuid4())} if method == "POST" else {}
        async with self._client() as client:
            r = await client.request(method, path, json=json, headers=headers)
        if r.status_code >= 400:
            try:
                detail = r.json().get("description") or r.text
            except ValueError:
                detail = r.text
            raise YooKassaError(f"ЮKassa {r.status_code}: {detail}")
        return r.json()

    async def create_payment(self, amount: int, description: str, return_url: str, metadata: dict,
                             receipt: dict | None = None) -> Payment:
        if amount < 1:
            raise YooKassaError("Минимальная сумма — 1 ₽")
        return _payment(await self._request("POST", "/payments",
                                            payment_body(amount, description, return_url, metadata, receipt)))

    async def get_payment(self, payment_id: str) -> Payment:
        return _payment(await self._request("GET", f"/payments/{payment_id}"))

    async def refund(self, payment_id: str, amount: int) -> str:
        data = await self._request("POST", "/refunds", {"payment_id": payment_id, "amount": rub(amount)})
        return data["status"]
