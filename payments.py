"""
payments.py

Базовые заглушки для интеграции крипто-платежей.
ТЗ: заменить/не использовать YooKassa и предоставить понятные точки расширения.
"""

from __future__ import annotations

import datetime as _dt
import secrets
from dataclasses import dataclass
from typing import Literal, Optional


CryptoPaymentStatus = Literal["pending", "paid", "expired", "failed"]


@dataclass(frozen=True)
class CryptoPayment:
    payment_id: str
    user_id: int
    plan: str
    amount: float
    currency: str
    status: CryptoPaymentStatus
    pay_url: Optional[str] = None
    created_at: str = ""


def create_crypto_payment(user_id: int, plan: str, amount: float, currency: str = "USDT") -> CryptoPayment:
    """
    Создаёт крипто-платёж (заглушка).
    В реальной интеграции здесь будет запрос к провайдеру крипто-платежей.
    """
    payment_id = f"cp_{secrets.token_hex(8)}"
    created_at = _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    # Заглушка: pay_url обычно выдаёт провайдер
    pay_url = f"https://crypto-payments.example/pay/{payment_id}"
    return CryptoPayment(
        payment_id=payment_id,
        user_id=user_id,
        plan=plan,
        amount=float(amount),
        currency=currency,
        status="pending",
        pay_url=pay_url,
        created_at=created_at,
    )


def check_crypto_payment_status(payment_id: str) -> CryptoPaymentStatus:
    """
    Проверяет статус крипто-платежа (заглушка).
    Сейчас всегда возвращает 'pending'.
    """
    _ = payment_id
    return "pending"

