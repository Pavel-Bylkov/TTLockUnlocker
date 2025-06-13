"""
Telegram-бот для управления рассылкой уведомлений TTLock и смены chat_id через Docker.
Используется совместно с auto_unlocker.py. Все параметры берутся из .env.

Для отладки можно установить переменную окружения DEBUG=1 (или true/True) — тогда будет подробный вывод в консоль.
"""
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
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

ASK_CODEWORD, CONFIRM_CHANGE = range(2)

CONFIG_PATH = os.getenv("CONFIG_PATH", "config.json")

# TTLock API команды для мгновенного открытия/закрытия
TTLOCK_CLIENT_ID = os.getenv("TTLOCK_CLIENT_ID")
TTLOCK_CLIENT_SECRET = os.getenv("TTLOCK_CLIENT_SECRET")
TTLOCK_USERNAME = os.getenv("TTLOCK_USERNAME")
TTLOCK_PASSWORD = os.getenv("TTLOCK_PASSWORD")
TTLOCK_LOCK_ID = os.getenv("TTLOCK_LOCK_ID")

SET_TIMEZONE = range(10, 11)

SETTIME_DAY, SETTIME_VALUE = range(20, 22)
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
DAY_MAP = dict(zip(DAYS_RU, DAYS))
DAY_MAP_INV = dict(zip(DAYS, DAYS_RU))

SETBREAK_DAY, SETBREAK_ACTION, SETBREAK_ADD, SETBREAK_DEL = range(30, 34)

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

def load_config():
    """
    Загружает конфигурацию из файла.
    """
    try:
        if DEBUG:
            log_message("DEBUG", f"Чтение конфигурации из {CONFIG_PATH}")
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        if DEBUG:
            log_message("DEBUG", f"Ошибка чтения config: {e}")
        return {}

def save_config(cfg):
    """
    Сохраняет конфигурацию в файл.
    """
    if DEBUG:
        log_message("DEBUG", f"Сохраняю конфиг в {CONFIG_PATH}: {cfg}")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

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
    if DEBUG:
        log_message("DEBUG", f"/start вызван от chat_id={update.effective_chat.id}")
    await menu(update, context)

async def setchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Запрашивает у пользователя кодовое слово для смены chat_id.
    """
    logger.info(f"Получена команда /setchat от chat_id={update.effective_chat.id}")
    if DEBUG:
        logger.debug(f"/setchat вызван от chat_id={update.message.chat_id}")
    await send_message(update, "Введите кодовое слово:")
    return ASK_CODEWORD

async def check_codeword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Проверяет введённое кодовое слово. Если верно — предлагает подтвердить смену chat_id.
    """
    if DEBUG:
        logger.debug(f"check_codeword: введено '{update.message.text.strip()}', ожидается '{CODEWORD}'")
    if update.message.text.strip() == CODEWORD:
        if DEBUG:
            logger.debug(f"Кодовое слово верно. chat_id={update.message.chat_id}")
        await send_message(update, "Кодовое слово верно! Подтвердите смену получателя (да/нет):")
        context.user_data['new_chat_id'] = update.message.chat_id
        return CONFIRM_CHANGE
    else:
        if DEBUG:
            logger.debug("[DEBUG] Неверное кодовое слово")
        await send_message(update, "Неверное кодовое слово.")
        return ConversationHandler.END

async def confirm_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Подтверждает смену chat_id, обновляет .env и перезапускает auto_unlocker (если возможно).
    """
    if DEBUG:
        log_message("DEBUG", f"confirm_change: ответ пользователя '{update.message.text}'")
    if update.message.text.lower() == 'да':
        new_chat_id = str(context.user_data['new_chat_id'])
        if DEBUG:
            log_message("DEBUG", f"Начинаю запись chat_id={new_chat_id} в {ENV_PATH}")
        try:
            with open(ENV_PATH, 'r') as f:
                lines = f.readlines()
            if DEBUG:
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
                        if DEBUG:
                            log_message("DEBUG", f"Заменяю строку: TELEGRAM_CHAT_ID={new_chat_id}")
                    else:
                        f.write(line)
                if not found:
                    f.write(f'TELEGRAM_CHAT_ID={new_chat_id}\n')
                    if DEBUG:
                        log_message("DEBUG", f"Добавляю строку: TELEGRAM_CHAT_ID={new_chat_id}")
            if DEBUG:
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
    if DEBUG:
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
    if DEBUG:
        log_message("DEBUG", "Выполняется /status, загружаю config и логи auto_unlocker...")
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
        msg += f"{DAY_MAP_INV.get(day, day.title())}: {t if t else 'выключено'}\n"
    
    # Только дни с перерывами
    breaks_with_values = {day: br for day, br in breaks.items() if br}
    if breaks_with_values:
        msg += "<b>Перерывы:</b>\n"
        for day, br in breaks_with_values.items():
            msg += f"{DAY_MAP_INV.get(day, day.title())}: {', '.join(br)}\n"
    
    await send_message(update, msg)

async def enable_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Включает расписание.
    """
    log_message("INFO", f"Получена команда /enable_schedule от chat_id={update.effective_chat.id}")
    if DEBUG:
        log_message("DEBUG", "Включаю расписание через /enable_schedule")
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
    if DEBUG:
        log_message("DEBUG", "Отключаю расписание через /disable_schedule")
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
        if DEBUG:
            log_message("DEBUG", f"Получен токен: {token}")
        resp = ttlock_api.unlock_lock(token, TTLOCK_LOCK_ID, logger)
        if DEBUG:
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
        if DEBUG:
            log_message("DEBUG", f"Получен токен: {token}")
        resp = ttlock_api.lock_lock(token, TTLOCK_LOCK_ID, logger)
        if DEBUG:
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
    return SET_TIMEZONE

