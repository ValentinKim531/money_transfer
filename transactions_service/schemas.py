from pydantic import BaseModel, Field
from typing import Literal


# mode="from" — задано сколько списать; mode="to" —  сколько зачислить
class TransferCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    mode: Literal["from", "to"]
    amount: float = Field(gt=0)
    commission_percent: float = 0.0
    commission_fixed: float = 0.0
    client_key: str | None = None


class TransferOut(BaseModel):
    id: int
    status: str
    from_account_id: int
    to_account_id: int
    currency_from: str
    currency_to: str
    amount_from: float
    amount_to: float
    commission_amount: float
    rate_used: float

    class Config:
        from_attributes = True
