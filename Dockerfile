# /opt-tg-bot/Dockerfile

# 1. Базовый образ
FROM python:3.10-slim-bookworm

LABEL maintainer="Jatixs"
LABEL description="Telegram VPS Bot"

# 2. Установка системных зависимостей
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

# 3. Установка Python-библиотеки Docker (для watchdog)
RUN pip install --no-cache-dir docker

# 4. Создание пользователя 'tgbot' (для режима secure)
# UID/GID 1001.
RUN groupadd -g 1001 tgbot && \
    useradd -u 1001 -g 1001 -m -s /bin/bash tgbot && \
    # Даем пользователю tgbot права sudo внутри контейнера (для режима secure)
    echo "tgbot ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# 5. Настройка рабочей директории
WORKDIR /opt-tg-bot

# 6. Установка зависимостей Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 7. Копирование всего кода приложения
COPY . .

# 8. Создание и выдача прав на директории config и logs
# (Они будут переопределены volumes, но это гарантирует правильные права)
RUN mkdir -p /opt/tg-bot/config /opt/tg-bot/logs/bot /opt/tg-bot/logs/watchdog && \
    chown -R tgbot:tgbot /opt/tg-bot

# 9. Установка пользователя 'tgbot' по умолчанию
# (docker-compose переопределит это на 'root' для root-режима)
USER tgbot

# 10. Команда по умолчанию
CMD ["python", "bot.py"]