"""
Автоматическое открытие замка TTLock каждый день в заданное время.
Скрипт для запуска в Docker-контейнере.
Все параметры берутся из .env (client_id, client_secret, username, password, lock_id, telegram).
Если lock_id не задан — определяется при первом запуске и используется до перезапуска.
Важные события отправляются в Telegram и пишутся в лог с ротацией (14 дней).
"""
import requests
import json
import time as time_module
import hashlib
import urllib3
import schedule
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import logging
from logging.handlers import TimedRotatingFileHandler
import ttlock_api
from typing import Optional, Dict, List, Any, Union
import re
from telegram_utils import send_telegram_message, log_message, load_config, save_config, send_email_notification, log_exception
import sys
import traceback

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

# Telegram параметры
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

# Email-уведомления
EMAIL_TO = os.getenv("EMAIL_TO")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = os.getenv("SMTP_PORT")
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
AUTHORIZED_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TTLOCK_LOCK_ID = os.getenv("TTLOCK_LOCK_ID")
CONFIG_PATH = os.getenv("CONFIG_PATH", "config.json")

REQUIRED_ENV_VARS = [
    'TTLOCK_CLIENT_ID',
    'TTLOCK_CLIENT_SECRET',
    'TTLOCK_USERNAME',
    'TTLOCK_PASSWORD',
    'TELEGRAM_BOT_TOKEN',
    'TELEGRAM_CHAT_ID',
    'EMAIL_TO',
    'SMTP_SERVER',
    'SMTP_PORT',
    'SMTP_USER',
    'SMTP_PASSWORD',
]

missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_vars:
    # Используем логгер для критической ошибки, если он уже настроен
    # или print, если еще нет.
    # В данном случае логгер еще не настроен, поэтому print оправдан.
    print(f"[CRITICAL] Не заданы обязательные переменные окружения: {', '.join(missing_vars)}. Проверьте .env файл!")
    exit(1)

# Настройка логирования
os.makedirs('logs', exist_ok=True)
logger = logging.getLogger("auto_unlocker")
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO) # Устанавливаем уровень в зависимости от DEBUG

