FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl wget && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requgit remote add origin https://github.com/ValentinKim531/money_transfer.gitirements.txt

COPY . .
ENV PYTHONPATH=/app

RUN mkdir -p /app/money_transfer/data
