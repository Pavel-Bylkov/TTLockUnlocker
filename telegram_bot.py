"""
Telegram-бот для управления рассылкой уведомлений TTLock и смены chat_id через Docker.
Используется совместно с auto_unlocker.py. Все параметры берутся из .env.

Для отладки можно установить переменную окружения DEBUG=1 (или true/True) — тогда будет подробный вывод в консоль.
"""
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQueryHandler
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import os
import docker
from dotenv import load_dotenv
import json
import requests
import time
import ttlock_api
from logging.handlers import TimedRotatingFileHandler
import sys
from datetime import datetime
import pytz
import traceback
from telegram_utils import send_telegram_message, is_authorized, log_exception
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
logger.setLevel(logging.INFO)


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
SETMAXRETRYTIME_VALUE = 9

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

def log_message(category: str, message: str):
    """
    Унифицированная функция для логирования сообщений.

    Args:
        category: Категория сообщения (ERROR, INFO, DEBUG)
        message: Текст сообщения
    """
    if category == "ERROR":
        print(f"[ERROR] {message}")
        logger.error(message)
    elif category == "INFO":
        print(f"[INFO] {message}")
        logger.info(message)
    elif DEBUG and category == "DEBUG":
        print(f"[DEBUG] {message}")
        logger.debug(message)

def load_config():
    """
    Загружает конфигурацию из файла.
    """
    try:
        if DEBUG:
            log_message("DEBUG", f"Чтение конфигурации из {CONFIG_PATH}")
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
            # Устанавливаем значения по умолчанию, если их нет
            if "timezone" not in config:
                config["timezone"] = "Asia/Novosibirsk"
            if "schedule_enabled" not in config:
                config["schedule_enabled"] = True
            if "open_times" not in config:
                config["open_times"] = {}
            if "breaks" not in config:
                config["breaks"] = {}

            return config
    except Exception as e:
        log_message("ERROR", f"Ошибка чтения конфигурации: {e}")
        # Возвращаем конфигурацию по умолчанию при ошибке
        return {
            "timezone": "Asia/Novosibirsk",
            "schedule_enabled": True,
            "open_times": {},
            "breaks": {}
        }

def save_config(cfg):
    """
    Сохраняет конфигурацию в файл.
    """
    try:
        if DEBUG:
            log_message("DEBUG", f"Сохранение конфигурации в {CONFIG_PATH}")

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_message("ERROR", f"Ошибка сохранения конфигурации: {e}")
        raise

# Проверка авторизации (только для chat_id из .env)
AUTHORIZED_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def send_telegram_message(token, chat_id, text):
    if DEBUG:
        logger.debug(f"Отправка сообщения в Telegram: chat_id={chat_id}, text={text}")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, data=payload, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"Ошибка отправки Telegram: {resp.text}")
    except Exception as e:
        logger.warning(f"Ошибка отправки Telegram: {str(e)}\n{traceback.format_exc()}")

def is_authorized(update):
    cid = str(update.effective_chat.id)
    if DEBUG:
        logger.debug(f"Проверка авторизации chat_id={cid}, разрешённый={AUTHORIZED_CHAT_ID}")
    return cid == str(AUTHORIZED_CHAT_ID)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает команду /start. Приветствие и краткая инструкция.
    """
    log_message("INFO", f"Получена команда /start от chat_id={update.effective_chat.id}")
    await menu(update, context)

async def setchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Запрашивает у пользователя кодовое слово для смены chat_id.
    """
    log_message("INFO", f"Получена команда /setchat от chat_id={update.effective_chat.id}")
    await send_message(update, "Введите кодовое слово:")
    return ASK_CODEWORD

