from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from starlette.middleware.base import BaseHTTPMiddleware
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncEngine,
    AsyncSession,
)
from sqlalchemy import select
from utils.config import settings
from utils.db import get_db
from utils.tracing import setup_tracing, shutdown_tracing
from utils.i18n import t, format_money
from utils.idempotency import idempotency_middleware
from utils.audit import audit_write
from utils.utils import get_lang
from .models import Base, Account, AccountOperation
from .schemas import (
    AccountCreate,
    AccountOut,
    BalanceChangeOut,
    BalanceChangeIn,
)
from contextlib import asynccontextmanager
import logging


logger = logging.getLogger(__name__)
DB_URL = settings.db_url

engine: AsyncEngine = create_async_engine(DB_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(bind=sync_conn, checkfirst=True)
        )


async def close_db() -> None:
    await engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    setup_tracing(app, "accounts_service")
    await init_db()
    try:
        yield
    finally:
        # shutdown
        await close_db()
        try:
            shutdown_tracing()
        except Exception as e:
            logger.error(f"Ошибка при остановке трассировки: {e}")


app = FastAPI(title="accounts_service", lifespan=lifespan)
app.add_middleware(BaseHTTPMiddleware, dispatch=idempotency_middleware)


def get_current_user_email(token: str = Depends(oauth2_scheme)) -> str:
    try:
        logger.info(
            f"[accounts] JWT_SECRET_LEN={len(settings.jwt_secret)} ALG={settings.jwt_alg}"
        )
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_alg]
        )
        sub = payload.get("sub")
        if not sub:
            raise ValueError
        return sub
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.post("/accounts", response_model=AccountOut)
async def create_account(
    data: AccountCreate,
    request: Request,
    user: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    acc = Account(
        owner_email=user,
        currency=data.currency.upper(),
        balance=0,
        title=data.title,
    )
    db.add(acc)
    await db.commit()
    await db.refresh(acc)
    audit_write(
        user,
        "account_create",
        f"account:{acc.id}",
        {"currency": acc.currency, "title": acc.title},
        "success",
        None,
    )
    return acc


@app.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    user: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(select(Account).where(Account.owner_email == user))
    items = q.scalars().all()
    return items


@app.get("/accounts/{account_id}")
async def account_detail(
    account_id: int,
    request: Request,
    user: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    lang = get_lang(request)
    q = await db.execute(
        select(Account).where(
            Account.id == account_id, Account.owner_email == user
        )
    )
    acc = q.scalar_one_or_none()
    if not acc:
        audit_write(
            user,
            "account_get",
            f"account:{account_id}",
            {},
            "fail",
            "not_found",
        )
        raise HTTPException(
            status_code=404, detail=t("account_not_found", lang)
        )
    # демонстрация локализации денег
    pretty_balance = format_money(float(acc.balance), acc.currency, lang)
    return {
        "id": acc.id,
        "currency": acc.currency,
        "balance": float(acc.balance),
        "title": acc.title,
        "balance_pretty": pretty_balance,
    }


@app.post("/accounts/{account_id}/deposit", response_model=BalanceChangeOut)
async def deposit_to_account(
    account_id: int,
    payload: BalanceChangeIn,
    user: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    # идемпотентность: если пришёл client_key — проверим, выполняли ли уже
    if payload.client_key:
        q = await db.execute(
            select(AccountOperation).where(
                AccountOperation.client_key == payload.client_key
            )
        )
        op_prev = q.scalar_one_or_none()
        if op_prev:
            acc = await db.get(Account, account_id)
            if not acc or acc.owner_email != user:
                raise HTTPException(status_code=403, detail="Forbidden")
            return BalanceChangeOut(
                account_id=acc.id,
                balance=float(acc.balance),
                operation="deposit",
            )

    acc = await db.get(Account, account_id)
    if not acc:
        audit_write(
            user,
            "account_deposit",
            f"account:{account_id}",
            {"amount": payload.amount},
            "fail",
            "not_found",
        )
        raise HTTPException(status_code=404, detail="Account not found")

    if acc.owner_email != user:
        raise HTTPException(status_code=403, detail="Forbidden")

    # атомарность в рамках транзакции БД
    acc.balance = float(acc.balance) + float(payload.amount)
    op = AccountOperation(
        account_id=acc.id,
        operation="deposit",
        amount=float(payload.amount),
        client_key=payload.client_key,
    )
    db.add(op)
    await db.commit()
    await db.refresh(acc)
    audit_write(
        user,
        "account_deposit",
        f"account:{acc.id}",
        {"amount": float(payload.amount)},
        "success",
        None,
    )
    return BalanceChangeOut(
        account_id=acc.id, balance=float(acc.balance), operation="deposit"
    )


@app.post("/accounts/{account_id}/withdraw", response_model=BalanceChangeOut)
async def withdraw_from_account(
    account_id: int,
    payload: BalanceChangeIn,
    user: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    # идемпотентность
    if payload.client_key:
        q = await db.execute(
            select(AccountOperation).where(
                AccountOperation.client_key == payload.client_key
            )
        )
        op_prev = q.scalar_one_or_none()
        if op_prev:
            acc = await db.get(Account, account_id)
            if not acc or acc.owner_email != user:
                raise HTTPException(status_code=403, detail="Forbidden")
            return BalanceChangeOut(
                account_id=acc.id,
                balance=float(acc.balance),
                operation="withdraw",
            )

    acc = await db.get(Account, account_id)
    if not acc:
        audit_write(
            user,
            "account_withdraw",
            f"account:{account_id}",
            {"amount": payload.amount},
            "fail",
            "not_found",
        )
        raise HTTPException(status_code=404, detail="Account not found")

    if acc.owner_email != user:
        raise HTTPException(status_code=403, detail="Forbidden")

    amount = float(payload.amount)
    if float(acc.balance) < amount:
        audit_write(
            user,
            "account_withdraw",
            f"account:{acc.id}",
            {"need": amount, "have": float(acc.balance)},
            "fail",
            "insufficient_funds",
        )
        raise HTTPException(status_code=400, detail="Insufficient funds")

    acc.balance = float(acc.balance) - amount
    op = AccountOperation(
        account_id=acc.id,
        operation="withdraw",
        amount=amount,
        client_key=payload.client_key,
    )
    db.add(op)
    await db.commit()
    await db.refresh(acc)
    audit_write(
        user,
        "account_withdraw",
        f"account:{acc.id}",
        {"amount": amount},
        "success",
        None,
    )
    return BalanceChangeOut(
        account_id=acc.id, balance=float(acc.balance), operation="withdraw"
    )
