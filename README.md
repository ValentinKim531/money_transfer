# Money Transfer Service

Сервис для регистрации пользователей, создания счетов, пополнений, списаний и переводов валют между счетами.  
Стек: **FastAPI**, **RabbitMQ**, **Jaeger**, **SQLite**, **Docker Compose**.

---

## Запуск проекта

1. Переименовать `.env.example` → `.env`  
```bash
cp .env.example .env
```

2.	Собрать и запустить контейнеры:
```bash
docker-compose up -d --build
```

3. Доступы по умолчанию:
	•	Auth API: http://localhost:8001/docs
	•	Accounts API: http://localhost:8002/docs
	•	Transactions API: http://localhost:8003/docs
	•	RabbitMQ UI: http://localhost:15672 (логин: guest, пароль: guest)
	•	Jaeger UI: http://localhost:16686


## Основные операции (через curl):

1️⃣ Регистрация пользователя
```bash
curl -X POST http://localhost:8001/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@test.com","password":"pw12345678","full_name":"User Test"}'
```

2️⃣ Вход в систему
```bash
curl -X POST http://localhost:8001/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@test.com","password":"pw12345678"}'
```

3️⃣ Провека токена:
```bash
curl -X GET http://localhost:8001/whoami
```


4️⃣ Создание счета
```bash
curl -X POST http://localhost:8002/accounts \
  -H "Authorization: Bearer <ВАШ_ТОКЕН>" \
  -H "Content-Type: application/json" \
  -d '{"currency":"USD"}'
````

```bash  
curl -X POST http://localhost:8002/accounts \
  -H "Authorization: Bearer <ВАШ_ТОКЕН>" \
  -H "Content-Type: application/json" \
  -d '{"currency":"KZT"}'
```

5️⃣ Пополнение счета
```bash
curl -X POST http://localhost:8002/accounts/<ACCOUNT_ID>/deposit \
  -H "Authorization: Bearer <ВАШ_ТОКЕН>" \
  -H "Content-Type: application/json" \
  -d '{"amount":200.0, "client_key":"dep-1-200"}'
```

6️⃣ Списание со счета
```bash
curl -X POST http://localhost:8002/accounts/<ACCOUNT_ID>/withdraw \
  -H "Authorization: Bearer <ВАШ_ТОКЕН>" \
  -H "Content-Type: application/json" \
  -d '{"amount":50.0, "client_key":"wd-1-50"}'
```

7️⃣ Перевод между счетами
```bash
curl -X POST http://localhost:8003/transfers \
  -H "Authorization: Bearer <ВАШ_ТОКЕН>" \
  -H "Content-Type: application/json" \
  -d '{
    "from_account_id": 1,
    "to_account_id": 2,
    "mode": "from",
    "amount": 100.0,
    "commission_percent": 1.0,
    "commission_fixed": 0.0,
    "client_key": "tx-1-to-2-100-from"
  }'
```