async def check_codeword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Проверяет введённое кодовое слово. Если верно — предлагает подтвердить смену chat_id.
    """
    log_message("DEBUG", f"check_codeword: введено '{update.message.text.strip()}', ожидается '{CODEWORD}'")
    if update.message.text.strip() == CODEWORD:
        log_message("DEBUG", f"Кодовое слово верно. chat_id={update.message.chat_id}")
        await send_message(update, "Кодовое слово верно! Подтвердите смену получателя (да/нет):")
        context.user_data['new_chat_id'] = update.message.chat_id
        return CONFIRM_CHANGE
    else:
        log_message("DEBUG", "Неверное кодовое слово")
        await send_message(update, "Неверное кодовое слово.")
        return ConversationHandler.END

async def confirm_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Подтверждает смену chat_id, обновляет .env и перезапускает auto_unlocker (если возможно).
    """
    log_message("DEBUG", f"confirm_change: ответ пользователя '{update.message.text}'")
    if update.message.text.lower() == 'да':
        new_chat_id = str(context.user_data['new_chat_id'])
        log_message("DEBUG", f"Начинаю запись chat_id={new_chat_id} в {ENV_PATH}")
        try:
            with open(ENV_PATH, 'r') as f:
                lines = f.readlines()
            log_message("DEBUG", f"Прочитано {len(lines)} строк из .env")
        except Exception as e:
            msg = f"Не удалось прочитать .env: {e}"
            log_message("ERROR", msg)
            await send_message(update, msg)
            return ConversationHandler.END
        try:
            with open(ENV_PATH, 'w') as f:
                found = False
                for line in lines:
                    if line.startswith('TELEGRAM_CHAT_ID='):
                        f.write(f'TELEGRAM_CHAT_ID={new_chat_id}\n')
                        found = True
                        log_message("DEBUG", f"Заменяю строку: TELEGRAM_CHAT_ID={new_chat_id}")
                    else:
                        f.write(line)
                if not found:
                    f.write(f'TELEGRAM_CHAT_ID={new_chat_id}\n')
                    log_message("DEBUG", f"Добавляю строку: TELEGRAM_CHAT_ID={new_chat_id}")
            log_message("DEBUG", "Запись в .env завершена")
            log_message("INFO", f"Chat ID изменён на {new_chat_id} в .env")
        except Exception as e:
            msg = f"Не удалось записать .env: {e}"
            log_message("ERROR", msg)
            await send_message(update, msg)
            return ConversationHandler.END
        # Пробуем перезапустить контейнер, если он есть
        await restart_auto_unlocker_and_notify(update, logger, "Получатель уведомлений изменён, скрипт перезапущен.", "Ошибка перезапуска контейнера")
        return ConversationHandler.END
    else:
        await send_message(update, "Операция отменена.")
        return ConversationHandler.END

