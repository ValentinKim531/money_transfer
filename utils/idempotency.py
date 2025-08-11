import uuid
from fastapi import Request
from starlette.responses import Response


async def idempotency_middleware(request: Request, call_next):
    idem = request.headers.get("X-Idempotency-Key")
    if not idem:
        idem = str(uuid.uuid4())
    request.state.idem_key = idem
    response: Response = await call_next(request)
    response.headers["X-Idempotency-Key"] = idem
    return response
