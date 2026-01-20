FROM python:3.12-slim-bookworm
LABEL maintainer="Jatixs <https://github.com/jatixs>"
LABEL org.opencontainers.image.source="https://github.com/jatixs/tgbotvpscp"
LABEL org.opencontainers.image.description="VPS Manager Telegram Bot"
LABEL org.opencontainers.image.licenses="MIT"
RUN apt-get update && apt-get install -y \
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
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir docker aiohttp aiosqlite argon2-cffi sentry-sdk tortoise-orm aerich cryptography tomlkit
RUN groupadd -g 1001 tgbot && useradd -u 1001 -g 1001 -m -s /bin/bash tgbot && \
    echo "tgbot ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers
WORKDIR /opt/tg-bot
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /opt/tg-bot/config /opt/tg-bot/logs/bot /opt/tg-bot/logs/watchdog && \
    chown -R tgbot:tgbot /opt/tg-bot
USER tgbot
CMD ["python", "bot.py"]