FROM python:3.12-slim-bookworm

LABEL maintainer="Jatixs"
LABEL description="Telegram VPS Bot"

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

RUN pip install --no-cache-dir docker

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
