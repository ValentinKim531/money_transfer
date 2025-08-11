# 0) Сначала — среда для всех сервисов (до импортов приложений!)
import os
from pathlib import Path

# Отключить Jaeger/OTEL, чтобы не сыпались ошибки экспорта
os.environ["OTEL_SDK_DISABLED"] = "true"

# Единый временный файл БД для всех сервисов
BASE_DIR = Path(__file__).resolve().parents[1]  # .../money_transfer
TEST_DB_PATH = BASE_DIR / "test_app.sqlite3"
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()  # чистый старт

os.environ["DB_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["USE_MOCK_RATES"] = "true"

# Один и тот же JWT_SECRET и нормальный TTL
os.environ[
    "JWT_SECRET"
] = "dev_test_secret_for_all_services_please_keep_constant"
os.environ["JWT_EXPIRES_MIN"] = "3600"

# 1) Далее — обычные импорты
import uuid
import pytest
from decimal import Decimal
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager

# ASGI-приложения
from auth_service.main import app as auth_app
from accounts_service.main import app as accounts_app
from transactions_service.main import app as tx_app

# 2) Жёстко фиксируем ожидания под твои МОКИ (540, 628, 1/540, 1/628)
USD_TO_KZT = Decimal("540.00")
KZT_TO_USD = Decimal("1") / USD_TO_KZT
PERCENT = Decimal("1.0")  # 1%
FIXED = Decimal("0.0")

Q2 = Decimal("0.01")


def q2(x: Decimal) -> Decimal:
    return x.quantize(Q2)


@pytest.mark.asyncio
async def test_full_flow():
    # Поднимаем lifespan у всех трёх приложений на время теста
    async with LifespanManager(auth_app), LifespanManager(
        accounts_app
    ), LifespanManager(tx_app):
        auth_tr = ASGITransport(app=auth_app)
        acc_tr = ASGITransport(app=accounts_app)
        tx_tr = ASGITransport(app=tx_app)

        # ---------- 1) Регистрация/логин ----------
        email = f"u_{uuid.uuid4().hex[:8]}@test.com"
        password = "pw12345678"

        async with AsyncClient(transport=auth_tr, base_url="http://test") as c:
            r = await c.post(
                "/register",
                json={
                    "email": email,
                    "password": password,
                    "full_name": "User A",
                },
            )
            assert r.status_code == 200, r.text
            token = r.json()["access_token"]
            r = await c.get(
                "/whoami", headers={"Authorization": f"Bearer {token}"}
            )
            assert r.status_code == 200
            assert r.json()["user"] == email

        headers = {"Authorization": f"Bearer {token}"}

        # ---------- 2) Создание счетов ----------
        async with AsyncClient(transport=acc_tr, base_url="http://test") as c:
            r = await c.post(
                "/accounts", headers=headers, json={"currency": "USD"}
            )
            assert r.status_code == 200, r.text
            acc_usd = r.json()["id"]

            r = await c.post(
                "/accounts", headers=headers, json={"currency": "KZT"}
            )
            assert r.status_code == 200, r.text
            acc_kzt = r.json()["id"]

        # ---------- 3) Депозит USD: 200.00 ----------
        async with AsyncClient(transport=acc_tr, base_url="http://test") as c:
            r = await c.post(
                f"/accounts/{acc_usd}/deposit",
                headers=headers,
                json={"amount": 200.0, "client_key": f"dep-{acc_usd}-200"},
            )
            assert r.status_code == 200, r.text

            r = await c.get(f"/accounts/{acc_usd}", headers=headers)
            assert q2(Decimal(str(r.json()["balance"]))) == Decimal("200.00")

            r = await c.get(f"/accounts/{acc_kzt}", headers=headers)
            assert q2(Decimal(str(r.json()["balance"]))) == Decimal("0.00")

        # ---------- 4) Перевод USD->KZT (mode="from", 100 USD, fee 1%) ----------
        # ожидаем: 100 * 540 * (1 - 0.01) = 53 460.00
        expected_kzt = q2(
            Decimal("100")
            * USD_TO_KZT
            * (Decimal("1") - PERCENT / Decimal("100"))
        )
        payload1 = {
            "from_account_id": acc_usd,
            "to_account_id": acc_kzt,
            "mode": "from",
            "amount": 100.0,
            "commission_percent": float(PERCENT),
            "commission_fixed": float(FIXED),
            "client_key": "demo-req-1",
        }
        async with AsyncClient(transport=tx_tr, base_url="http://test") as c:
            r = await c.post("/transfers", headers=headers, json=payload1)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "completed"
            t1_id = body["id"]
            assert (
                q2(Decimal(str(body["amount_to"]))) == expected_kzt
            )  # 53460.00

        # Балансы после перевода
        async with AsyncClient(transport=acc_tr, base_url="http://test") as c:
            r = await c.get(f"/accounts/{acc_usd}", headers=headers)
            assert q2(Decimal(str(r.json()["balance"]))) == Decimal("100.00")
            r = await c.get(f"/accounts/{acc_kzt}", headers=headers)
            assert q2(Decimal(str(r.json()["balance"]))) == expected_kzt

        # ---------- 5) Идемпотентность (тот же client_key) ----------
        async with AsyncClient(transport=tx_tr, base_url="http://test") as c:
            r = await c.post("/transfers", headers=headers, json=payload1)
            assert r.status_code == 200, r.text
            assert r.json()["id"] == t1_id

        # ---------- 6) Перевод KZT->USD (mode="from", 10 000 KZT, fee 1%) ----------
        # грязная сумма: 10000 * (1/540) ≈ 18.5185, комиссия 1% ≈ 0.1852 → 0.19, итог ≈ 18.33
        payload2 = {
            "from_account_id": acc_kzt,
            "to_account_id": acc_usd,
            "mode": "from",
            "amount": 10000.0,
            "commission_percent": float(PERCENT),
            "commission_fixed": float(FIXED),
            "client_key": "demo-req-2",
        }
        async with AsyncClient(transport=tx_tr, base_url="http://test") as c:
            r = await c.post("/transfers", headers=headers, json=payload2)
            assert r.status_code == 200, r.text
            amt_to_usd = float(
                Decimal(str(r.json()["amount_to"])).quantize(Q2)
            )
            expected_usd = q2(
                Decimal("10000")
                * KZT_TO_USD
                * (Decimal("1") - PERCENT / Decimal("100"))
            )
            assert amt_to_usd == pytest.approx(
                float(expected_usd), rel=1e-3
            )  # ≈ 18.33

        # ---------- 7) Перевод USD->KZT (mode="to", хотим ровно 20 000 KZT) ----------
        expected_from = Decimal("20000") / (
            USD_TO_KZT * (Decimal("1") - PERCENT / Decimal("100"))
        )  # ≈ 37.43
        payload3 = {
            "from_account_id": acc_usd,
            "to_account_id": acc_kzt,
            "mode": "to",
            "amount": 20000.0,
            "commission_percent": float(PERCENT),
            "commission_fixed": float(FIXED),
            "client_key": "demo-req-3",
        }
        async with AsyncClient(transport=tx_tr, base_url="http://test") as c:
            r = await c.post("/transfers", headers=headers, json=payload3)
            assert r.status_code == 200, r.text
            body = r.json()
            assert float(body["amount_to"]) == pytest.approx(20000.0, rel=1e-6)
            assert float(
                Decimal(str(body["amount_from"])).quantize(Q2)
            ) == pytest.approx(float(q2(expected_from)), rel=1e-2)
