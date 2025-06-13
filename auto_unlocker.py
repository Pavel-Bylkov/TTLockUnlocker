"""
Автоматическое открытие замка TTLock каждый день в 9:00 утра по Новосибирскому времени.
Скрипт для запуска в Docker-контейнере.
Все параметры берутся из .env (client_id, client_secret, username, password, lock_id, telegram).
Если lock_id не задан — определяется при первом запуске и используется до перезапуска.
Важные события отправляются в Telegram и пишутся в лог с ротацией (14 дней).
"""
import requests
import json
import time
import hashlib
import urllib3
import schedule
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import logging
from logging.handlers import TimedRotatingFileHandler
import ttlock_api

# Определяем путь к .env: сначала из ENV_PATH, иначе env/.env
ENV_PATH = os.getenv('ENV_PATH') or 'env/.env'
# Загрузка переменных окружения
load_dotenv(ENV_PATH)

# Уровень отладки
DEBUG = os.getenv('DEBUG', '0').lower() in ('1', 'true', 'yes')

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# TTLock API параметры из .env
client_id = os.getenv("TTLOCK_CLIENT_ID")
client_secret = os.getenv("TTLOCK_CLIENT_SECRET")
username = os.getenv("TTLOCK_USERNAME")
password = os.getenv("TTLOCK_PASSWORD")
# Удаляем получение lock_id_env здесь

# Telegram параметры
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

REQUIRED_ENV_VARS = [
    'TTLOCK_CLIENT_ID',
    'TTLOCK_CLIENT_SECRET',
    'TTLOCK_USERNAME',
    'TTLOCK_PASSWORD',
    'TELEGRAM_BOT_TOKEN',
    'TELEGRAM_CHAT_ID',
]
missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_vars:
    print(f"[ERROR] Не заданы обязательные переменные окружения: {', '.join(missing_vars)}. Проверьте .env файл!")
    exit(1)

if not all([client_id, client_secret, username, password]):
    raise RuntimeError("Не заданы все переменные окружения TTLOCK_CLIENT_ID, TTLOCK_CLIENT_SECRET, TTLOCK_USERNAME, TTLOCK_PASSWORD. Проверьте .env файл!")

# Максимум попыток и задержка между ними
MAX_RETRIES = 3
RETRY_DELAY = 2
MAX_RETRY_TIME = 21  # Максимальное время для повторных попыток (21:00)
RETRY_TIME_SHIFT = 15  # Смещение времени на 15 минут при неудаче

# Глобальная переменная для lock_id, если он найден при старте
LOCK_ID = None

CONFIG_PATH = os.getenv("CONFIG_PATH", "config.json")

