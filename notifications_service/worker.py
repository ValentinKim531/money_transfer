import os
import asyncio
import logging
import aio_pika
from aio_pika import RobustConnection, Channel
from aio_pika.exceptions import AMQPConnectionError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("notifications")

RABBIT_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
QUEUE_NAME = "transfer_notifications"


async def connect_with_retry(
    url: str, attempts: int = 30, delay: float = 2.0
) -> RobustConnection:
    """
    Пытаемся подключиться к RabbitMQ несколько раз (чтобы дождаться старта брокера).
    """
    last_err = None
    for i in range(1, attempts + 1):
        try:
            log.info("[rmq] connect attempt %d to %s", i, url)
            conn: RobustConnection = await aio_pika.connect_robust(url)
            log.info("[rmq] connected")
            return conn
        except AMQPConnectionError as e:
            last_err = e
            log.warning("[rmq] connect failed: %s; retry in %.1fs", e, delay)
            await asyncio.sleep(delay)
    raise RuntimeError(
        f"RabbitMQ not available after {attempts} attempts: {last_err}"
    )


async def main():
    log.info("[notifications] starting consumer… RABBITMQ_URL=%s", RABBIT_URL)

    connection = await connect_with_retry(RABBIT_URL)
    channel: Channel = await connection.channel()

    queue = await channel.declare_queue(QUEUE_NAME, durable=True)
    log.info("[notifications] queue declared: %s", QUEUE_NAME)

    async with queue.iterator() as q:
        async for message in q:
            async with message.process(requeue=False):
                body = message.body.decode("utf-8", errors="replace")
                log.info("[notify] received: %s", body)
                # await send_telegram(json.loads(body))  # пример


if __name__ == "__main__":
    asyncio.run(main())
