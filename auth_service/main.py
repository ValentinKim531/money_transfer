from fastapi import HTTPException, Request
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from utils.tracing import setup_tracing, shutdown_tracing
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
    AsyncEngine,
)
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from utils.config import settings
from utils.db import get_db
from utils.i18n import t
from utils.security import hash_password, verify_password, create_access_token
from utils.idempotency import idempotency_middleware
from utils.audit import audit_write
from utils.utils import get_lang
from .models import Base, User
from .schemas import RegisterIn, LoginIn, TokenOut
import logging


logger = logging.getLogger(__name__)

DB_URL = settings.db_url

engine: AsyncEngine = create_async_engine(DB_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    setup_tracing(app, "auth_service")
    await init_db()
    try:
        yield
    finally:
        await close_db()
        try:
            shutdown_tracing()
        except Exception as e:
            logger.error(f"Ошибка при остановке трассировки: {e}")


app = FastAPI(title="auth_service", lifespan=lifespan)
app.add_middleware(BaseHTTPMiddleware, dispatch=idempotency_middleware)


def get_current_user_id(token: str = Depends(oauth2_scheme)) -> str:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_alg]
        )
        logger.info(
            f"[auth] JWT_SECRET_LEN={len(settings.jwt_secret)} ALG={settings.jwt_alg}"
        )
        sub = payload.get("sub")
        if not sub:
            raise ValueError
        return sub
    except JWTError as e:
        logger.error(f"[auth] Invalid token: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")


@app.post("/register", response_model=TokenOut)
async def register(
    data: RegisterIn, request: Request, db: AsyncSession = Depends(get_db)
):
    lang = get_lang(request)

    # проверка существования
    q = await db.execute(select(User).where(User.email == data.email))
    existing = q.scalar_one_or_none()
    if existing:
        audit_write(
            None,
            "register",
            f"user:{data.email}",
            {"email": data.email},
            "fail",
            "exists",
        )
        raise HTTPException(status_code=400, detail=t("user_exists", lang))

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
    )
    db.add(user)
    await db.commit()
    token = create_access_token(sub=user.email)
    audit_write(
        user.email,
        "register",
        f"user:{user.email}",
        {"full_name": user.full_name},
        "success",
        None,
    )
    return TokenOut(access_token=token)


@app.post("/login", response_model=TokenOut)
async def login(
    data: LoginIn, request: Request, db: AsyncSession = Depends(get_db)
):
    lang = get_lang(request)

    q = await db.execute(select(User).where(User.email == data.email))
    user = q.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        audit_write(
            None,
            "login",
            f"user:{data.email}",
            {},
            "fail",
            "invalid_credentials",
        )
        raise HTTPException(
            status_code=401, detail=t("invalid_credentials", lang)
        )

    token = create_access_token(sub=user.email)
    audit_write(user.email, "login", f"user:{user.email}", {}, "success", None)
    return TokenOut(access_token=token)


@app.get("/whoami")
async def whoami(user_id: str = Depends(get_current_user_id)):
    return {"user": user_id}
