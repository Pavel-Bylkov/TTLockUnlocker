"""
Telegram-бот для управления рассылкой уведомлений TTLock и смены chat_id через Docker.
Используется совместно с auto_unlocker.py. Все параметры берутся из .env.

Для отладки можно установить переменную окружения DEBUG=1 (или true/True) — тогда будет подробный вывод в консоль.
"""
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ConversationHandler, CallbackQueryHandler
import os
import docker
from dotenv import load_dotenv
import json
import ttlock_api
from logging.handlers import TimedRotatingFileHandler
import sys
import pytz
import traceback
from telegram_utils import send_telegram_message, is_authorized, log_exception, send_email_notification, log_message, load_config, save_config
import re
from typing import Any

# Определяем путь к .env: сначала из ENV_PATH, иначе env/.env
ENV_PATH = os.getenv('ENV_PATH') or 'env/.env'
# Загрузка переменных окружения
load_dotenv(ENV_PATH)

# Уровень отладки
DEBUG = os.getenv('DEBUG', '0').lower() in ('1', 'true', 'yes')

if DEBUG:
    print(f"[DEBUG] Используется путь к .env: {ENV_PATH}")

# Настройка логирования
os.makedirs('logs', exist_ok=True)
logger = logging.getLogger("telegram_bot")
logger.setLevel(logging.DEBUG)


handler = TimedRotatingFileHandler('logs/telegram_bot.log', when="midnight", backupCount=14, encoding="utf-8")
formatter = ttlock_api.TZFormatter('%(asctime)s %(levelname)s: %(message)s', '%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)
logger.handlers.clear()
logger.addHandler(handler)
# Дублируем логи в stdout для Docker
console = logging.StreamHandler(sys.stdout)
console.setFormatter(formatter)
logger.addHandler(console)

CODEWORD = os.getenv('TELEGRAM_CODEWORD', 'secretword')
AUTO_UNLOCKER_CONTAINER = os.getenv('AUTO_UNLOCKER_CONTAINER', 'auto_unlocker_1')
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
AUTHORIZED_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', 300613294)

# Состояния для ConversationHandler
ASK_CODEWORD = 0
CONFIRM_CHANGE = 1
SETTIME_DAY = 2
SETTIME_VALUE = 3
SETBREAK_DAY = 4
SETBREAK_ACTION = 5
SETBREAK_ADD = 6
SETBREAK_DEL = 7
SETTIMEZONE_VALUE = 8
SETEMAIL_VALUE = 9

CONFIG_PATH = os.getenv("CONFIG_PATH", "config.json")

# TTLock API команды для мгновенного открытия/закрытия
TTLOCK_CLIENT_ID = os.getenv("TTLOCK_CLIENT_ID")
TTLOCK_CLIENT_SECRET = os.getenv("TTLOCK_CLIENT_SECRET")
TTLOCK_USERNAME = os.getenv("TTLOCK_USERNAME")
TTLOCK_PASSWORD = os.getenv("TTLOCK_PASSWORD")
TTLOCK_LOCK_ID = os.getenv("TTLOCK_LOCK_ID")

DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

REQUIRED_ENV_VARS = [
    'TELEGRAM_BOT_TOKEN',
    'AUTO_UNLOCKER_CONTAINER',
    'TTLOCK_CLIENT_ID',
    'TTLOCK_CLIENT_SECRET',
    'TTLOCK_USERNAME',
    'TTLOCK_PASSWORD',
]
missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_vars:
    print(f"[ERROR] Не заданы обязательные переменные окружения: {', '.join(missing_vars)}. Проверьте .env файл!")
    exit(1)

# Глобальный set для блокировки chat_id, которые 5 раз ввели неверный код
BLOCKED_CHAT_IDS_FILE = 'blocked_chat_ids.json'

# Глобальный set для блокировки chat_id, которые 5 раз ввели неверный код
try:
    with open(BLOCKED_CHAT_IDS_FILE, 'r', encoding='utf-8') as f:
        BLOCKED_CHAT_IDS = set(json.load(f))
        print(f"[INFO] Загружено {len(BLOCKED_CHAT_IDS)} заблокированных chat_id из {BLOCKED_CHAT_IDS_FILE}")
except Exception:
    BLOCKED_CHAT_IDS = set()
    print(f"[INFO] Файл {BLOCKED_CHAT_IDS_FILE} не найден или пуст, блокировка не загружена.")

def save_blocked_chat_ids(blocked_set):
    try:
        with open(BLOCKED_CHAT_IDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(blocked_set), f, ensure_ascii=False, indent=2)
        log_message(logger, "INFO", f"Список заблокированных chat_id сохранён в {BLOCKED_CHAT_IDS_FILE}")
    except Exception as e:
        log_message(logger, "ERROR", f"Ошибка сохранения {BLOCKED_CHAT_IDS_FILE}: {e}")

def send_message(update, text: str, parse_mode: str = "HTML", **kwargs: Any) -> None:
    """
    Отправляет сообщение в Telegram с обработкой ошибок.
    
    Args:
        update: Объект Update
        text: Текст сообщения
        parse_mode: Режим форматирования (HTML или Markdown)
        **kwargs: Дополнительные параметры
    """
    try:
        # Заменяем <br> на \n
        text = text.replace("<br>", "\n")
        log_message(logger, "DEBUG", f"Отправка сообщения пользователю {update.effective_chat.id}")
        update.message.reply_text(text, parse_mode=parse_mode, **kwargs)
    except Exception as e:
        log_message(logger, "ERROR", f"Ошибка отправки сообщения: {e}")
        log_message(logger, "ERROR", traceback.format_exc())
        # Пробуем отправить без форматирования
        try:
            update.message.reply_text(text, parse_mode=None, **kwargs)
        except Exception as e:
            log_message(logger, "ERROR", f"Ошибка отправки сообщения без форматирования: {e}")

def format_logs(log_path: str = "logs/auto_unlocker.log") -> str:
    """
    Формирует текст сообщения с логами.
    """
    try:
        if not os.path.exists(log_path):
            return "Лог-файл не найден."
            
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-10:]  # Берем последние 10 строк
        
        # Фильтруем пустые строки и удаляем лишние пробелы
        non_empty_lines = [line.strip() for line in lines if line.strip()]
        
        # Заменяем дни недели
        days_map = {
            "monday": "Понедельник",
            "tuesday": "Вторник",
            "wednesday": "Среда",
            "thursday": "Четверг",
            "friday": "Пятница",
            "saturday": "Суббота",
            "sunday": "Воскресенье"
        }
        
        # Применяем замену дней недели к каждой строке
        processed_lines = []
        for line in non_empty_lines:
            for en, ru in days_map.items():
                line = line.replace(en, ru)
            processed_lines.append(line)
        
        return f"<b>Последние логи сервиса:</b>\n<code>{chr(10).join(processed_lines)}</code>"
    except Exception as e:
        log_message(logger, "ERROR", f"Ошибка чтения логов: {e}")
        return f"Ошибка чтения логов: {e}"

