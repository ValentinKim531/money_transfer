import os
import json
from datetime import datetime
from typing import cast, Optional
from aio_pika import RobustConnection, Channel
from aiormq import AMQPConnectionError
from starlette.datastructures import State
import httpx
from jose import jwt, JWTError
from fastapi import FastAPI, Depends, HTTPException, Request, Query
from fastapi.security import OAuth2PasswordBearer
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
    AsyncEngine,
)
from utils.config import settings
from utils.db import get_db
from utils.tracing import setup_tracing, shutdown_tracing
from utils.idempotency import idempotency_middleware
from utils.audit import audit_write
from utils.i18n import t
from .models import Base, Account, Transfer
from .schemas import TransferCreate, TransferOut
import asyncio
import aio_pika
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger(__name__)

DB_URL = settings.db_url
RABBIT_URL = settings.rabbitmq_url
QUEUE_NAME = "transfer_notifications"
NOTIF_ENABLED = os.getenv("NOTIFICATIONS_ENABLED", "true").lower() == "true"


DEFAULT_PERCENT = 1.0
DEFAULT_FIXED = 0.0


engine: AsyncEngine = create_async_engine(DB_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


class RatesProvider:
    def __init__(
        self,
        use_mock: bool = True,
        provider_url: str = "https://api.exchangerate.host/latest",
    ):
        self.use_mock = use_mock
        self.provider_url = provider_url

    async def get_rate(self, base: str, quote: str) -> float:
        base = base.upper()
        quote = quote.upper()
        if base == quote:
            return 1.0
        if self.use_mock:
            table = {
                ("USD", "KZT"): 540.00,
                ("KZT", "USD"): 1 / 540.00,
                ("EUR", "KZT"): 628.00,
                ("KZT", "EUR"): 1 / 628.00,
                ("EUR", "USD"): 1.162881,
                ("USD", "EUR"): 1 / 1.162881,
            }
            return float(table.get((base, quote), 1.0))
        url = f"{self.provider_url}?base={base}&symbols={quote}"
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            rate = data.get("rates", {}).get(quote)
            if not rate:
                raise ValueError("Rate not found")
            return float(rate)


rates = RatesProvider(
    use_mock=settings.use_mock_rates, provider_url=settings.rates_provider_url
)


def _state(app: FastAPI) -> State:
    return cast(State, app.state)


async def try_connect_rabbit(app: FastAPI) -> bool:
    s = _state(app)

    if not NOTIF_ENABLED:
        logger.warning(
            "[rmq] Notifications disabled by NOTIFICATIONS_ENABLED=false"
        )
        s.rmq_channel = None
        s.rmq_connection = None
        return False

    try:
        conn: RobustConnection = await aio_pika.connect_robust(RABBIT_URL)
        from aio_pika import Channel

        ch: Channel = await conn.channel()
        await ch.declare_queue(QUEUE_NAME, durable=True)
        s.rmq_connection = conn
        s.rmq_channel = ch
        logger.info(
            "[rmq] Connected to RabbitMQ and queue declared: %s", QUEUE_NAME
        )
        return True
    except AMQPConnectionError as e:
        logger.warning(
            "[rmq] RabbitMQ unavailable: %s. Notifications will be NO-OP.", e
        )
        s.rmq_channel = None
        s.rmq_connection = None
        return False


async def close_rabbit(app: FastAPI) -> None:
    s = _state(app)
    ch: Optional[Channel] = getattr(s, "rmq_channel", None)
    conn: Optional[RobustConnection] = getattr(s, "rmq_connection", None)
    try:
        if ch and not ch.is_closed:
            await ch.close()
    finally:
        if conn and not conn.is_closed:
            await conn.close()


async def publish_notification(app: FastAPI, payload: dict) -> None:
    s = _state(app)
    ch: Optional[Channel] = getattr(s, "rmq_channel", None)
    if not ch or ch.is_closed:
        logger.info("[rmq] NO-OP notify: %s", payload)
        return
    await ch.default_exchange.publish(
        aio_pika.Message(body=str(payload).encode("utf-8")),
        routing_key=QUEUE_NAME,
    )


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_tracing(app, "transactions_service")
    await init_db()
    rmq_ok = await try_connect_rabbit(
        app
    )  # ← не падаем, если брокер недоступен
    try:
        yield
    finally:
        if rmq_ok:
            await close_rabbit(app)
        await close_db()
        shutdown_tracing(app)


app = FastAPI(title="transactions_service", lifespan=lifespan)
app.add_middleware(BaseHTTPMiddleware, dispatch=idempotency_middleware)


def get_current_user_email(token: str = Depends(oauth2_scheme)) -> str:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_alg]
        )
        sub = payload.get("sub")
        if not sub:
            raise ValueError
        return sub
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def calc_from_mode(
    amount_from: float, rate: float, p: float, f: float
) -> tuple[float, float]:
    gross = amount_from * rate
    commission = gross * (p / 100.0) + f
    amount_to = gross - commission
    if amount_to <= 0:
        raise ValueError("Amount_to <= 0 after commission")
    return round(amount_to, 2), round(commission, 2)


def calc_to_mode(
    amount_to_wanted: float, rate: float, p: float, f: float
) -> tuple[float, float]:
    percent_factor = 1.0 - (p / 100.0)
    if percent_factor <= 0:
        raise ValueError("Invalid commission percent")
    gross_needed = (amount_to_wanted + f) / percent_factor
    amount_from_required = gross_needed / rate
    commission = gross_needed - amount_to_wanted
    return round(amount_from_required, 2), round(commission, 2)


