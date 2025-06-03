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
from datetime import datetime
import pytz
import os
from dotenv import load_dotenv
import logging
from logging.handlers import TimedRotatingFileHandler

# Уровень отладки
DEBUG = os.getenv('DEBUG', '0').lower() in ('1', 'true', 'yes')

# Загрузка переменных окружения из .env
load_dotenv()

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# TTLock API параметры из .env
client_id = os.getenv("TTLOCK_CLIENT_ID")
client_secret = os.getenv("TTLOCK_CLIENT_SECRET")
username = os.getenv("TTLOCK_USERNAME")
password = os.getenv("TTLOCK_PASSWORD")
lock_id_env = os.getenv("TTLOCK_LOCK_ID")

# Telegram параметры
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

if not all([client_id, client_secret, username, password]):
    raise RuntimeError("Не заданы все переменные окружения TTLOCK_CLIENT_ID, TTLOCK_CLIENT_SECRET, TTLOCK_USERNAME, TTLOCK_PASSWORD. Проверьте .env файл!")

# Максимум попыток и задержка между ними
MAX_RETRIES = 3
RETRY_DELAY = 2

# Часовой пояс Новосибирска
TZ = pytz.timezone('Asia/Novosibirsk')

# Глобальная переменная для lock_id, если он найден при старте
LOCK_ID = None

# Настройка логирования с ротацией (14 дней)
LOG_FILENAME = "logs/auto_unlocker.log"
os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("auto_unlocker")
logger.setLevel(logging.INFO)
handler = TimedRotatingFileHandler(LOG_FILENAME, when="midnight", backupCount=14, encoding="utf-8")
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


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


def get_token():
    """
    Получает access_token для TTLock Cloud API по логину/паролю владельца аккаунта.
    :return: access_token или None
    """
    url = "https://euapi.ttlock.com/oauth2/token"
    password_md5 = hashlib.md5(password.encode()).hexdigest()
    data = {
        "username": username,
        "password": password_md5,
        "clientId": client_id,
        "clientSecret": client_secret
    }
    response = requests.post(url, data=data, verify=False)
    if DEBUG:
        debug_request("Получение токена", url, data, response)
    response_data = response.json()
    if response.status_code == 200 and "access_token" in response_data:
        if DEBUG:
            print("Токен получен успешно")
        logger.info("Токен TTLock получен успешно")
        return response_data["access_token"]
    else:
        msg = f"Ошибка получения токена: {response_data}"
        print(msg)
        logger.error(msg)
        send_telegram_message(f"❗️ <b>Ошибка получения токена TTLock</b>\n{response_data}")
        return None


def list_locks(token):
    """
    Запрашивает список замков, доступных для данного access_token (только для владельца).
    :param token: access_token
    :return: список замков (list)
    """
    url = "https://euapi.ttlock.com/v3/lock/list"
    data = {
        "clientId": client_id,
        "accessToken": token,
        "pageNo": 1,
        "pageSize": 20,
        "date": int(time.time() * 1000)
    }
    try:
        response = requests.post(url, data=data, verify=False)
        if DEBUG:
            debug_request("Список замков", url, data, response)
        response_data = response.json()
        return response_data.get("list", [])
    except Exception as e:
        msg = f"Ошибка получения списка замков: {str(e)}"
        print(msg)
        logger.error(msg)
        send_telegram_message(f"❗️ <b>Ошибка получения списка замков</b>\n{str(e)}")
        return []


def unlock_lock(token, lock_id):
    """
    Пытается открыть замок с указанным lock_id через облако.
    :param token: access_token
    :param lock_id: идентификатор замка
    :return: True/False
    """
    url = "https://euapi.ttlock.com/v3/lock/unlock"
    data = {
        "clientId": client_id,
        "lockId": lock_id,
        "accessToken": token,
        "date": int(time.time() * 1000)
    }
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(url, data=data, verify=False)
            if DEBUG:
                debug_request("Открытие замка", url, data, response)
            response_data = response.json()
            if "errcode" in response_data and response_data["errcode"] == 0:
                msg = f"✅ Замок {lock_id} открыт успешно"
                if DEBUG:
                    print(msg)
                logger.info(msg)
                send_telegram_message(msg)
                return True
            elif "errcode" in response_data and response_data["errcode"] == -3037:
                if attempt < MAX_RETRIES - 1:
                    msg = f"Замок {lock_id} занят. Повтор через {RETRY_DELAY} сек... (Попытка {attempt + 1}/{MAX_RETRIES})"
                    print(msg)
                    logger.warning(msg)
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    msg = f"Замок {lock_id} занят. Достигнут лимит попыток. Попробуйте позже."
                    print(msg)
                    logger.error(msg)
                    send_telegram_message(f"❗️ <b>Ошибка открытия замка</b>\n{msg}")
                    return False
            else:
                msg = f"Ошибка при открытии замка {lock_id}: {response_data.get('errmsg', 'Unknown error')} (Код: {response_data.get('errcode')})"
                print(msg)
                logger.error(msg)
                send_telegram_message(f"❗️ <b>Ошибка открытия замка</b>\n{msg}")
                return False
        except Exception as e:
            msg = f"Ошибка при запросе открытия замка {lock_id}: {str(e)}"
            print(msg)
            logger.error(msg)
            send_telegram_message(f"❗️ <b>Ошибка открытия замка</b>\n{msg}")
            return False
    return False


def resolve_lock_id(token):
    """
    Пытается получить lock_id из .env, либо из первого замка в списке.
    :param token: access_token
    :return: lock_id или None
    """
    if lock_id_env:
        if DEBUG:
            print(f"lock_id найден в .env: {lock_id_env}")
        logger.info(f"lock_id найден в .env: {lock_id_env}")
        send_telegram_message(f"ℹ️ lock_id найден в .env: <code>{lock_id_env}</code>")
        return lock_id_env
    locks = list_locks(token)
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
    Основная задача: открыть замок в 9:00 по Новосибирску.
    """
    global LOCK_ID
    now_str = datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')
    msg = f"\n[{now_str}] Запуск задачи открытия замка..."
    print(msg)
    logger.info(msg)
    send_telegram_message(f"🔔 <b>Запуск задачи открытия замка</b>\n{now_str}")
    token = get_token()
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
    unlock_lock(token, LOCK_ID)


def main():
    """
    Точка входа: определяет lock_id, запускает планировщик.
    """
    global LOCK_ID
    print("\n[INIT] Определение lock_id...")
    logger.info("[INIT] Определение lock_id...")
    send_telegram_message("🚀 <b>Сервис авто-открытия замка TTLock запущен</b>")
    token = get_token()
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
    # Планируем задачу на 9:00 утра по Новосибирску каждый день
    schedule.every().day.at("09:00").do(job)
    print("Сервис авто-открытия замка запущен. Ожидание 9:00 по Новосибирску...")
    logger.info("Сервис авто-открытия замка запущен. Ожидание 9:00 по Новосибирску...")
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    main()