def logs(update, context):
    """
    Показывает последние записи из логов сервиса автооткрытия.
    """
    log_message(logger, "INFO", f"Получена команда /logs от chat_id={update.effective_chat.id}")
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        send_message(update, "Нет доступа.")
        return
    
    try:
        message = format_logs()
        send_message(update, message)
    except Exception as e:
        log_message(logger, "ERROR", f"Ошибка при получении логов: {e}")
        send_message(update, f"Ошибка при получении логов: {e}")

def setemail(update, context) -> int:
    """
    Начинает процесс установки email для уведомлений.
    """
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        return ConversationHandler.END
        
    send_message(update,
        "Введите email для получения уведомлений о критических ошибках:"
    )
    return SETEMAIL_VALUE

def setemail_value(update, context) -> int:
    """
    Сохраняет email в .env файл.
    """
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        return ConversationHandler.END
        
    email = update.message.text.strip()
    
    # Простая проверка формата email
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        send_message(update, "Некорректный формат email. Попробуйте еще раз.")
        return SETEMAIL_VALUE
        
    log_message(logger, "DEBUG", f"Начинаю запись EMAIL_TO={email} в {ENV_PATH}")
    try:
        with open(ENV_PATH, 'r') as f:
            lines = f.readlines()
    except Exception as e:
        send_message(update, f"Не удалось прочитать .env: {e}")
        return ConversationHandler.END

    send_message(update, "⚙️ Сохраняю новые настройки...")
    with open(ENV_PATH, 'w') as f:
        found = False
        for line in lines:
            if line.startswith('EMAIL_TO='):
                f.write(f'EMAIL_TO={email}\n')
                found = True
            else:
                f.write(line)
        if not found:
            f.write(f'EMAIL_TO={email}\n')

    restart_auto_unlocker_and_notify(
        update,
        logger,
        f"Email для уведомлений установлен: {email}",
        "Ошибка при перезапуске сервиса"
    )
    return ConversationHandler.END

def do_test_email(update, context):
    """
    Отправляет тестовое email-сообщение.
    """
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        send_message(update, "⛔️ Нет доступа.")
        return

    send_message(update, "Отправляю тестовое email-сообщение...")
    
    success = send_email_notification(
        subject="Тестовое уведомление от TTLock Bot",
        body="Это тестовое сообщение для проверки настроек отправки email."
    )
    
    if success:
        send_message(update, "✅ Сообщение успешно отправлено!")
    else:
        send_message(update, "❌ Не удалось отправить сообщение. Проверьте настройки SMTP в .env и логи.")

