#!/bin/bash
set -e

# Установка прав на папки и файлы для Docker
if [ -d logs ]; then
    chown -R 1000:1000 logs || true
    chmod -R 755 logs || true
fi
if [ -d env ]; then
    chmod -R 755 env || true
fi
if [ -f config.json ]; then
    chmod 666 config.json || true
fi

if [[ "$1" == "test" ]]; then
    echo "[INFO] Запуск тестов..."
    pytest tests/
    exit $?
fi

if docker-compose ps | grep -q 'Up'; then
    echo "[INFO] Контейнеры уже запущены."
    docker-compose ps
else
    echo "[INFO] Сборка и запуск контейнеров..."
    docker-compose build
    docker-compose up -d
fi