async def publish_event(message: dict):
    try:
        connection = await aio_pika.connect_robust(RABBIT_URL)
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue(QUEUE_NAME, durable=True)
            await channel.default_exchange.publish(
                aio_pika.Message(
                    body=json.dumps(message, ensure_ascii=False).encode(
                        "utf-8"
                    )
                ),
                routing_key=queue.name,
            )
    except Exception as e:
        audit_write(
            message.get("user"),
            "notify_publish",
            f"transfer:{message.get('transfer_id')}",
            {"error": str(e)},
            "fail",
            str(e),
        )


@app.post("/transfers", response_model=TransferOut)
async def create_transfer(
    payload: TransferCreate,
    request: Request,
    user: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    if payload.client_key:
        q = await db.execute(
            select(Transfer).where(Transfer.client_key == payload.client_key)
        )
        prev = q.scalar_one_or_none()
        if prev:
            return TransferOut.model_validate(prev)

    q1 = await db.execute(
        select(Account).where(Account.id == payload.from_account_id)
    )
    from_acc = q1.scalar_one_or_none()
    q2 = await db.execute(
        select(Account).where(Account.id == payload.to_account_id)
    )
    to_acc = q2.scalar_one_or_none()

    if not from_acc or not to_acc:
        audit_write(
            user,
            "transfer_create",
            f"accounts:{payload.from_account_id}->{payload.to_account_id}",
            {},
            "fail",
            "account_not_found",
        )
        raise HTTPException(
            status_code=404, detail=t("account_not_found", "ru")
        )

    if from_acc.owner_email != user:
        raise HTTPException(status_code=403, detail="Forbidden")

    rate = await rates.get_rate(from_acc.currency, to_acc.currency)

    p = float(
        payload.commission_percent
        if payload.commission_percent is not None
        else DEFAULT_PERCENT
    )
    f = float(
        payload.commission_fixed
        if payload.commission_fixed is not None
        else DEFAULT_FIXED
    )

    if payload.mode == "from":
        amount_from = float(payload.amount)
        amount_to, commission_amount = calc_from_mode(amount_from, rate, p, f)
    else:
        amount_to = float(payload.amount)
        amount_from, commission_amount = calc_to_mode(amount_to, rate, p, f)

    if float(from_acc.balance) < amount_from:
        audit_write(
            user,
            "transfer_create",
            f"account:{from_acc.id}",
            {"need": amount_from, "have": float(from_acc.balance)},
            "fail",
            "insufficient_funds",
        )
        raise HTTPException(
            status_code=400, detail=t("insufficient_funds", "ru")
        )

    transfer = Transfer(
        from_account_id=from_acc.id,
        to_account_id=to_acc.id,
        currency_from=from_acc.currency,
        currency_to=to_acc.currency,
        amount_from=amount_from,
        amount_to=amount_to,
        commission_percent=p,
        commission_fixed=f,
        commission_amount=commission_amount,
        rate_used=rate,
        status="created",
        client_key=payload.client_key,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(transfer)
    await db.flush()

    try:
        transfer.status = "processing"
        await db.flush()

        from_acc.balance = float(from_acc.balance) - amount_from
        to_acc.balance = float(to_acc.balance) + amount_to
        await db.flush()

        transfer.status = "completed"
        transfer.updated_at = datetime.utcnow()
        await db.commit()

        asyncio.create_task(
            publish_event(
                {
                    "type": "transfer_completed",
                    "transfer_id": transfer.id,
                    "from": transfer.from_account_id,
                    "to": transfer.to_account_id,
                    "amount_from": float(transfer.amount_from),
                    "currency_from": transfer.currency_from,
                    "amount_to": float(transfer.amount_to),
                    "currency_to": transfer.currency_to,
                    "status": transfer.status,
                    "user": user,
                }
            )
        )

        audit_write(
            user,
            "transfer_completed",
            f"transfer:{transfer.id}",
            {
                "from": transfer.from_account_id,
                "to": transfer.to_account_id,
                "amount_from": amount_from,
                "amount_to": amount_to,
                "rate": rate,
                "commission": commission_amount,
            },
            "success",
            None,
        )

    except Exception as e:
        await db.rollback()
        async with SessionLocal() as s2:
            async with s2.begin():
                t2 = await s2.get(Transfer, transfer.id)
                if t2:
                    t2.status = "failed"
                    t2.updated_at = datetime.utcnow()
        audit_write(
            user,
            "transfer_failed",
            f"transfer:{transfer.id}",
            {"error": str(e)},
            "fail",
            str(e),
        )
        raise HTTPException(status_code=500, detail="Transfer failed")

    return TransferOut.model_validate(transfer)


@app.get("/transfers/{transfer_id}", response_model=TransferOut)
async def get_transfer(
    transfer_id: int,
    user: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    t = await db.get(Transfer, transfer_id)
    if not t:
        raise HTTPException(status_code=404, detail="Transfer not found")

    a = await db.get(Account, t.from_account_id)
    if not a or a.owner_email != user:
        raise HTTPException(status_code=403, detail="Forbidden")

    return TransferOut.model_validate(t)


@app.get("/rates")
async def get_rate(
    base: str = Query(
        ..., min_length=3, max_length=3, description="Например, USD"
    ),
    quote: str = Query(
        ..., min_length=3, max_length=3, description="Например, KZT"
    ),
):
    rate = await rates.get_rate(base.upper(), quote.upper())
    return {
        "base": base.upper(),
        "quote": quote.upper(),
        "rate": rate,
        "provider": "mock" if rates.use_mock else "exchangerate.host",
        "ts": datetime.utcnow().isoformat(),
    }