def start(update, context):
    """
    Обрабатывает команду /start. Приветствие и краткая инструкция.
    """
    log_message(logger, "INFO", f"Получена команда /start от chat_id={update.effective_chat.id}")
    menu(update, context)

def setchat(update, context):
    """
    Запрашивает у пользователя кодовое слово для смены chat_id.
    """
    log_message(logger, "DEBUG", f"Вход в setchat, chat_id={update.effective_chat.id}, text='{getattr(update.message, 'text', '')}'")
    log_message(logger, "INFO", f"Получена команда /setchat от chat_id={update.effective_chat.id}")
    blocked = context.bot_data.get('blocked_chat_ids', set())
    blocked.update(BLOCKED_CHAT_IDS)
    if update.effective_chat.id in blocked:
        send_message(update, "⛔️ Вы исчерпали лимит попыток смены получателя. Попробуйте позже или обратитесь к администратору.")
        return ConversationHandler.END
    send_message(update, "Введите кодовое слово:", reply_markup=ReplyKeyboardRemove())
    return ASK_CODEWORD

def check_codeword(update, context):
    """
    Проверяет введённое кодовое слово. Если верно — предлагает подтвердить смену chat_id.
    """
    log_message(logger, "DEBUG", f"check_codeword вызван с update: {update}")
    log_message(logger, "DEBUG", f"Вход в check_codeword, chat_id={update.effective_chat.id}, text='{getattr(update.message, 'text', '')}'")
    chat_id = update.effective_chat.id
    bot_data = context.bot_data
    blocked = bot_data.setdefault('blocked_chat_ids', set())
    blocked.update(BLOCKED_CHAT_IDS)
    attempts = bot_data.setdefault('codeword_attempts', {})
    log_message(logger, "DEBUG", f"[check_codeword] Вход. chat_id={chat_id}, text='{update.message.text.strip()}'")
    if chat_id in blocked:
        send_message(update, "⛔️ Вы исчерпали лимит попыток смены получателя. Попробуйте позже или обратитесь к администратору.")
        return ConversationHandler.END
    if update.message.text.strip() == CODEWORD:
        log_message(logger, "DEBUG", f"Кодовое слово верно. chat_id={update.message.chat_id}")
        send_message(update, "Кодовое слово верно! Подтвердите смену получателя (да/нет):", reply_markup=ReplyKeyboardRemove())
        context.user_data['new_chat_id'] = update.message.chat_id
        attempts.pop(chat_id, None)
        return CONFIRM_CHANGE
    else:
        attempts[chat_id] = attempts.get(chat_id, 0) + 1
        log_message(logger, "DEBUG", f"Неверное кодовое слово. Попытка {attempts[chat_id]} из 5 для chat_id={chat_id}")
        if attempts[chat_id] >= 5:
            blocked.add(chat_id)
            BLOCKED_CHAT_IDS.add(chat_id)
            save_blocked_chat_ids(BLOCKED_CHAT_IDS)
            log_message(logger, "INFO", f"chat_id={chat_id} заблокирован за 5 неверных попыток кодового слова (сохранено)")
            send_message(update, "⛔️ Вы исчерпали лимит попыток смены получателя. Попробуйте позже или обратитесь к администратору.")
            return ConversationHandler.END
        send_message(update, f"Неверное кодовое слово. Осталось попыток: {5 - attempts[chat_id]}", reply_markup=ReplyKeyboardRemove())
        return ASK_CODEWORD

