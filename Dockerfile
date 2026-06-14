FROM python:3.10-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get dist-upgrade -y \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
    openssl \
    libssl3 \
    python3-yaml \
    iperf3 \
    git \
    curl \
    wget \
    sudo \
    procps \
    iputils-ping \
    net-tools \
    gnupg \
    docker.io \
    coreutils \
    gcc \
    python3-dev \
    && dpkg-query -W openssl libssl3 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir \
    docker \
    aiohttp==3.13.5 \
    aiosqlite \
    argon2-cffi \
    sentry-sdk \
    tortoise-orm \
    aerich \
    cryptography \
    tomlkit

RUN groupadd -g 1001 tgbot && \
    useradd -u 1001 -g 1001 -m -s /bin/bash tgbot && \
    echo "tgbot ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

WORKDIR /opt/tg-bot
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /opt/tg-bot/config /opt/tg-bot/logs/bot /opt/tg-bot/logs/watchdog && \
    chown -R tgbot:tgbot /opt/tg-bot

USER tgbot
CMD ["python", "bot.py"]
