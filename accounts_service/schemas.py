from pydantic import BaseModel, Field


class AccountCreate(BaseModel):
    currency: str = Field(..., examples=["KZT"])
    title: str | None = None


class AccountOut(BaseModel):
    id: int
    currency: str
    balance: float
    title: str | None = None

    class Config:
        from_attributes = True


class BalanceChangeIn(BaseModel):
    amount: float = Field(gt=0, description="Сумма > 0")
    client_key: str | None = Field(
        default=None, description="Идемпотентный ключ клиента"
    )


class BalanceChangeOut(BaseModel):
    account_id: int
    balance: float
    operation: str