def confirm_change(update, context):
    """
    Подтверждает смену chat_id, обновляет .env и перезапускает auto_unlocker (если возможно).
    """
    log_message(logger, "DEBUG", f"Вход в confirm_change, chat_id={update.effective_chat.id}, text='{getattr(update.message, 'text', '')}'")
    log_message(logger, "DEBUG", f"confirm_change: ответ пользователя '{update.message.text}'")
    if update.message.text.lower() == 'да':
        send_message(update, "✅ Кодовое слово верно. Начинаю смену получателя...", reply_markup=ReplyKeyboardRemove())
        new_chat_id = str(context.user_data['new_chat_id'])
        log_message(logger, "INFO", f"ПРОЦЕДУРА СМЕНЫ CHAT_ID: новый chat_id={new_chat_id}, ENV_PATH={ENV_PATH}")
        try:
            with open(ENV_PATH, 'r') as f:
                lines = f.readlines()
            log_message(logger, "DEBUG", f"Прочитано {len(lines)} строк из .env")
        except Exception as e:
            msg = f"Не удалось прочитать .env: {e}"
            log_message(logger, "ERROR", msg)
            send_message(update, msg)
            return ConversationHandler.END
        try:
            with open(ENV_PATH, 'w') as f:
                found = False
                for line in lines:
                    if line.startswith('TELEGRAM_CHAT_ID='):
                        f.write(f'TELEGRAM_CHAT_ID={new_chat_id}\n')
                        found = True
                        log_message(logger, "DEBUG", f"Заменяю строку: TELEGRAM_CHAT_ID={new_chat_id}")
                    else:
                        f.write(line)
                if not found:
                    f.write(f'TELEGRAM_CHAT_ID={new_chat_id}\n')
                    log_message(logger, "DEBUG", f"Добавляю строку: TELEGRAM_CHAT_ID={new_chat_id}")
            log_message(logger, "DEBUG", "Запись в .env завершена")
            log_message(logger, "INFO", f"Chat ID изменён на {new_chat_id} в .env")
            # Обновляем глобальную переменную AUTHORIZED_CHAT_ID
            global AUTHORIZED_CHAT_ID
            AUTHORIZED_CHAT_ID = new_chat_id
            log_message(logger, "INFO", f"AUTHORIZED_CHAT_ID обновлён в памяти: {AUTHORIZED_CHAT_ID}")
        except Exception as e:
            msg = f"Не удалось записать .env: {e}"
            log_message(logger, "ERROR", msg)
            send_message(update, msg)
            return ConversationHandler.END
        # Пробуем перезапустить контейнер, если он есть
        send_message(update, "⚙️ Файл `.env` обновлён. Перезапускаю сервис...", reply_markup=ReplyKeyboardRemove())
        restart_auto_unlocker_and_notify(update, logger, "Получатель уведомлений изменён, скрипт перезапущен.", "Ошибка перезапуска контейнера")
        # После завершения возвращаем меню
        menu(update, context)
        return ConversationHandler.END
    else:
        send_message(update, "Операция отменена.")
        menu(update, context)
        return ConversationHandler.END

def restart_auto_unlocker_and_notify(update, logger, message_success, message_error):
    """
    Перезапускает сервис автооткрытия и отправляет уведомление.
    """
    log_message(logger, "DEBUG", "Пробую перезапустить сервис автооткрытия...")
    try:
        client = docker.from_env()
        container = client.containers.get(AUTO_UNLOCKER_CONTAINER)
        container.restart()
        send_message(update, message_success)
        log_message(logger, "INFO", "Сервис автооткрытия перезапущен после изменения конфигурации.")
    except Exception as e:
        send_message(update, f"{message_error}: {e}")
        log_exception(logger)

def status(update, context):
    """
    Показывает текущий статус расписания и сервиса.
    """
    log_message(logger, "INFO", f"Получена команда /status от chat_id={update.effective_chat.id}")
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        send_message(update, "Нет доступа.")
        return
    cfg = load_config(CONFIG_PATH, logger, default={
        "timezone": "Asia/Novosibirsk",
        "schedule_enabled": True,
        "open_times": {},
        "breaks": {}
    })
    tz = cfg.get("timezone", "?")
    enabled = cfg.get("schedule_enabled", True)
    open_times = cfg.get("open_times", {})
    breaks = cfg.get("breaks", {})
    
    # Проверка статуса auto_unlocker
    try:
        client = docker.from_env()
        container = client.containers.get(AUTO_UNLOCKER_CONTAINER)
        status_map = {
            "running": "работает",
            "exited": "остановлен",
            "created": "создан",
            "paused": "приостановлен",
            "restarting": "перезапускается"
        }
        rus_status = status_map.get(container.status, container.status)
        status_str = f"<b>Сервис автооткрытия:</b> <code>{rus_status}</code>"
    except Exception as e:
        log_message(logger, "ERROR", f"Ошибка получения статуса контейнера: {e}")
        status_str = ""
    
    msg = f"<b>Статус расписания</b>\n"
    msg += f"Часовой пояс: <code>{tz}</code>\n"
    msg += f"Расписание включено: <b>{'да' if enabled else 'нет'}</b>\n"
    if status_str:
        msg += status_str + "\n"
    msg += "<b>Время открытия:</b>\n"
    for day, t in open_times.items():
        msg += f"{day}: {t if t else 'выключено'}\n"
    
    # Только дни с перерывами
    breaks_with_values = {day: br for day, br in breaks.items() if br}
    if breaks_with_values:
        msg += "<b>Перерывы:</b>\n"
        for day, br in breaks_with_values.items():
            msg += f"{day}: {', '.join(br)}\n"
    
    send_message(update, msg)

