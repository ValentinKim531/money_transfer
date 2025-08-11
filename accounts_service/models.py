from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Numeric, Integer, DateTime, ForeignKey
from typing import Optional
from datetime import datetime


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_email: Mapped[str] = mapped_column(String(255), index=True)
    currency: Mapped[str] = mapped_column(String(10), index=True)
    balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class AccountOperation(Base):
    __tablename__ = "account_operations"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"))
    operation: Mapped[str] = mapped_column(
        String(20)
    )  # "deposit" или "withdraw"
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    client_key: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
