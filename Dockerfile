# syntax=docker/dockerfile:1.4
FROM python:3.10-slim

RUN useradd -m appuser
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY auto_unlocker.py ./
COPY ttlock_api.py ./
COPY telegram_utils.py ./
RUN mkdir -p /app/logs && chown appuser:appuser /app/logs && chown appuser:appuser auto_unlocker.py ttlock_api.py telegram_utils.py || true
ENV TZ=Asia/Novosibirsk
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
USER appuser

# Healthcheck: скрипт должен быть живым процессом
HEALTHCHECK --interval=1m --timeout=10s CMD pgrep -f auto_unlocker.py || exit 1

CMD ["python", "auto_unlocker.py"] 