def enable_schedule(update, context):
    """
    Включает расписание.
    """
    log_message(logger, "INFO", f"Получена команда /enable_schedule от chat_id={update.effective_chat.id}")
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        send_message(update, "Нет доступа.")
        return
    send_message(update, "⚙️ Сохраняю настройки. Перезапускаю сервис...")
    cfg = load_config(CONFIG_PATH, logger)
    cfg["schedule_enabled"] = True
    save_config(cfg, CONFIG_PATH, logger)
    # Перезапуск auto_unlocker
    restart_auto_unlocker_and_notify(update, logger, "Расписание <b>включено</b>.\nAuto_unlocker перезапущен, изменения применены.", "Расписание <b>включено</b>, но не удалось перезапустить auto_unlocker")

def disable_schedule(update, context):
    """
    Отключает расписание.
    """
    log_message(logger, "INFO", f"Получена команда /disable_schedule от chat_id={update.effective_chat.id}")
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        send_message(update, "Нет доступа.")
        return
    send_message(update, "⚙️ Сохраняю настройки. Перезапускаю сервис...")
    cfg = load_config(CONFIG_PATH, logger)
    cfg["schedule_enabled"] = False
    save_config(cfg, CONFIG_PATH, logger)
    # Перезапуск auto_unlocker
    restart_auto_unlocker_and_notify(update, logger, "Расписание <b>отключено</b>.\nAuto_unlocker перезапущен, изменения применены.", "Расписание <b>отключено</b>, но не удалось перезапустить auto_unlocker")

def open_lock(update, context):
    """
    Открывает замок.
    """
    log_message(logger, "INFO", f"Получена команда /open от chat_id={update.effective_chat.id}")
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        send_message(update, "Нет доступа.")
        return
    send_message(update, "🔑 Отправляю команду на открытие замка...")
    try:
        token = ttlock_api.get_token(logger)
        if not token:
            msg = "Ошибка при открытии замка: Не удалось получить токен."
            log_message(logger, "ERROR", msg)
            send_message(update, msg)
            return

        log_message(logger, "DEBUG", f"Получен токен: {token}")
        resp = ttlock_api.unlock_lock(token, TTLOCK_LOCK_ID, logger)
        log_message(logger, "DEBUG", f"Ответ от API: {resp}")
        if resp['errcode'] == 0:
            send_message(update, f"Замок <b>открыт</b>.\nПопытка: {resp['attempt']}")
        else:
            msg = f"Ошибка открытия замка: {resp.get('errmsg', 'Неизвестная ошибка')}"
            log_message(logger, "ERROR", msg)
            send_message(update, msg)
    except Exception as e:
        msg = f"Ошибка при открытии замка: {e}"
        log_message(logger, "ERROR", msg)
        send_message(update, msg)

def close_lock(update, context):
    """
    Закрывает замок.
    """
    log_message(logger, "INFO", f"Получена команда /close от chat_id={update.effective_chat.id}")
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        send_message(update, "Нет доступа.")
        return
    send_message(update, "🔒 Отправляю команду на закрытие замка...")
    try:
        token = ttlock_api.get_token(logger)
        if not token:
            msg = "Ошибка при закрытии замка: Не удалось получить токен."
            log_message(logger, "ERROR", msg)
            send_message(update, msg)
            return

        log_message(logger, "DEBUG", f"Получен токен: {token}")
        resp = ttlock_api.lock_lock(token, TTLOCK_LOCK_ID, logger)
        log_message(logger, "DEBUG", f"Ответ от API: {resp}")
        if resp['errcode'] == 0:
            send_message(update, f"Замок <b>закрыт</b>.\nПопытка: {resp['attempt']}")
        else:
            msg = f"Ошибка закрытия замка: {resp.get('errmsg', 'Неизвестная ошибка')}"
            log_message(logger, "ERROR", msg)
            send_message(update, msg)
    except Exception as e:
        msg = f"Ошибка при закрытии замка: {e}"
        log_message(logger, "ERROR", msg)
        send_message(update, msg)

def settimezone(update, context):
    """
    Начинает процесс настройки часового пояса.
    """
    log_message(logger, "INFO", f"Получена команда /settimezone от chat_id={update.effective_chat.id}")
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        send_message(update, "Нет доступа.")
        return ConversationHandler.END
    send_message(update, "Введите часовой пояс (например, Europe/Moscow):")
    return SETTIMEZONE_VALUE