async def restart_auto_unlocker_and_notify(update, logger, message_success, message_error):
    """
    Перезапускает сервис автооткрытия и отправляет уведомление.
    """
    log_message("DEBUG", "Пробую перезапустить сервис автооткрытия...")
    try:
        client = docker.from_env()
        container = client.containers.get(AUTO_UNLOCKER_CONTAINER)
        container.restart()
        await send_message(update, message_success)
        log_message("INFO", "Сервис автооткрытия перезапущен после изменения конфигурации.")
    except Exception as e:
        await send_message(update, f"{message_error}: {e}")
        log_message("ERROR", f"Ошибка перезапуска сервиса автооткрытия: {e}")
        log_exception(logger)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает текущий статус расписания и сервиса.
    """
    log_message("INFO", f"Получена команда /status от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return
    cfg = load_config()
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
        log_message("ERROR", f"Ошибка получения статуса контейнера: {e}")
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

    await send_message(update, msg)

async def enable_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Включает расписание.
    """
    log_message("INFO", f"Получена команда /enable_schedule от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return
    cfg = load_config()
    cfg["schedule_enabled"] = True
    save_config(cfg)
    # Перезапуск auto_unlocker
    await restart_auto_unlocker_and_notify(update, logger, "Расписание <b>включено</b>.\nAuto_unlocker перезапущен, изменения применены.", "Расписание <b>включено</b>, но не удалось перезапустить auto_unlocker")

async def disable_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отключает расписание.
    """
    log_message("INFO", f"Получена команда /disable_schedule от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return
    cfg = load_config()
    cfg["schedule_enabled"] = False
    save_config(cfg)
    # Перезапуск auto_unlocker
    await restart_auto_unlocker_and_notify(update, logger, "Расписание <b>отключено</b>.\nAuto_unlocker перезапущен, изменения применены.", "Расписание <b>отключено</b>, но не удалось перезапустить auto_unlocker")

async def open_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Открывает замок.
    """
    log_message("INFO", f"Получена команда /open от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return
    try:
        token = ttlock_api.get_token(logger)
        log_message("DEBUG", f"Получен токен: {token}")
        resp = ttlock_api.unlock_lock(token, TTLOCK_LOCK_ID, logger)
        log_message("DEBUG", f"Ответ от API: {resp}")
        if resp['errcode'] == 0:
            await send_message(update, f"Замок <b>открыт</b>.\nПопытка: {resp['attempt']}")
        else:
            msg = f"Ошибка открытия замка: {resp.get('errmsg', 'Неизвестная ошибка')}"
            log_message("ERROR", msg)
            await send_message(update, msg)
    except Exception as e:
        msg = f"Ошибка при открытии замка: {e}"
        log_message("ERROR", msg)
        await send_message(update, msg)

async def close_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Закрывает замок.
    """
    log_message("INFO", f"Получена команда /close от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return
    try:
        token = ttlock_api.get_token(logger)
        log_message("DEBUG", f"Получен токен: {token}")
        resp = ttlock_api.lock_lock(token, TTLOCK_LOCK_ID, logger)
        log_message("DEBUG", f"Ответ от API: {resp}")
        if resp['errcode'] == 0:
            await send_message(update, f"Замок <b>закрыт</b>.\nПопытка: {resp['attempt']}")
        else:
            msg = f"Ошибка закрытия замка: {resp.get('errmsg', 'Неизвестная ошибка')}"
            log_message("ERROR", msg)
            await send_message(update, msg)
    except Exception as e:
        msg = f"Ошибка при закрытии замка: {e}"
        log_message("ERROR", msg)
        await send_message(update, msg)

async def settimezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Начинает процесс настройки часового пояса.
    """
    log_message("INFO", f"Получена команда /settimezone от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return ConversationHandler.END
    await send_message(update, "Введите часовой пояс (например, Europe/Moscow):")
    return SETTIMEZONE_VALUE

async def settimezone_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Применяет новый часовой пояс.
    """
    if DEBUG:
        log_message("DEBUG", f"Пользователь вводит TZ: {update.message.text.strip()}")
    tz = update.message.text.strip()
    try:
        # Проверяем валидность часового пояса
        pytz.timezone(tz)
        cfg = load_config()
        cfg["timezone"] = tz
        save_config(cfg)
        # Перезапуск auto_unlocker
        await restart_auto_unlocker_and_notify(update, logger, f"Часовой пояс изменён на <code>{tz}</code>.<br>Auto_unlocker перезапущен, изменения применены.", "Часовой пояс изменён, но не удалось перезапустить auto_unlocker")
        return ConversationHandler.END
    except pytz.exceptions.UnknownTimeZoneError:
        await send_message(update, "Некорректный часовой пояс. Попробуйте ещё раз.")
        return SETTIMEZONE_VALUE
    except Exception as e:
        log_message("ERROR", f"Ошибка при смене часового пояса: {e}")
        await send_message(update, f"Ошибка при смене часового пояса: {e}")
        return ConversationHandler.END

async def settime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Начало процесса настройки времени открытия.
    """
    if not is_authorized(update):
        await update.message.reply_text("⛔️ У вас нет доступа к этой команде.")
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
    await update.message.reply_text(
        "Выберите день недели для настройки времени открытия:",
        reply_markup=reply_markup
    )
    return SETTIME_DAY

async def handle_settime_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик нажатия на inline-кнопку выбора дня недели.
    """
    query = update.callback_query
    await query.answer()

    # Сохраняем выбранный день
    context.user_data["day"] = query.data

    # Удаляем inline-клавиатуру
    await query.edit_message_text(
        text=f"Выбран день: {query.data}\nВведите время открытия в формате ЧЧ:ММ (например, 09:00):"
    )

    return SETTIME_VALUE

async def settime_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает выбор времени открытия.
    """
    if DEBUG:
        log_message("DEBUG", f"Пользователь вводит время: {update.message.text.strip()}")
    time_str = update.message.text.strip()

    # Проверяем формат времени
    if not re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$', time_str):
        await send_message(update, "Некорректный формат времени. Используйте ЧЧ:ММ (например, 09:00).")
        return SETTIME_VALUE

    try:
        # Проверяем валидность времени
        hour, minute = map(int, time_str.split(':'))
        if hour > 23 or minute > 59:
            await send_message(update, "Некорректное время. Часы должны быть от 0 до 23, минуты от 0 до 59.")
            return SETTIME_VALUE

        cfg = load_config()
        if "open_times" not in cfg:
            cfg["open_times"] = {}

        cfg["open_times"][context.user_data["day"]] = time_str
        save_config(cfg)

        # Перезапуск auto_unlocker
        await restart_auto_unlocker_and_notify(
            update,
            logger,
            f"Время открытия для {context.user_data['day']} установлено на <code>{time_str}</code>.<br>Auto_unlocker перезапущен, изменения применены.",
            "Время открытия изменено, но не удалось перезапустить auto_unlocker"
        )
        return ConversationHandler.END
    except Exception as e:
        log_message("ERROR", f"Ошибка при установке времени: {e}")
        await send_message(update, f"Ошибка при установке времени: {e}")
        return ConversationHandler.END

async def setbreak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Начинает процесс установки перерывов.
    """
    log_message("INFO", f"Получена команда /setbreak от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(day, callback_data=f"setbreak_{day}")] for day in DAYS]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_message(update, "Выберите день недели:", reply_markup=reply_markup)
    return SETBREAK_DAY

async def setbreak_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает выбор дня для настройки перерывов.
    """
    day = update.message.text.strip()
    if day not in DAYS:
        await send_message(update, "Некорректный день недели. Выберите из списка.")
        return SETBREAK_DAY

    context.user_data["day"] = day
    cfg = load_config()
    breaks = cfg.get("breaks", {}).get(day, [])

    msg = f"Текущие перерывы для {day}:\n"
    if breaks:
        msg += "\n".join(breaks)
    else:
        msg += "Нет перерывов"

    keyboard = [
        [InlineKeyboardButton("Добавить", callback_data="add_break")],
        [InlineKeyboardButton("Удалить", callback_data="remove_break")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_message(update, msg, reply_markup=reply_markup)
    return SETBREAK_ACTION

async def setbreak_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает выбор действия для перерывов (добавить/удалить).
    """
    action = update.message.text.strip().lower()
    if action == "добавить":
        await send_message(update, "Введите время перерыва в формате ЧЧ:ММ-ЧЧ:ММ (например, 12:00-13:00):")
        return SETBREAK_ADD
    elif action == "удалить":
        cfg = load_config()
        breaks = cfg.get("breaks", {}).get(context.user_data["day"], [])
        if not breaks:
            await send_message(update, "Нет перерывов для удаления.")
            return SETBREAK_DAY
        await send_message(update, "Введите время перерыва для удаления в формате ЧЧ:ММ-ЧЧ:ММ:")
        return SETBREAK_DEL
    else:
        await send_message(update, "Некорректное действие. Выберите 'Добавить' или 'Удалить'.")
        return SETBREAK_ACTION

async def setbreak_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Добавляет перерыв.
    """
    if DEBUG:
        log_message("DEBUG", f"Пользователь вводит перерыв: {update.message.text.strip()}")
    break_str = update.message.text.strip()

    # Проверяем формат перерыва
    if not re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]-([01]?[0-9]|2[0-3]):[0-5][0-9]$', break_str):
        await send_message(update, "Некорректный формат перерыва. Используйте ЧЧ:ММ-ЧЧ:ММ (например, 12:00-13:00).")
        return SETBREAK_DAY

    try:
        # Проверяем валидность времени перерыва
        start_time, end_time = break_str.split('-')
        start_hour, start_minute = map(int, start_time.split(':'))
        end_hour, end_minute = map(int, end_time.split(':'))

        if start_hour > 23 or start_minute > 59 or end_hour > 23 or end_minute > 59:
            await send_message(update, "Некорректное время. Часы должны быть от 0 до 23, минуты от 0 до 59.")
            return SETBREAK_DAY

        # Проверяем, что конец перерыва позже начала
        if (end_hour < start_hour) or (end_hour == start_hour and end_minute <= start_minute):
            await send_message(update, "Время окончания перерыва должно быть позже времени начала.")
            return SETBREAK_DAY

        cfg = load_config()
        if "breaks" not in cfg:
            cfg["breaks"] = {}
        if context.user_data["day"] not in cfg["breaks"]:
            cfg["breaks"][context.user_data["day"]] = []

        # Проверяем на пересечение с существующими перерывами
        for existing_break in cfg["breaks"][context.user_data["day"]]:
            existing_start, existing_end = existing_break.split('-')
            if (start_time <= existing_end and end_time >= existing_start):
                await send_message(update, "Этот перерыв пересекается с существующим. Выберите другое время.")
                return SETBREAK_DAY

        cfg["breaks"][context.user_data["day"]].append(break_str)
        save_config(cfg)

        # Перезапуск auto_unlocker
        await restart_auto_unlocker_and_notify(
            update,
            logger,
            f"Добавлен перерыв {break_str} для {context.user_data['day']}.<br>Auto_unlocker перезапущен, изменения применены.",
            "Перерыв добавлен, но не удалось перезапустить auto_unlocker"
        )
        return ConversationHandler.END
    except Exception as e:
        log_message("ERROR", f"Ошибка при добавлении перерыва: {e}")
        await send_message(update, f"Ошибка при добавлении перерыва: {e}")
        return ConversationHandler.END

async def setbreak_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Удаляет перерыв.
    """
    if DEBUG:
        log_message("DEBUG", f"Пользователь вводит перерыв для удаления: {update.message.text.strip()}")
    break_str = update.message.text.strip()

    # Проверяем формат перерыва
    if not re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]-([01]?[0-9]|2[0-3]):[0-5][0-9]$', break_str):
        await send_message(update, "Некорректный формат перерыва. Используйте ЧЧ:ММ-ЧЧ:ММ (например, 12:00-13:00).")
        return SETBREAK_DAY

    try:
        cfg = load_config()
        if context.user_data["day"] in cfg.get("breaks", {}) and break_str in cfg["breaks"][context.user_data["day"]]:
            cfg["breaks"][context.user_data["day"]].remove(break_str)
            save_config(cfg)

            # Перезапуск auto_unlocker
            await restart_auto_unlocker_and_notify(
                update,
                logger,
                f"Удалён перерыв {break_str} для {context.user_data['day']}.<br>Auto_unlocker перезапущен, изменения применены.",
                "Перерыв удалён, но не удалось перезапустить auto_unlocker"
            )
        else:
            await send_message(update, "Такой перерыв не найден.")
        return ConversationHandler.END
    except Exception as e:
        log_message("ERROR", f"Ошибка при удалении перерыва: {e}")
        await send_message(update, f"Ошибка при удалении перерыва: {e}")
        return ConversationHandler.END

async def restart_auto_unlocker_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Перезапускает сервис автооткрытия по команде.
    """
    log_message("INFO", f"Получена команда /restart_auto_unlocker от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return
    await restart_auto_unlocker_and_notify(update, logger, "Сервис автооткрытия перезапущен по команде.", "Не удалось перезапустить сервис автооткрытия")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Выводит список всех доступных команд в виде кнопок.
    """
    log_message("INFO", f"Получена команда /menu от chat_id={update.effective_chat.id}")

    # Создаем клавиатуру с кнопками
    keyboard = [
        ["📊 Статус", "📅 Расписание"],
        ["🔓 Открыть", "🔒 Закрыть"],
        ["⚙️ Настройки", "📝 Логи"],
        ["🔄 Перезапуск"]
    ]

    # Создаем клавиатуру с постоянной кнопкой меню
    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите действие"
    )

    # Отправляем сообщение с кнопками
    await update.message.reply_text(
        "Выберите действие:",
        reply_markup=reply_markup
    )

async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик нажатий на кнопки меню.
    """
    text = update.message.text

    # Удаляем клавиатуру после выбора
    await update.message.reply_text(
        "Выполняю команду...",
        reply_markup=ReplyKeyboardRemove()
    )

    # Обработка нажатий на кнопки
    if text == "📊 Статус":
        await status(update, context)
    elif text == "📅 Расписание":
        # Показываем подменю расписания
        keyboard = [
            ["✅ Включить расписание", "❌ Выключить расписание"],
            ["⏰ Настроить время", "🕒 Настроить перерывы"],
            ["🌍 Настроить часовой пояс"]
        ]
        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await update.message.reply_text(
            "Выберите действие с расписанием:",
            reply_markup=reply_markup
        )
    elif text == "🔓 Открыть":
        await open_lock(update, context)
    elif text == "🔒 Закрыть":
        await close_lock(update, context)
    elif text == "⚙️ Настройки":
        # Показываем подменю настроек
        keyboard = [
            ["👤 Сменить получателя", "⏰ Макс. время попыток"],
            ["🔙 Назад"]
        ]
        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await update.message.reply_text(
            "Выберите настройку:",
            reply_markup=reply_markup
        )
    elif text == "📝 Логи":
        await logs(update, context)
    elif text == "🔄 Перезапуск":
        await restart_auto_unlocker_cmd(update, context)
    elif text == "✅ Включить расписание":
        await enable_schedule(update, context)
    elif text == "❌ Выключить расписание":
        await disable_schedule(update, context)
    elif text == "⏰ Настроить время":
        await settime(update, context)
    elif text == "🕒 Настроить перерывы":
        await setbreak(update, context)
    elif text == "🌍 Настроить часовой пояс":
        await settimezone(update, context)
    elif text == "👤 Сменить получателя":
        await setchat(update, context)
    elif text == "⏰ Макс. время попыток":
        await setmaxretrytime(update, context)
    elif text == "🔙 Назад":
        await menu(update, context)

async def send_message(update: Update, text: str, parse_mode: str = "HTML", **kwargs: Any) -> None:
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
        log_message("DEBUG", f"Отправка сообщения пользователю {update.effective_chat.id}")
        await update.message.reply_text(text, parse_mode=parse_mode, **kwargs)
    except Exception as e:
        log_message("ERROR", f"Ошибка отправки сообщения: {e}")
        log_message("ERROR", traceback.format_exc())
        # Пробуем отправить без форматирования
        try:
            await update.message.reply_text(text, parse_mode=None, **kwargs)
        except Exception as e:
            log_message("ERROR", f"Ошибка отправки сообщения без форматирования: {e}")

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
        log_message("ERROR", f"Ошибка чтения логов: {e}")
        return f"Ошибка чтения логов: {e}"

async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает последние записи из логов сервиса автооткрытия.
    """
    log_message("INFO", f"Получена команда /logs от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return

    try:
        message = format_logs()
        await send_message(update, message)
    except Exception as e:
        log_message("ERROR", f"Ошибка при получении логов: {e}")
        await send_message(update, f"Ошибка при получении логов: {e}")

async def setmaxretrytime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Начало диалога настройки максимального времени для попыток.
    """
    if not is_authorized(update):
        return ConversationHandler.END

    await update.message.reply_text(
        "Введите максимальное время для попыток открытия замка в формате ЧЧ:ММ\n"
        "Например: 21:00\n"
        "Это время, после которого система прекратит попытки открыть замок в текущий день."
    )
    return SETMAXRETRYTIME_VALUE

async def setmaxretrytime_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработка введенного максимального времени для попыток.
    """
    if not is_authorized(update):
        return ConversationHandler.END

    time_str = update.message.text.strip()

    # Проверяем формат времени
    try:
        datetime.strptime(time_str, "%H:%M")
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат времени. Используйте формат ЧЧ:ММ (например, 21:00)"
        )
        return SETMAXRETRYTIME_VALUE

    # Загружаем текущую конфигурацию
    config = load_config()

    # Обновляем время
    config["max_retry_time"] = time_str

    # Сохраняем конфигурацию
    save_config(config)

    # Перезапускаем сервис
    await restart_auto_unlocker_and_notify(
        update,
        logger,
        f"✅ Максимальное время для попыток открытия установлено на {time_str}",
        "❌ Ошибка при перезапуске сервиса"
    )

    return ConversationHandler.END

def main():
    """
    Точка входа: запускает Telegram-бота и обработчики команд.
    """
    try:
        log_message("DEBUG", "Запуск Telegram-бота...")
        if not BOT_TOKEN:
            log_message("ERROR", "TELEGRAM_BOT_TOKEN не задан в .env!")
            return

        app = ApplicationBuilder().token(BOT_TOKEN).build()

        # Регистрация обработчиков команд
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
            # Добавляем обработчик для кнопок меню
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_button),
            ConversationHandler(
                entry_points=[CommandHandler('setchat', setchat)],
                states={
                    ASK_CODEWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_codeword)],
                    CONFIRM_CHANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_change)],
                },
                fallbacks=[]
            ),
            ConversationHandler(
                entry_points=[CommandHandler('settimezone', settimezone)],
                states={
                    SETTIMEZONE_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settimezone_apply)],
                },
                fallbacks=[]
            ),
            ConversationHandler(
                entry_points=[CommandHandler('settime', settime)],
                states={
                    SETTIME_DAY: [CallbackQueryHandler(handle_settime_callback)],
                    SETTIME_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settime_value)],
                },
                fallbacks=[]
            ),
            ConversationHandler(
                entry_points=[CommandHandler('setbreak', setbreak)],
                states={
                    SETBREAK_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbreak_day)],
                    SETBREAK_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbreak_action)],
                    SETBREAK_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbreak_add)],
                    SETBREAK_DEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbreak_remove)],
                },
                fallbacks=[]
            ),
            ConversationHandler(
                entry_points=[CommandHandler('setmaxretrytime', setmaxretrytime)],
                states={
                    SETMAXRETRYTIME_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, setmaxretrytime_value)],
                },
                fallbacks=[]
            )
        ]

        for handler in handlers:
            app.add_handler(handler)

        log_message("INFO", "Telegram-бот успешно запущен и готов к работе.")
        app.run_polling()
    except Exception as e:
        log_message("ERROR", f"Критическая ошибка при запуске бота: {e}")
        log_exception(logger)
        raise

if __name__ == '__main__':
    main()
