from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Numeric, Integer, DateTime, ForeignKey
from datetime import datetime
from typing import Optional


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_email: Mapped[str] = mapped_column(String(255), index=True)
    currency: Mapped[str] = mapped_column(String(10), index=True)
    balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class Transfer(Base):
    __tablename__ = "transfers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    from_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id")
    )
    to_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id")
    )

    # суммы и валюты
    currency_from: Mapped[str] = mapped_column(String(10))
    currency_to: Mapped[str] = mapped_column(String(10))
    amount_from: Mapped[float] = mapped_column(Numeric(18, 2))
    amount_to: Mapped[float] = mapped_column(Numeric(18, 2))

    # комиссии
    commission_percent: Mapped[float] = mapped_column(Numeric(6, 3), default=0)
    commission_fixed: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    commission_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)

    # курс
    rate_used: Mapped[float] = mapped_column(Numeric(18, 6), default=1)

    # статусы: created, processing, completed, failed
    status: Mapped[str] = mapped_column(String(20), default="created")

    # идемпотентность (по желанию клиента)
    client_key: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