def settimezone_apply(update, context):
    """
    Применяет новый часовой пояс.
    """
    if DEBUG:
        log_message(logger, "DEBUG", f"Пользователь вводит TZ: {update.message.text.strip()}")
    tz = update.message.text.strip()
    try:
        # Проверяем валидность часового пояса
        pytz.timezone(tz)
        cfg = load_config(CONFIG_PATH, logger)
        cfg["timezone"] = tz
        save_config(cfg, CONFIG_PATH, logger)
        # Перезапуск auto_unlocker
        restart_auto_unlocker_and_notify(update, logger, f"Часовой пояс изменён на {tz}. \nAuto_unlocker перезапущен, изменения применены.", "Часовой пояс изменён, но не удалось перезапустить auto_unlocker")
        return ConversationHandler.END
    except pytz.exceptions.UnknownTimeZoneError:
        send_message(update, "Некорректный часовой пояс. Попробуйте ещё раз.")
        return SETTIMEZONE_VALUE
    except Exception as e:
        log_message(logger, "ERROR", f"Ошибка при смене часового пояса: {e}")
        send_message(update, f"Ошибка при смене часового пояса: {e}")
        return ConversationHandler.END

def settime(update, context) -> int:
    """
    Начало процесса настройки времени открытия.
    """
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        send_message(update, "⛔️ У вас нет доступа к этой команде.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("Понедельник", callback_data="Пн")],
        [InlineKeyboardButton("Вторник", callback_data="Вт")],
        [InlineKeyboardButton("Среда", callback_data="Ср")],
        [InlineKeyboardButton("Четверг", callback_data="Чт")],
        [InlineKeyboardButton("Пятница", callback_data="Пт")],
        [InlineKeyboardButton("Суббота", callback_data="Сб")],
        [InlineKeyboardButton("Воскресенье", callback_data="Вс")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    send_message(update,
        "Выберите день недели для настройки времени открытия:",
        reply_markup=reply_markup
    )
    return SETTIME_DAY

def handle_settime_callback(update, context) -> int:
    query = update.callback_query
    query.answer()
    # Сохраняем выбранный день
    context.user_data["day"] = query.data
    # Удаляем inline-клавиатуру
    query.edit_message_text(
        text=f"Выбран день: {query.data}\nВведите время открытия в формате ЧЧ:ММ (например, 09:00):"
    )
    log_message(logger, "DEBUG", f"Переход в состояние SETTIME_VALUE для chat_id={update.effective_chat.id}")
    return SETTIME_VALUE

def settime_value(update, context):
    """
    Обрабатывает выбор времени открытия.
    """
    if DEBUG:
        log_message(logger, "DEBUG", f"Пользователь вводит время: {update.message.text.strip()}")
    time_str = update.message.text.strip()
    
    # Проверяем формат времени
    if not re.match(r'^\d{1,2}:[0-5][0-9]$', time_str):
        send_message(update, "Некорректный формат времени. Используйте ЧЧ:ММ (например, 09:00).")
        return SETTIME_VALUE
        
    try:
        # Проверяем валидность времени
        hour, minute = map(int, time_str.split(':'))
        if hour > 23 or minute > 59:
            send_message(update, "Некорректное время. Часы должны быть от 0 до 23, минуты от 0 до 59.")
            return SETTIME_VALUE
            
        # Форматируем время в формат HH:MM
        time_str = f"{hour:02d}:{minute:02d}"
            
        cfg = load_config(CONFIG_PATH, logger)
        if "open_times" not in cfg:
            cfg["open_times"] = {}
            
        # Сохраняем день перед очисткой состояния
        day = context.user_data["day"]
        cfg["open_times"][day] = time_str
        save_config(cfg, CONFIG_PATH, logger)
        
        # Очищаем состояние
        context.user_data.pop("state", None)
        context.user_data.pop("day", None)
        
        # Перезапуск auto_unlocker
        restart_auto_unlocker_and_notify(
            update, 
            logger, 
            f"Время открытия для {day} установлено на {time_str}. \nAuto_unlocker перезапущен, изменения применены.",
            "Время открытия изменено, но не удалось перезапустить auto_unlocker"
        )
        return ConversationHandler.END
    except Exception as e:
        log_message(logger, "ERROR", f"Ошибка при установке времени: {e}")
        send_message(update, f"Ошибка при установке времени: {e}")
        return SETTIME_VALUE

def setbreak(update, context):
    """
    Начинает процесс установки перерывов.
    """
    log_message(logger, "INFO", f"Получена команда /setbreak от chat_id={update.effective_chat.id}")
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        send_message(update, "Нет доступа.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(day, callback_data=f"setbreak_{day}")] for day in DAYS]
    reply_markup = InlineKeyboardMarkup(keyboard)
    send_message(update, "Выберите день недели:", reply_markup=reply_markup)
    return SETBREAK_DAY

def handle_setbreak_callback(update, context) -> int:
    query = update.callback_query
    query.answer()
    # Сохраняем выбранный день
    context.user_data["day"] = query.data.replace("setbreak_", "")
    # Удаляем inline-клавиатуру
    query.edit_message_text(
        text=f"Выбран день: {context.user_data['day']}\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Добавить", callback_data="add_break")],
            [InlineKeyboardButton("Удалить", callback_data="remove_break")]
        ])
    )
    log_message(logger, "DEBUG", f"Переход в состояние SETBREAK_ACTION для chat_id={update.effective_chat.id}")
    return SETBREAK_ACTION