async def settimezone_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Применяет новый часовой пояс.
    """
    if DEBUG:
        log_message("DEBUG", f"Пользователь вводит TZ: {update.message.text.strip()}")
    tz = update.message.text.strip()
    try:
        pytz.timezone(tz)
    except Exception:
        await send_message(update, "Некорректный часовой пояс. Попробуйте ещё раз.")
        return SET_TIMEZONE
    cfg = load_config()
    cfg["timezone"] = tz
    save_config(cfg)
    # Перезапуск auto_unlocker
    await restart_auto_unlocker_and_notify(update, logger, f"Часовой пояс изменён на <code>{tz}</code>.<br>Auto_unlocker перезапущен, изменения применены.", "Часовой пояс изменён, но не удалось перезапустить auto_unlocker")
    return ConversationHandler.END

async def settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Начинает процесс настройки времени открытия.
    """
    log_message("INFO", f"Получена команда /settime от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return ConversationHandler.END
    await send_message(update, "Выберите день недели:", reply_markup=ReplyKeyboardMarkup([DAYS_RU], one_time_keyboard=True))
    return SETTIME_DAY

async def settime_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает выбор дня недели для настройки времени.
    """
    if DEBUG:
        log_message("DEBUG", f"settime_day: ответ пользователя '{update.message.text}'")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return ConversationHandler.END
    day = update.message.text.strip()
    if day not in DAY_MAP:
        await send_message(update, "Некорректный день недели. Выберите из списка.")
        return SETTIME_DAY
    context.user_data['settime_day'] = DAY_MAP[day]
    await send_message(update, f"Введите время открытия для {day} (формат ЧЧ:ММ):", reply_markup=ReplyKeyboardRemove())
    return SETTIME_VALUE

async def settime_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает ввод времени открытия.
    """
    if DEBUG:
        log_message("DEBUG", f"settime_value: ответ пользователя '{update.message.text}'")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return ConversationHandler.END
    time = update.message.text.strip()
    try:
        datetime.strptime(time, '%H:%M')
    except ValueError:
        await send_message(update, "Некорректный формат времени. Введите в формате ЧЧ:ММ.")
        return SETTIME_VALUE
    day = context.user_data['settime_day']
    cfg = load_config()
    if 'open_times' not in cfg:
        cfg['open_times'] = {}
    cfg['open_times'][day] = time
    save_config(cfg)
    # Перезапуск auto_unlocker
    await restart_auto_unlocker_and_notify(update, logger, f"Время открытия для {day} установлено на {time}. Auto_unlocker перезапущен, изменения применены.", f"Время открытия для {day} установлено на {time}, но не удалось перезапустить auto_unlocker")
    await send_message(update, f"Время открытия для {day} установлено на {time}.\nХотите изменить время для другого дня?")
    return SETTIME_DAY

async def settime_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Добавляет время открытия для выбранного дня.
    """
    if DEBUG:
        log_message("DEBUG", f"settime_add: ответ пользователя '{update.message.text}'")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return ConversationHandler.END
    time = update.message.text.strip()
    try:
        datetime.strptime(time, '%H:%M')
    except ValueError:
        await send_message(update, "Некорректный формат времени. Введите в формате ЧЧ:ММ.")
        return SETTIME_VALUE
    day = context.user_data['settime_day']
    cfg = load_config()
    if 'open_times' not in cfg:
        cfg['open_times'] = {}
    cfg['open_times'][day] = time
    save_config(cfg)
    # Перезапуск auto_unlocker
    await restart_auto_unlocker_and_notify(update, logger, f"Время открытия для {day} установлено на {time}. Auto_unlocker перезапущен, изменения применены.", f"Время открытия для {day} установлено на {time}, но не удалось перезапустить auto_unlocker")
    await send_message(update, f"Время открытия для {day} установлено на {time}.")
    return SETTIME_DAY

async def setbreak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Начинает процесс настройки перерывов.
    """
    log_message("INFO", f"Получена команда /setbreak от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return ConversationHandler.END
    await send_message(update, "Выберите день недели:", reply_markup=ReplyKeyboardMarkup([DAYS_RU], one_time_keyboard=True))
    return SETBREAK_DAY

async def setbreak_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает выбор дня недели для настройки перерывов.
    """
    if DEBUG:
        log_message("DEBUG", f"setbreak_day: ответ пользователя '{update.message.text}'")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return ConversationHandler.END
    day = update.message.text.strip()
    if day not in DAY_MAP:
        await send_message(update, "Некорректный день недели. Выберите из списка.")
        return SETBREAK_DAY
    context.user_data['break_day'] = DAY_MAP[day]
    cfg = load_config()
    breaks = cfg.get('breaks', {}).get(DAY_MAP[day], [])
    if breaks:
        msg = f"Текущие перерывы для {day}:\n" + "\n".join(breaks)
    else:
        msg = f"Текущие перерывы для {day}:\nНет перерывов"
    await send_message(update, msg + "\n\nВыберите действие:", reply_markup=ReplyKeyboardMarkup([["Добавить", "Удалить"]], one_time_keyboard=True))
    return SETBREAK_ACTION

async def setbreak_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает выбор действия для перерывов.
    """
    if DEBUG:
        log_message("DEBUG", f"setbreak_action: ответ пользователя '{update.message.text}'")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return ConversationHandler.END
    action = update.message.text.strip()
    if action == "Добавить":
        await send_message(update, "Введите интервал перерыва в формате ЧЧ:ММ-ЧЧ:ММ (например, 13:00-14:00):", reply_markup=ReplyKeyboardRemove())
        return SETBREAK_ADD
    elif action == "Удалить":
        cfg = load_config()
        breaks = cfg.get('breaks', {}).get(context.user_data['break_day'], [])
        if not breaks:
            await send_message(update, "Нет перерывов для удаления.")
            return SETBREAK_DAY
        await send_message(update, "Выберите перерыв для удаления:", reply_markup=ReplyKeyboardMarkup([[b] for b in breaks], one_time_keyboard=True))
        return SETBREAK_DEL
    else:
        await send_message(update, "Некорректное действие. Выберите 'Добавить' или 'Удалить'.")
        return SETBREAK_ACTION

async def setbreak_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Удаляет выбранный перерыв.
    """
    if DEBUG:
        log_message("DEBUG", f"setbreak_del: ответ пользователя '{update.message.text}'")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return ConversationHandler.END
    interval = update.message.text.strip()
    day = context.user_data['break_day']
    cfg = load_config()
    if 'breaks' not in cfg:
        cfg['breaks'] = {}
    if day not in cfg['breaks']:
        cfg['breaks'][day] = []
    if interval in cfg['breaks'][day]:
        cfg['breaks'][day].remove(interval)
        save_config(cfg)
        # Перезапуск auto_unlocker
        await restart_auto_unlocker_and_notify(update, logger, f"Перерыв {interval} удалён для {day}. Auto_unlocker перезапущен, изменения применены.", f"Перерыв {interval} удалён для {day}, но не удалось перезапустить auto_unlocker")
        await send_message(update, f"Перерыв {interval} удалён для {day}.")
    else:
        await send_message(update, f"Перерыв {interval} не найден для {day}.")
    return SETBREAK_DAY

async def setbreak_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Добавляет перерыв для выбранного дня.
    """
    if DEBUG:
        log_message("DEBUG", f"setbreak_add: ответ пользователя '{update.message.text}'")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return ConversationHandler.END
    interval = update.message.text.strip()
    try:
        start, end = interval.split('-')
        start = start.strip()
        end = end.strip()
        # Проверяем формат времени
        datetime.strptime(start, '%H:%M')
        datetime.strptime(end, '%H:%M')
        day = context.user_data['break_day']
        cfg = load_config()
        if 'breaks' not in cfg:
            cfg['breaks'] = {}
        if day not in cfg['breaks']:
            cfg['breaks'][day] = []
        cfg['breaks'][day].append(f"{start}-{end}")
        save_config(cfg)
        # Перезапуск auto_unlocker
        await restart_auto_unlocker_and_notify(update, logger, f"Перерыв {interval} добавлен для {day}. Auto_unlocker перезапущен, изменения применены.", f"Перерыв {interval} добавлен для {day}, но не удалось перезапустить auto_unlocker")
        await send_message(update, f"Перерыв {interval} добавлен для {day}.")
        await send_message(update, "Пожалуйста, выберите день из списка:", reply_markup=ReplyKeyboardMarkup([DAYS_RU], one_time_keyboard=True))
        return SETBREAK_DAY
    except Exception as e:
        msg = f"Ошибка разбора интервала перерыва {interval} для {day}: {e}"
        log_message("ERROR", msg)
        await send_message(update, msg)
        return SETBREAK_DAY

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
    Выводит список всех доступных команд.
    """
    log_message("INFO", f"Получена команда /menu от chat_id={update.effective_chat.id}")
    menu_text = (
        "<b>Доступные команды:</b>\n"
        "/menu — показать это меню\n"
        "/setchat — сменить получателя уведомлений\n"
        "/status — статус расписания\n"
        "/enable_schedule — включить расписание\n"
        "/disable_schedule — выключить расписание\n"
        "/settimezone — сменить часовой пояс\n"
        "/settime — сменить время открытия\n"
        "/setbreak — настроить перерывы\n"
        "/open — открыть замок\n"
        "/close — закрыть замок\n"
        "/logs — последние логи сервиса\n"
    )
    await send_message(update, menu_text)

async def send_message(update: Update, text: str, parse_mode: str = "HTML", **kwargs):
    """
    Отправляет сообщение пользователю.
    """
    if DEBUG:
        log_message("DEBUG", f"Отправка сообщения: {text}")
    await update.message.reply_text(text, parse_mode=parse_mode, **kwargs)

def format_logs(log_path: str = "logs/auto_unlocker.log") -> str:
    """
    Формирует текст сообщения с логами.
    """
    try:
        if os.path.exists(log_path):
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

            # Объединяем строки
            logs = "\n".join(processed_lines)
        else:
            logs = "Лог-файл не найден."
    except Exception as e:
        log_message("ERROR", f"Ошибка чтения логов: {e}")
        logs = f"Ошибка чтения логов: {e}"

    return f"<b>Последние логи сервиса:</b>\n<code>{logs}</code>"

async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает последние записи из логов сервиса автооткрытия.
    """
    log_message("INFO", f"Получена команда /logs от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await send_message(update, "Нет доступа.")
        return

    message = format_logs()
    await send_message(update, message)

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
    elif category == "DEBUG":
        if DEBUG:
            print(f"[DEBUG] {message}")
            logger.debug(message)

def main():
    """
    Точка входа: запускает Telegram-бота и обработчики команд.
    """
    if DEBUG:
        logger.debug("Запуск Telegram-бота...")
    if not BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN не задан в .env!")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('setchat', setchat)],
        states={
            ASK_CODEWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_codeword)],
            CONFIRM_CHANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_change)],
        },
        fallbacks=[]
    )
    tz_conv = ConversationHandler(
        entry_points=[CommandHandler('settimezone', settimezone)],
        states={
            SET_TIMEZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settimezone_apply)],
        },
        fallbacks=[]
    )
    settime_conv = ConversationHandler(
        entry_points=[CommandHandler('settime', settime)],
        states={
            SETTIME_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, settime_day)],
            SETTIME_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settime_value)],
        },
        fallbacks=[]
    )
    setbreak_conv = ConversationHandler(
        entry_points=[CommandHandler('setbreak', setbreak)],
        states={
            SETBREAK_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbreak_day)],
            SETBREAK_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbreak_action)],
            SETBREAK_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbreak_add)],
            SETBREAK_DEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbreak_del)],
        },
        fallbacks=[]
    )
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('menu', menu))
    app.add_handler(CommandHandler('logs', logs))
    app.add_handler(conv_handler)
    app.add_handler(tz_conv)
    app.add_handler(settime_conv)
    app.add_handler(setbreak_conv)
    app.add_handler(CommandHandler('status', status))
    app.add_handler(CommandHandler('enable_schedule', enable_schedule))
    app.add_handler(CommandHandler('disable_schedule', disable_schedule))
    app.add_handler(CommandHandler('open', open_lock))
    app.add_handler(CommandHandler('close', close_lock))
    app.add_handler(CommandHandler('restart_auto_unlocker', restart_auto_unlocker_cmd))
    logger.info("Telegram-бот успешно запущен и готов к работе.")
    app.run_polling()

if __name__ == '__main__':
    main()
