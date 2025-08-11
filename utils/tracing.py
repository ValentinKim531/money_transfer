from __future__ import annotations
from typing import Optional
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
import logging
from .config import settings


logger = logging.getLogger(__name__)
# Глобальный флаг — чтобы не инициализировать повторно
_TRACING_INITIALIZED = False


def setup_tracing(app: FastAPI, service_name: str) -> None:
    """
    Инициализация трассировки (однократно):
      - TracerProvider с ресурсом SERVICE_NAME
      - BatchSpanProcessor + JaegerExporter
      - Инструментирование FastAPI
    Если OTEL_SDK_DISABLED=true — OTel сам отключен, функция отработает тихо.
    """
    global _TRACING_INITIALIZED
    if _TRACING_INITIALIZED:
        return

    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: service_name})
    )
    trace.set_tracer_provider(provider)

    jaeger_exporter = JaegerExporter(
        agent_host_name=settings.jaeger_agent_host,
        agent_port=settings.jaeger_agent_port,
    )

    # Подключаем процессор
    processor = BatchSpanProcessor(jaeger_exporter)
    provider.add_span_processor(processor)

    FastAPIInstrumentor.instrument_app(app)

    _TRACING_INITIALIZED = True


def shutdown_tracing(app: Optional[FastAPI] = None) -> None:
    """
    Корректное завершение:
      - снимаем инструментирование FastAPI
      - вызываем shutdown() у текущего TracerProvider
    """
    try:
        if app is not None:
            FastAPIInstrumentor.uninstrument_app(app)
        else:
            FastAPIInstrumentor().uninstrument()
    except Exception as e:
        logger.error(f"[tracing] uninstrument failed: {e}")
        pass

    try:
        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            provider.shutdown()
    except Exception as e:
        logger.error(f"[tracing] shutdown failed: {e}")
        pass

    global _TRACING_INITIALIZED
    _TRACING_INITIALIZED = False