def handle_setbreak_action(update, context) -> int:
    query = update.callback_query
    query.answer()
    if query.data == "add_break":
        query.edit_message_text(
            text="Введите время перерыва в формате ЧЧ:ММ-ЧЧ:ММ (например, 12:00-13:00):"
        )
        log_message(logger, "DEBUG", f"Переход в состояние SETBREAK_ADD для chat_id={update.effective_chat.id}")
        return SETBREAK_ADD
    elif query.data == "remove_break":
        cfg = load_config(CONFIG_PATH, logger)
        breaks = cfg.get("breaks", {}).get(context.user_data["day"], [])
        if not breaks:
            query.edit_message_text(text="Нет перерывов для удаления.")
            return ConversationHandler.END
        query.edit_message_text(
            text="Введите время перерыва для удаления в формате ЧЧ:ММ-ЧЧ:ММ:"
        )
        log_message(logger, "DEBUG", f"Переход в состояние SETBREAK_DEL для chat_id={update.effective_chat.id}")
        return SETBREAK_DEL
    return ConversationHandler.END

def restart_auto_unlocker_cmd(update, context):
    """
    Перезапускает сервис автооткрытия по команде.
    """
    log_message(logger, "INFO", f"Получена команда /restart_auto_unlocker от chat_id={update.effective_chat.id}")
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        send_message(update, "Нет доступа.")
        return
    send_message(update, "🔄 Отправляю команду на перезапуск сервиса...")
    restart_auto_unlocker_and_notify(update, logger, "Сервис автооткрытия перезапущен по команде.", "Не удалось перезапустить сервис автооткрытия")

def menu(update, context):
    """
    Выводит список всех доступных команд в виде кнопок-команд.
    """
    log_message(logger, "INFO", f"Получена команда /menu от chat_id={update.effective_chat.id}")
    reply_markup = ReplyKeyboardMarkup(
        MENU_COMMANDS,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие"
    )
    send_message(update,
        "Выберите действие:",
        reply_markup=reply_markup
    )

MENU_COMMANDS = [
    ["/status", "/logs"],
    ["/open", "/close"],
    ["/settime", "/setbreak"],
    ["/setchat", "/setemail"],
    ["/restart_auto_unlocker", "/test_email"],
    ["/menu"]
]

def setbreak_add(update, context):
    """
    Добавляет перерыв.
    """
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        send_message(update, "Нет доступа.")
        return ConversationHandler.END
    break_str = update.message.text.strip()
    # Проверка формата
    if not re.match(r'^\d{1,2}:[0-5][0-9]-\d{1,2}:[0-5][0-9]$', break_str):
        send_message(update, "Некорректный формат перерыва. Используйте ЧЧ:ММ-ЧЧ:ММ (например, 12:00-13:00).")
        return SETBREAK_ADD
    try:
        start_time, end_time = break_str.split('-')
        # Проверка валидности времени
        start_hour, start_minute = map(int, start_time.split(':'))
        end_hour, end_minute = map(int, end_time.split(':'))
        if start_hour > 23 or start_minute > 59 or end_hour > 23 or end_minute > 59:
            send_message(update, "Некорректное время. Часы должны быть от 0 до 23, минуты от 0 до 59.")
            return SETBREAK_ADD
        if (end_hour < start_hour) or (end_hour == start_hour and end_minute <= start_minute):
            send_message(update, "Время окончания перерыва должно быть позже времени начала.")
            return SETBREAK_ADD
        cfg = load_config(CONFIG_PATH, logger)
        day = context.user_data["day"]
        if "breaks" not in cfg:
            cfg["breaks"] = {}
        if day not in cfg["breaks"]:
            cfg["breaks"][day] = []
        cfg["breaks"][day].append(break_str)
        save_config(cfg, CONFIG_PATH, logger)
        send_message(update, f"Перерыв {break_str} для {day} добавлен.")
        restart_auto_unlocker_and_notify(
            update, logger,
            f"Добавлен перерыв {break_str} для {day}.<br>Auto_unlocker перезапущен, изменения применены.",
            "Перерыв добавлен, но не удалось перезапустить auto_unlocker"
        )
        return ConversationHandler.END
    except Exception as e:
        log_message(logger, "ERROR", f"Ошибка при добавлении перерыва: {e}")
        send_message(update, f"Ошибка при добавлении перерыва: {e}")
        return SETBREAK_ADD