handler = TimedRotatingFileHandler('logs/auto_unlocker.log', when="midnight", backupCount=14, encoding="utf-8")
formatter = ttlock_api.TZFormatter('%(asctime)s %(levelname)s: %(message)s', '%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)
logger.handlers.clear()
logger.addHandler(handler)

# Дублируем логи в stdout для Docker
console = logging.StreamHandler(sys.stdout)
console.setFormatter(formatter)
logger.addHandler(console)

if DEBUG:
    logger.debug(f"Используется путь к .env: {ENV_PATH}")

if not all([client_id, client_secret, username, password]):
    logger.critical("Не заданы все переменные окружения TTLOCK_CLIENT_ID, TTLOCK_CLIENT_SECRET, TTLOCK_USERNAME, TTLOCK_PASSWORD. Проверьте .env файл!")
    raise RuntimeError("Не заданы все переменные окружения TTLOCK_CLIENT_ID, TTLOCK_CLIENT_SECRET, TTLOCK_USERNAME, TTLOCK_PASSWORD. Проверьте .env файл!")

# Глобальная переменная для lock_id, если он найден при старте
LOCK_ID = None

LOG_FILENAME = "logs/auto_unlocker.log"

def execute_lock_action_with_retries(action_func, token: str, lock_id: str, action_name: str, success_msg: str, failure_msg_part: str) -> bool:
    """
    Выполняет действие с замком, используя определенный график повторных попыток.

    Args:
        action_func: Функция для вызова (ttlock_api.unlock_lock или ttlock_api.lock_lock).
        token: Токен TTLock API.
        lock_id: ID замка.
        action_name: Название действия для логов (например, "открытия").
        success_msg: Сообщение для логов и Telegram при успехе (например, "открыт").
        failure_msg_part: Часть сообщения для уведомлений о сбое (например, "открытие замка").

    Returns:
        True, если действие выполнено успешно, иначе False.
    """
    # Задержки в секундах между попытками: 30с, 1м, 5м, 10м, и 5 раз по 15м
    delays = [30, 60, 5 * 60, 10 * 60] + [15 * 60] * 5
    total_attempts = len(delays) + 1
    last_error = "Неизвестная ошибка"

    for attempt in range(1, total_attempts + 1):
        logger.info(f"Попытка #{attempt} {action_name} замка...")
        response = action_func(token, lock_id, logger)

        if response and response.get("errcode") == 0:
            logger.info(f"Замок успешно {success_msg}!")
            send_telegram_message(telegram_token, telegram_chat_id, f"✅ <b>Замок успешно {success_msg} (попытка #{attempt})</b>", logger)
            return True  # Успех

        last_error = response.get('errmsg', 'Неизвестная ошибка') if response else 'Ответ от API не получен'
        logger.error(f"Попытка #{attempt} не удалась: {last_error}")

        # Уведомление после 5-й неудачной попытки
        if attempt == 5:
            msg = f"❗️ Не удалось выполнить {failure_msg_part} после 5 попыток. Отправляю email."
            logger.warning(msg)
            send_telegram_message(telegram_token, telegram_chat_id, msg, logger)
            send_email_notification(
                subject=f"Проблема с TTLock: Замок {lock_id}",
                body=f"Не удалось выполнить {failure_msg_part} для замка {lock_id} после 5 попыток.\nПоследняя ошибка: {last_error}"
            )

        # Ожидание перед следующей попыткой
        if attempt < total_attempts:
            delay = delays[attempt - 1]
            logger.info(f"Ожидание {delay // 60 if delay >= 60 else delay} {'мин' if delay >= 60 else 'сек'} перед следующей попыткой...")
            time_module.sleep(delay)

    # Если все попытки провалились
    final_error_msg = f"🔥 <b>КРИТИЧЕСКАЯ ОШИБКА:</b> Все {total_attempts} попыток {action_name} замка не удались. Последняя ошибка: {last_error}. Требуется ручное вмешательство."
    logger.critical(final_error_msg)
    send_telegram_message(telegram_token, telegram_chat_id, final_error_msg, logger)
    send_email_notification(
        subject=f"Критическая ошибка TTLock: Замок {lock_id} не отвечает",
        body=final_error_msg
    )

    return False  # Провал

def debug_request(name: str, url: str, data: Dict[str, Any], response: requests.Response) -> None:
    """
    Подробный отладочный вывод HTTP-запроса и ответа.

    Args:
        name: Название операции
        url: URL запроса
        data: Данные запроса
        response: Ответ requests
    """
    logger.debug(f"===== HTTP DEBUG: {name} =====")
    logger.debug(f"URL: {url}")
    logger.debug(f"Request Data: {json.dumps(data, ensure_ascii=False)}")
    logger.debug(f"Response Status: {response.status_code}")
    try:
        logger.debug(f"Response Body: {json.dumps(response.json(), ensure_ascii=False)}")
    except Exception:
        logger.debug(f"Response Body (not JSON): {response.text}")
    logger.debug("===== END HTTP DEBUG =====")

def resolve_lock_id(token: str) -> Optional[str]:
    """
    Пытается получить lock_id из .env, либо из первого замка в списке.

    Args:
        token: access_token

    Returns:
        str: lock_id или None в случае ошибки
    """
    lock_id_env = os.getenv("TTLOCK_LOCK_ID")
    if lock_id_env:
        logger.info(f"Используется lock_id из .env: {lock_id_env}")
        send_telegram_message(telegram_token, telegram_chat_id, f"ℹ️ lock_id найден в .env: <code>{lock_id_env}</code>", logger)
        return lock_id_env

    locks = ttlock_api.list_locks(token)
    if not locks:
        msg = "Замки не найдены. Проверьте права доступа."
        logger.error(msg)
        send_telegram_message(telegram_token, telegram_chat_id, f"❗️ <b>Ошибка: замки не найдены</b>", logger)
        return None

    first_lock = locks[0]
    lock_id = first_lock.get('lockId')
    msg = f"lock_id не был задан в .env, выбран первый из списка: {lock_id}"
    logger.info(msg)
    send_telegram_message(telegram_token, telegram_chat_id, f"ℹ️ lock_id выбран из списка: <code>{lock_id}</code>", logger)
    return lock_id

def job() -> None:
    """
    Основная задача: проверяет время и открывает замок если нужно.
    При неудаче делает повторные попытки с новой логикой.
    """
    # Получаем LOCK_ID из переменных окружения
    LOCK_ID = os.getenv('TTLOCK_LOCK_ID')

    logger.debug("-> job: начало выполнения задачи")

    # Получаем текущее время в нужном часовом поясе
    now = ttlock_api.get_now()
    current_time = now.strftime("%H:%M")

    # Преобразуем день недели в русский формат
    day_mapping = {
        "monday": "Пн",
        "tuesday": "Вт",
        "wednesday": "Ср",
        "thursday": "Чт",
        "friday": "Пт",
        "saturday": "Сб",
        "sunday": "Вс"
    }
    current_day = day_mapping.get(now.strftime("%A").lower())

    logger.debug(f"Текущий день: {current_day}, время: {current_time}")

    # Проверяем, нужно ли открывать замок
    cfg = load_config(CONFIG_PATH, logger, default={
        "timezone": "Asia/Krasnoyarsk",  # Используем поддерживаемый часовой пояс
        "schedule_enabled": True,
        "open_times": {
            "Пн": "09:01",
            "Вт": "09:01",
            "Ср": "09:01",
            "Чт": "09:01",
            "Пт": "09:01",
            "Сб": "09:01",
            "Вс": "09:01"
        },
        "breaks": {
            "Пн": [],
            "Вт": [],
            "Ср": [],
            "Чт": [],
            "Пт": [],
            "Сб": [],
            "Вс": []
        }
    })
    if not cfg.get("schedule_enabled", True):
        logger.info("Расписание отключено, задача не выполняется.")
        return

    # Проверяем время открытия
    open_time = cfg.get("open_times", {}).get(current_day)
    logger.debug(f"Время открытия для {current_day} по расписанию: {open_time}")
    if not open_time:
        logger.info(f"Для {current_day} не задано время открытия, задача не выполняется.")
        return

    # Проверяем, не перерыв ли сейчас
    breaks = cfg.get("breaks", {}).get(current_day, [])
    logger.debug(f"Проверка перерывов для {current_day}. Перерывы: {breaks}")
    for break_time in breaks:
        start, end = break_time.split("-")
        if start <= current_time < end: # Изменено на `< end` для корректной работы
            logger.info(f"Сейчас перерыв ({break_time}). Открытие замка отложено.")
            return

    # Если текущее время совпадает с временем открытия
    logger.debug(f"Сравнение текущего времени ({current_time}) с временем открытия ({open_time})")
    if current_time == open_time:
        logger.info("Время открытия совпало. Начинаю процедуру открытия замка.")
        # Получаем токен
        token = ttlock_api.get_token(logger)
        if not token:
            logger.error("Не удалось получить токен для открытия замка.")
            send_telegram_message(telegram_token, telegram_chat_id, "❗️ <b>Ошибка: не удалось получить токен TTLock</b>", logger)
            return

        # Если LOCK_ID не задан, процедура не может быть выполнена.
        if not LOCK_ID:
            logger.error("LOCK_ID не задан в .env, процедура открытия не может быть выполнена.")
            send_telegram_message(telegram_token, telegram_chat_id, "❗️ <b>Ошибка: LOCK_ID не задан</b>", logger)
            return

        execute_lock_action_with_retries(
            action_func=ttlock_api.unlock_lock,
            token=token,
            lock_id=LOCK_ID,
            action_name="открытия",
            success_msg="открыт",
            failure_msg_part="открытие замка"
        )
    else:
        logger.debug("Время открытия не совпало. Задача завершена.")

def log_heartbeat():
    """Логирует 'сердцебиение' планировщика, чтобы показать, что он работает."""
    logger.debug("Планировщик активен, ожидает задач...")

def main() -> None:
    """
    Главная функция: настраивает и запускает планировщик.
    """
    logger.info("Запуск сервиса auto_unlocker...")
    send_telegram_message(telegram_token, telegram_chat_id, "🚀 <b>Сервис auto_unlocker запущен</b>", logger)

    # Получаем токен для первоначальной проверки
    token = ttlock_api.get_token(logger)
    if not token:
        msg = "Не удалось получить токен при запуске. Проверьте учетные данные TTLock."
        logger.critical(msg)
        send_telegram_message(telegram_token, telegram_chat_id, f"🔥 <b>Критическая ошибка:</b> {msg}", logger)
        send_email_notification("Критическая ошибка TTLock", msg)
        return

    # Определяем lock_id
    lock_id = resolve_lock_id(token)
    if not lock_id:
        msg = "Не удалось определить lock_id. Сервис не может продолжить работу."
        logger.critical(msg)
        send_telegram_message(telegram_token, telegram_chat_id, f"🔥 <b>Критическая ошибка:</b> {msg}", logger)
        send_email_notification("Критическая ошибка TTLock", msg)
        return

    global LOCK_ID
    LOCK_ID = lock_id

    # Загружаем конфигурацию
    cfg = load_config(CONFIG_PATH, logger)
    if not cfg:
        msg = f"Не удалось загрузить конфигурационный файл {CONFIG_PATH}. Используются значения по умолчанию."
        logger.warning(msg)
        send_telegram_message(telegram_token, telegram_chat_id, f"⚠️ <b>Предупреждение:</b> {msg}", logger)
        cfg = {} # Используем пустой конфиг, чтобы дальше код работал со значениями по-умолчанию

    # Проверяем и устанавливаем часовой пояс
    tz_str = cfg.get("timezone", "Asia/Krasnoyarsk")
    try:
        # Установка системного часового пояса для всего процесса
        os.environ['TZ'] = tz_str
        time_module.tzset()
        logger.info(f"Установлен часовой пояс: {tz_str}")
        send_telegram_message(telegram_token, telegram_chat_id, f"⚙️ Часовой пояс: <code>{tz_str}</code>", logger)
    except Exception as e:
        logger.error(f"Ошибка установки часового пояса {tz_str}: {e}")
        send_telegram_message(telegram_token, telegram_chat_id, f"❗️ <b>Ошибка установки часового пояса:</b> {tz_str}", logger)

    # --- Настройка расписания ---
    schedule.clear() # Очищаем старые задачи на случай перезапуска
    logger.info("Настройка расписания...")

    schedule_enabled = cfg.get("schedule_enabled", True)
    if not schedule_enabled:
        logger.warning("Расписание в конфигурации отключено. Задачи не будут запланированы.")
        send_telegram_message(telegram_token, telegram_chat_id, "🚫 <b>Расписание отключено.</b> Задачи автоматического открытия/закрытия неактивны.", logger)
    else:
        open_times = cfg.get("open_times", {})
        breaks = cfg.get("breaks", {})

        for day_name, open_time in open_times.items():
            if open_time:
                # Задача на открытие
                logger.info(f"Планирую открытие на {day_name} в {open_time}")
                day_schedule = getattr(schedule.every(), day_name.lower())
                day_schedule.at(open_time).do(job)

                # Задачи на закрытие и повторное открытие по перерывам
                day_breaks = breaks.get(day_name, [])
                if day_breaks:
                    logger.info(f"Для {day_name} найдены перерывы: {day_breaks}")
                for break_time in day_breaks:
                    start_break, end_break = break_time.split('-')

                    # Закрытие в начале перерыва
                    logger.info(f"Планирую закрытие на {day_name} в {start_break} (начало перерыва)")

                    def make_close(day=day_name):
                        def _close():
                            logger.info(f"Перерыв ({day}). Закрываю замок.")
                            token_close = ttlock_api.get_token(logger)
                            if token_close:
                                execute_lock_action_with_retries(
                                    action_func=ttlock_api.lock_lock,
                                    token=token_close,
                                    lock_id=LOCK_ID,
                                    action_name="закрытия",
                                    success_msg="закрыт на перерыв",
                                    failure_msg_part="закрытие замка на перерыв"
                                )
                        return _close

                    day_schedule_close = getattr(schedule.every(), day_name.lower())
                    day_schedule_close.at(start_break).do(make_close(day=day_name))

                    # Открытие в конце перерыва
                    logger.info(f"Планирую открытие на {day_name} в {end_break} (конец перерыва)")
                    def make_reopen(day=day_name):
                        def _open():
                            logger.info(f"Перерыв ({day}) окончен. Открываю замок.")
                            token_open = ttlock_api.get_token(logger)
                            if token_open:
                                execute_lock_action_with_retries(
                                    action_func=ttlock_api.unlock_lock,
                                    token=token_open,
                                    lock_id=LOCK_ID,
                                    action_name="открытия",
                                    success_msg="открыт после перерыва",
                                    failure_msg_part="открытие замка после перерыва"
                                )
                        return _open

                    day_schedule_open = getattr(schedule.every(), day_name.lower())
                    day_schedule_open.at(end_break).do(make_reopen(day=day_name))

    # Логирование "сердцебиения" каждые 10 минут
    schedule.every(10).minutes.do(log_heartbeat)

    logger.info("Планировщик запущен и ожидает задач.")
    send_telegram_message(telegram_token, telegram_chat_id, "✅ <b>Планировщик успешно настроен и запущен.</b>", logger)

    # Основной цикл
    while True:
        schedule.run_pending()
        time_module.sleep(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Критическая ошибка в main: {e}")
        log_exception(logger)
        send_email_notification("Критическая ошибка в auto_unlocker", f"Произошла критическая ошибка: {e}\n\n{traceback.format_exc()}")
        raise

