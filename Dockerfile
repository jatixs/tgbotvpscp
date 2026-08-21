# -- Stage 1: Builder --
FROM python:3.10-slim-bookworm AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip 'setuptools>=83.0.0' wheel && \
    pip wheel --no-cache-dir --wheel-dir /build/wheels \
    docker \
    aiohttp==3.14.3 \
    aiosqlite \
    argon2-cffi \
    'msgpack>=1.2.1' \
    sentry-sdk \
    tortoise-orm \
    aerich \
    cryptography \
    tomlkit \
    -r requirements.txt

# -- Stage 2: Final --
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
    && dpkg-query -W openssl libssl3 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir --upgrade pip 'setuptools>=83.0.0' wheel && \
    pip install --no-cache-dir /wheels/* && \
    rm -rf /wheels

RUN groupadd -g 1001 tgbot && \
    useradd -u 1001 -g 1001 -m -s /bin/bash tgbot && \
    echo "tgbot ALL=(ALL) NOPASSWD: /opt/tg-bot/scripts/update_os.sh, /usr/bin/systemctl, /bin/journalctl" >> /etc/sudoers

WORKDIR /opt/tg-bot
COPY . .
RUN mkdir -p /opt/tg-bot/config /opt/tg-bot/logs/bot /opt/tg-bot/logs/watchdog && \
    chown -R tgbot:tgbot /opt/tg-bot

USER tgbot
CMD ["python", "bot.py"]