def setbreak_remove(update, context):
    """
    Удаляет перерыв.
    """
    if not is_authorized(update, AUTHORIZED_CHAT_ID):
        send_message(update, "Нет доступа.")
        return ConversationHandler.END
    break_str = update.message.text.strip()
    if not re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]-([01]?[0-9]|2[0-3]):[0-5][0-9]$', break_str):
        send_message(update, "Некорректный формат перерыва. Используйте ЧЧ:ММ-ЧЧ:ММ (например, 12:00-13:00).")
        return SETBREAK_DEL
    try:
        cfg = load_config(CONFIG_PATH, logger)
        day = context.user_data["day"]
        if day in cfg.get("breaks", {}) and break_str in cfg["breaks"][day]:
            cfg["breaks"][day].remove(break_str)
            save_config(cfg, CONFIG_PATH, logger)
            send_message(update, f"Перерыв {break_str} для {day} удалён.")
            restart_auto_unlocker_and_notify(
                update, logger,
                f"Удалён перерыв {break_str} для {day}.<br>Auto_unlocker перезапущен, изменения применены.",
                "Перерыв удалён, но не удалось перезапустить auto_unlocker"
            )
        else:
            send_message(update, "Такой перерыв не найден.")
        return ConversationHandler.END
    except Exception as e:
        log_message(logger, "ERROR", f"Ошибка при удалении перерыва: {e}")
        send_message(update, f"Ошибка при удалении перерыва: {e}")
        return SETBREAK_DEL

def main():
    """
    Точка входа: запускает Telegram-бота и обработчики команд.
    """
    try:
        log_message(logger, "DEBUG", "Запуск Telegram-бота...")
        if not BOT_TOKEN:
            log_message(logger, "ERROR", "TELEGRAM_BOT_TOKEN не задан в .env!")
            return
        updater = Updater(BOT_TOKEN, use_context=True)
        dp = updater.dispatcher
        handlers = [
            CommandHandler('start', start),
            CommandHandler('menu', menu),
            CommandHandler('logs', logs),
            CommandHandler('status', status),
            CommandHandler('enable_schedule', enable_schedule),
            CommandHandler('disable_schedule', disable_schedule),
            CommandHandler('open', open_lock),
            CommandHandler('close', close_lock),
            CommandHandler('restart_auto_unlocker', restart_auto_unlocker_cmd),
            CommandHandler('test_email', do_test_email),
            ConversationHandler(
                entry_points=[CommandHandler('setchat', setchat)],
                states={
                    ASK_CODEWORD: [MessageHandler(Filters.text, check_codeword)],
                    CONFIRM_CHANGE: [MessageHandler(Filters.text, confirm_change)],
                },
                fallbacks=[],
                per_chat=True
            ),
            ConversationHandler(
                entry_points=[CommandHandler('settimezone', settimezone)],
                states={
                    SETTIMEZONE_VALUE: [MessageHandler(Filters.text, settimezone_apply)],
                },
                fallbacks=[],
                per_chat=True
            ),
            ConversationHandler(
                entry_points=[CommandHandler('settime', settime)],
                states={
                    SETTIME_DAY: [CallbackQueryHandler(handle_settime_callback, pattern="^(Пн|Вт|Ср|Чт|Пт|Сб|Вс)$")],
                    SETTIME_VALUE: [MessageHandler(Filters.text, settime_value)],
                },
                fallbacks=[],
                per_chat=True
            ),
            ConversationHandler(
                entry_points=[CommandHandler('setbreak', setbreak)],
                states={
                    SETBREAK_DAY: [CallbackQueryHandler(handle_setbreak_callback, pattern="^setbreak_")],
                    SETBREAK_ACTION: [CallbackQueryHandler(handle_setbreak_action, pattern="^(add_break|remove_break)$")],
                    SETBREAK_ADD: [MessageHandler(Filters.text, setbreak_add)],
                    SETBREAK_DEL: [MessageHandler(Filters.text, setbreak_remove)],
                },
                fallbacks=[],
                per_chat=True
            ),
            ConversationHandler(
                entry_points=[CommandHandler('setemail', setemail)],
                states={
                    SETEMAIL_VALUE: [MessageHandler(Filters.text, setemail_value)],
                },
                fallbacks=[],
                per_chat=True
            ),
        ]
        for handler in handlers:
            dp.add_handler(handler)
        log_message(logger, "INFO", "Telegram-бот успешно запущен и готов к работе.")
        updater.start_polling()
        updater.idle()
    except Exception as e:
        log_message(logger, "ERROR", f"Критическая ошибка при запуске бота: {e}")
        log_exception(logger)
        raise

if __name__ == '__main__':
    main() 