LOG_FILENAME = "logs/auto_unlocker.log"
os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("auto_unlocker")
logger.setLevel(logging.INFO)
handler = TimedRotatingFileHandler(LOG_FILENAME, when="midnight", backupCount=14, encoding="utf-8")
formatter = ttlock_api.TZFormatter('%(asctime)s %(levelname)s: %(message)s', '%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)
logger.handlers.clear()
logger.addHandler(handler)

def load_config():
    """Загружает настройки из config.json. Если нет файла — возвращает дефолтные значения."""
    default = {
        "timezone": "Asia/Novosibirsk",
        "schedule_enabled": True,
        "open_times": {
            "monday": "09:00",
            "tuesday": "09:00",
            "wednesday": "09:00",
            "thursday": "09:00",
            "friday": "09:00",
            "saturday": None,
            "sunday": None
        },
        "breaks": {
            "monday": ["13:00-14:00"],
            "tuesday": [],
            "wednesday": [],
            "thursday": [],
            "friday": [],
            "saturday": [],
            "sunday": []
        }
    }
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def send_telegram_message(text):
    """
    Отправляет сообщение в Telegram, если заданы токен и chat_id.
    :param text: Текст сообщения
    """
    if not telegram_token or not telegram_chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы, Telegram-уведомление не отправлено.")
        return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {
        "chat_id": telegram_chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, data=payload, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"Ошибка отправки Telegram: {resp.text}")
    except Exception as e:
        logger.warning(f"Ошибка отправки Telegram: {str(e)}")


def debug_request(name, url, data, response):
    """
    Подробный отладочный вывод HTTP-запроса и ответа.
    :param name: Название операции
    :param url: URL запроса
    :param data: Данные запроса
    :param response: Ответ requests
    """
    print(f"\n[DEBUG] {name}")
    print(f"URL: {url}")
    print(f"Параметры запроса: {json.dumps(data, ensure_ascii=False)}")
    print(f"Статус ответа: {response.status_code}")
    try:
        print(f"Тело ответа: {json.dumps(response.json(), ensure_ascii=False)}")
    except Exception:
        print(f"Тело ответа (не JSON): {response.text}")


def resolve_lock_id(token):
    """
    Пытается получить lock_id из .env, либо из первого замка в списке.
    :param token: access_token
    :return: lock_id или None
    """
    lock_id_env = os.getenv("TTLOCK_LOCK_ID")  # Получаем lock_id_env здесь
    if lock_id_env:
        if DEBUG:
            print(f"lock_id найден в .env: {lock_id_env}")
        logger.info(f"lock_id найден в .env: {lock_id_env}")
        send_telegram_message(f"ℹ️ lock_id найден в .env: <code>{lock_id_env}</code>")
        return lock_id_env
    locks = ttlock_api.list_locks(token)
    if not locks:
        msg = "Замки не найдены. Проверьте права доступа."
        print(msg)
        logger.error(msg)
        send_telegram_message(f"❗️ <b>Ошибка: замки не найдены</b>")
        return None
    first_lock = locks[0]
    lock_id = first_lock.get('lockId')
    msg = f"lock_id выбран из списка: {lock_id}"
    print(msg)
    logger.info(msg)
    send_telegram_message(f"ℹ️ lock_id выбран из списка: <code>{lock_id}</code>")
    return lock_id


def job():
    """
    Основная задача: открыть замок в заданное время.
    При неудаче делает повторные попытки с временным смещением.
    """
    global LOCK_ID
    now = ttlock_api.get_now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    msg = f"\n[{now_str}] Запуск задачи открытия замка..."
    print(msg)
    logger.info(msg)
    send_telegram_message(f"🔔 <b>Запуск задачи открытия замка</b>\n{now_str}")
    
    token = ttlock_api.get_token(logger)
    if not token:
        msg = "Не удалось получить токен, задача пропущена."
        print(msg)
        logger.error(msg)
        send_telegram_message(f"❗️ <b>Ошибка: не удалось получить токен</b>")
        return

    if LOCK_ID is None:
        LOCK_ID = resolve_lock_id(token)
        if LOCK_ID is None:
            msg = "Не удалось определить lock_id. Задача пропущена."
            print(msg)
            logger.error(msg)
            send_telegram_message(f"❗️ <b>Ошибка: не удалось определить lock_id</b>")
            return

    current_hour = now.hour
    retry_count = 0
    max_retries = MAX_RETRIES

    while current_hour < MAX_RETRY_TIME and retry_count < max_retries:
        if retry_count > 0:
            msg = f"Повторная попытка {retry_count}/{max_retries} в {now.strftime('%H:%M')}"
            print(msg)
            logger.info(msg)
            send_telegram_message(f"🔄 <b>{msg}</b>")
            time.sleep(RETRY_DELAY)

        result = ttlock_api.unlock_lock(token, LOCK_ID, logger, send_telegram_message)
        
        if result.get('success'):
            msg = f"✅ Замок успешно открыт (попытка {retry_count + 1})"
            print(msg)
            logger.info(msg)
            send_telegram_message(f"✅ <b>{msg}</b>")
            return
        elif result.get('errcode') == -3037:  # Замок занят
            retry_count += 1
            if retry_count < max_retries:
                continue
            elif current_hour < MAX_RETRY_TIME - 1:  # Если еще не поздно
                # Смещаем время на 15 минут вперед
                now = now + timedelta(minutes=RETRY_TIME_SHIFT)
                current_hour = now.hour
                retry_count = 0
                msg = f"⏰ Смещаем время открытия на {now.strftime('%H:%M')}"
                print(msg)
                logger.info(msg)
                send_telegram_message(f"⏰ <b>{msg}</b>")
                continue
        else:
            msg = f"❌ Ошибка при открытии замка: {result.get('errmsg', 'Unknown error')}"
            print(msg)
            logger.error(msg)
            send_telegram_message(f"❌ <b>{msg}</b>")
            return

    msg = f"❌ Не удалось открыть замок после всех попыток до {MAX_RETRY_TIME}:00"
    print(msg)
    logger.error(msg)
    send_telegram_message(f"❌ <b>{msg}</b>")


def main():
    """
    Точка входа: определяет lock_id, запускает планировщик.
    """
    global LOCK_ID
    config = load_config()
    tz = config.get("timezone", "Asia/Novosibirsk")
    schedule_enabled = config.get("schedule_enabled", True)
    open_times = config.get("open_times", {})
    breaks = config.get("breaks", {})

    print("\n[INIT] Определение lock_id...")
    logger.info("[INIT] Определение lock_id...")
    send_telegram_message("🚀 <b>Сервис авто-открытия замка TTLock запущен</b>")
    token = ttlock_api.get_token(logger)
    if not token:
        msg = "Не удалось получить токен при инициализации. Скрипт завершён."
        print(msg)
        logger.error(msg)
        send_telegram_message(f"❗️ <b>Ошибка: не удалось получить токен при инициализации</b>")
        return
    LOCK_ID = resolve_lock_id(token)
    if LOCK_ID is None:
        msg = "Не удалось определить lock_id при инициализации. Скрипт завершён."
        print(msg)
        logger.error(msg)
        send_telegram_message(f"❗️ <b>Ошибка: не удалось определить lock_id при инициализации</b>")
        return
    print(f"lock_id для работы: {LOCK_ID}")
    logger.info(f"lock_id для работы: {LOCK_ID}")
    send_telegram_message(f"ℹ️ lock_id для работы: <code>{LOCK_ID}</code>")

    if not schedule_enabled:
        print("[INFO] Автоматическое расписание отключено через config.json")
        logger.info("Автоматическое расписание отключено через config.json")
        send_telegram_message("ℹ️ Автоматическое расписание <b>отключено</b> через config.json")
        while True:
            time.sleep(60)

    # Планируем задачи по дням недели
    for day, open_time in open_times.items():
        if open_time:
            getattr(schedule.every(), day).at(open_time).do(job)
            print(f"[SCHEDULE] {day}: открытие в {open_time}")
            logger.info(f"[SCHEDULE] {day}: открытие в {open_time}")
        # Перерывы (закрытие/открытие)
        for interval in breaks.get(day, []):
            try:
                close_time, reopen_time = interval.split("-")
                # Закрытие
                def make_close(day=day):
                    def _close():
                        token = ttlock_api.get_token(logger)
                        if token and LOCK_ID:
                            send_telegram_message(f"🔒 <b>Перерыв: закрытие замка</b> ({day})")
                            ttlock_api.lock_lock(token, LOCK_ID, logger, send_telegram_message)
                    return _close
                getattr(schedule.every(), day).at(close_time).do(make_close())
                print(f"[SCHEDULE] {day}: закрытие в {close_time}")
                logger.info(f"[SCHEDULE] {day}: закрытие в {close_time}")
                # Открытие после перерыва
                def make_reopen(day=day):
                    def _open():
                        token = ttlock_api.get_token(logger)
                        if token and LOCK_ID:
                            send_telegram_message(f"🔓 <b>Перерыв окончен: открытие замка</b> ({day})")
                            ttlock_api.unlock_lock(token, LOCK_ID, logger, send_telegram_message)
                    return _open
                getattr(schedule.every(), day).at(reopen_time).do(make_reopen())
                print(f"[SCHEDULE] {day}: открытие после перерыва в {reopen_time}")
                logger.info(f"[SCHEDULE] {day}: открытие после перерыва в {reopen_time}")
            except Exception as e:
                print(f"[ERROR] Ошибка разбора интервала перерыва {interval} для {day}: {e}")
                logger.error(f"Ошибка разбора интервала перерыва {interval} для {day}: {e}")

    print("Сервис авто-открытия замка запущен. Ожидание событий по расписанию...")
    logger.info("Сервис авто-открытия замка запущен. Ожидание событий по расписанию...")
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    main()

