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
import pytz
import ttlock_api
from logging.handlers import TimedRotatingFileHandler
import sys

# Загрузка переменных окружения
load_dotenv('/app/.env')

# Уровень отладки
DEBUG = os.getenv('DEBUG', '0').lower() in ('1', 'true', 'yes')

# Настройка логирования
os.makedirs('logs', exist_ok=True)
logger = logging.getLogger("telegram_bot")
logger.setLevel(logging.INFO)
handler = TimedRotatingFileHandler('logs/telegram_bot.log', when="midnight", backupCount=14, encoding="utf-8")
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
# Дублируем логи в stdout для Docker
console = logging.StreamHandler(sys.stdout)
console.setFormatter(formatter)
logger.addHandler(console)

CODEWORD = os.getenv('TELEGRAM_CODEWORD', 'secretword')
# Определяем путь к .env: сначала из ENV_PATH, иначе ./env
ENV_PATH = os.getenv('ENV_PATH') or './.env'
if DEBUG:
    print(f"[DEBUG] Используется путь к .env: {ENV_PATH}")
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

def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# Проверка авторизации (только для chat_id из .env)
AUTHORIZED_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def is_authorized(update):
    return str(update.effective_chat.id) == str(AUTHORIZED_CHAT_ID)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает команду /start. Приветствие и краткая инструкция.
    """
    logger.info(f"Получена команда /start от chat_id={update.effective_chat.id}")
    if DEBUG:
        print("[DEBUG] /start вызван")
    menu = (
        "Привет! Я бот для управления замками TTLock.\n\n"
        "<b>Доступные команды:</b>\n"
        "/setchat — сменить получателя уведомлений\n"
        "/status — статус расписания\n"
        "/enable_schedule — включить расписание\n"
        "/disable_schedule — выключить расписание\n"
        "/settimezone — сменить часовой пояс\n"
        "/settime — сменить время открытия\n"
        "/setbreak — настроить перерывы\n"
        "/open — открыть замок\n"
        "/close — закрыть замок\n"
    )
    await update.message.reply_text(menu, parse_mode="HTML")

async def setchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Запрашивает у пользователя кодовое слово для смены chat_id.
    """
    logger.info(f"Получена команда /setchat от chat_id={update.effective_chat.id}")
    if DEBUG:
        print(f"[DEBUG] /setchat вызван от chat_id={update.message.chat_id}")
    await update.message.reply_text("Введите кодовое слово:")
    return ASK_CODEWORD

async def check_codeword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Проверяет введённое кодовое слово. Если верно — предлагает подтвердить смену chat_id.
    """
    if DEBUG:
        print(f"[DEBUG] check_codeword: введено '{update.message.text.strip()}', ожидается '{CODEWORD}'")
    if update.message.text.strip() == CODEWORD:
        if DEBUG:
            print(f"[DEBUG] Кодовое слово верно. chat_id={update.message.chat_id}")
        await update.message.reply_text("Кодовое слово верно! Подтвердите смену получателя (да/нет):")
        context.user_data['new_chat_id'] = update.message.chat_id
        return CONFIRM_CHANGE
    else:
        if DEBUG:
            print("[DEBUG] Неверное кодовое слово")
        await update.message.reply_text("Неверное кодовое слово.")
        return ConversationHandler.END

async def confirm_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Подтверждает смену chat_id, обновляет .env и перезапускает auto_unlocker (если возможно).
    """
    if DEBUG:
        print(f"[DEBUG] confirm_change: ответ пользователя '{update.message.text}'")
    if update.message.text.lower() == 'да':
        new_chat_id = str(context.user_data['new_chat_id'])
        if DEBUG:
            print(f"[DEBUG] Начинаю запись chat_id={new_chat_id} в {ENV_PATH}")
        try:
            with open(ENV_PATH, 'r') as f:
                lines = f.readlines()
            if DEBUG:
                print(f"[DEBUG] Прочитано {len(lines)} строк из .env")
        except Exception as e:
            print(f"[ERROR] Не удалось прочитать .env: {e}")
            await update.message.reply_text(f"Ошибка чтения .env: {e}")
            return ConversationHandler.END
        try:
            with open(ENV_PATH, 'w') as f:
                found = False
                for line in lines:
                    if line.startswith('TELEGRAM_CHAT_ID='):
                        f.write(f'TELEGRAM_CHAT_ID={new_chat_id}\n')
                        found = True
                        if DEBUG:
                            print(f"[DEBUG] Заменяю строку: TELEGRAM_CHAT_ID={new_chat_id}")
                    else:
                        f.write(line)
                if not found:
                    f.write(f'TELEGRAM_CHAT_ID={new_chat_id}\n')
                    if DEBUG:
                        print(f"[DEBUG] Добавляю строку: TELEGRAM_CHAT_ID={new_chat_id}")
            if DEBUG:
                print(f"[DEBUG] Запись в .env завершена")
            logging.info(f"Chat ID изменён на {new_chat_id} в .env")
        except Exception as e:
            print(f"[ERROR] Не удалось записать .env: {e}")
            await update.message.reply_text(f"Ошибка записи .env: {e}")
            return ConversationHandler.END
        # Пробуем перезапустить контейнер, если он есть
        try:
            if DEBUG:
                print(f"[DEBUG] Пробую получить контейнер {AUTO_UNLOCKER_CONTAINER}")
            client = docker.from_env()
            container = client.containers.get(AUTO_UNLOCKER_CONTAINER)
            container.restart()
            await update.message.reply_text("Получатель уведомлений изменён, скрипт перезапущен.")
            if DEBUG:
                print(f"[DEBUG] Контейнер {AUTO_UNLOCKER_CONTAINER} перезапущен")
            logging.info(f"Контейнер {AUTO_UNLOCKER_CONTAINER} перезапущен.")
        except docker.errors.NotFound:
            await update.message.reply_text("Chat ID сохранён в .env. Контейнер auto_unlocker не найден. Перезапустите его вручную, чтобы изменения вступили в силу.")
            if DEBUG:
                print(f"[DEBUG] Контейнер {AUTO_UNLOCKER_CONTAINER} не найден. Только обновлён .env.")
            logging.warning(f"Контейнер {AUTO_UNLOCKER_CONTAINER} не найден. Только обновлён .env.")
        except Exception as e:
            await update.message.reply_text(f"Chat ID сохранён в .env, но ошибка при попытке перезапуска контейнера: {str(e)}")
            print(f"[ERROR] Ошибка перезапуска контейнера: {e}")
            logging.error(f"Ошибка перезапуска контейнера: {str(e)}")
    else:
        if DEBUG:
            print("[DEBUG] Операция отменена пользователем")
        await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Получена команда /status от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await update.message.reply_text("Нет доступа.")
        return
    cfg = load_config()
    tz = cfg.get("timezone", "?")
    enabled = cfg.get("schedule_enabled", True)
    open_times = cfg.get("open_times", {})
    breaks = cfg.get("breaks", {})
    msg = f"<b>Статус расписания</b>\n"
    msg += f"Часовой пояс: <code>{tz}</code>\n"
    msg += f"Расписание включено: <b>{'да' if enabled else 'нет'}</b>\n"
    msg += "<b>Время открытия:</b>\n"
    for day, t in open_times.items():
        msg += f"{day.title()}: {t or '-'}\n"
    msg += "<b>Перерывы:</b>\n"
    for day, br in breaks.items():
        msg += f"{day.title()}: {', '.join(br) if br else '-'}\n"
    await update.message.reply_text(msg, parse_mode="HTML")

async def enable_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Получена команда /enable_schedule от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await update.message.reply_text("Нет доступа.")
        return
    cfg = load_config()
    cfg["schedule_enabled"] = True
    save_config(cfg)
    await update.message.reply_text("Расписание <b>включено</b>.", parse_mode="HTML")

async def disable_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Получена команда /disable_schedule от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await update.message.reply_text("Нет доступа.")
        return
    cfg = load_config()
    cfg["schedule_enabled"] = False
    save_config(cfg)
    await update.message.reply_text("Расписание <b>отключено</b>.", parse_mode="HTML")

async def open_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Получена команда /open от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await update.message.reply_text("Нет доступа.")
        return
    lock_id = TTLOCK_LOCK_ID
    if not lock_id:
        await update.message.reply_text("lock_id не задан в .env!")
        return
    token = ttlock_api.get_token(logger)
    if not token:
        await update.message.reply_text("Ошибка получения токена TTLock.")
        return
    resp = ttlock_api.unlock_lock(token, lock_id, logger)
    if resp.get("errcode") == 0:
        await update.message.reply_text(f"Замок <b>открыт</b>! (попытка {resp.get('attempt')})", parse_mode="HTML")
    else:
        await update.message.reply_text(f"Ошибка открытия замка: {resp.get('errmsg')} (код {resp.get('errcode')})", parse_mode="HTML")

async def close_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Получена команда /close от chat_id={update.effective_chat.id}")
    if not is_authorized(update):
        await update.message.reply_text("Нет доступа.")
        return
    lock_id = TTLOCK_LOCK_ID
    if not lock_id:
        await update.message.reply_text("lock_id не задан в .env!")
        return
    token = ttlock_api.get_token(logger)
    if not token:
        await update.message.reply_text("Ошибка получения токена TTLock.")
        return
    resp = ttlock_api.lock_lock(token, lock_id, logger)
    if resp.get("errcode") == 0:
        await update.message.reply_text(f"Замок <b>закрыт</b>! (попытка {resp.get('attempt')})", parse_mode="HTML")
    else:
        await update.message.reply_text(f"Ошибка закрытия замка: {resp.get('errmsg')} (код {resp.get('errcode')})", parse_mode="HTML")

async def settimezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Нет доступа.")
        return ConversationHandler.END
    await update.message.reply_text(
        "Введите новый часовой пояс (например, Europe/Moscow, Asia/Novosibirsk).\nСписок: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
    )
    return SET_TIMEZONE

async def settimezone_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tz = update.message.text.strip()
    try:
        pytz.timezone(tz)
    except Exception:
        await update.message.reply_text("Некорректный часовой пояс. Попробуйте ещё раз.")
        return SET_TIMEZONE
    cfg = load_config()
    cfg["timezone"] = tz
    save_config(cfg)
    await update.message.reply_text(f"Часовой пояс изменён на <code>{tz}</code>.", parse_mode="HTML")
    return ConversationHandler.END

async def settime_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Нет доступа.")
        return ConversationHandler.END
    kb = [[d] for d in DAYS_RU]
    await update.message.reply_text(
        "Выберите день недели:",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
    )
    return SETTIME_DAY

async def settime_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == "/cancel":
        await update.message.reply_text("Ввод отменён.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if text.lower() == "/back":
        return await settime_start(update, context)
    if text not in DAYS_RU:
        await update.message.reply_text("Пожалуйста, выберите день из списка или /cancel.")
        return SETTIME_DAY
    context.user_data['settime_day'] = DAY_MAP[text]
    await update.message.reply_text(
        f"Введите время открытия для {text} (например, 09:00) или 'off' для отключения открытия в этот день.\nКоманды: /back — назад, /cancel — отмена.",
        reply_markup=ReplyKeyboardRemove()
    )
    return SETTIME_VALUE

async def settime_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if val.lower() == "/cancel":
        await update.message.reply_text("Ввод отменён.")
        return ConversationHandler.END
    if val.lower() == "/back":
        return await settime_start(update, context)
    day = context.user_data.get('settime_day')
    if val.lower() == "off":
        new_time = None
    else:
        # Проверка формата времени
        import re
        if not re.match(r"^\d{2}:\d{2}$", val):
            await update.message.reply_text("Некорректный формат времени. Введите в формате ЧЧ:ММ, например 09:00, или 'off'.")
            return SETTIME_VALUE
        new_time = val
    cfg = load_config()
    if "open_times" not in cfg:
        cfg["open_times"] = {}
    cfg["open_times"][day] = new_time
    save_config(cfg)
    day_ru = DAY_MAP_INV[day]
    await update.message.reply_text(f"Время открытия для {day_ru} установлено: {new_time or 'отключено'}.")
    # Предложить выбрать другой день или завершить
    kb = [[d] for d in DAYS_RU]
    await update.message.reply_text(
        "Хотите изменить время для другого дня? Выберите день или /cancel.",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
    )
    return SETTIME_DAY

async def setbreak_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Нет доступа.")
        return ConversationHandler.END
    kb = [[d] for d in DAYS_RU]
    await update.message.reply_text(
        "Выберите день недели для настройки перерывов:",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
    )
    return SETBREAK_DAY

async def setbreak_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == "/cancel":
        await update.message.reply_text("Ввод отменён.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if text.lower() == "/back":
        return await setbreak_start(update, context)
    if text not in DAYS_RU:
        await update.message.reply_text("Пожалуйста, выберите день из списка или /cancel.")
        return SETBREAK_DAY
    context.user_data['setbreak_day'] = DAY_MAP[text]
    cfg = load_config()
    br = cfg.get("breaks", {}).get(DAY_MAP[text], [])
    msg = f"Текущие перерывы для {text}:\n"
    if br:
        for i, interval in enumerate(br, 1):
            msg += f"{i}. {interval}\n"
    else:
        msg += "Нет перерывов.\n"
    msg += "\nЧто хотите сделать?\nДобавить — /add\nУдалить — /del\nНазад — /back\nОтмена — /cancel"
    await update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())
    return SETBREAK_ACTION

async def setbreak_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text == "/cancel":
        await update.message.reply_text("Ввод отменён.")
        return ConversationHandler.END
    if text == "/back":
        return await setbreak_start(update, context)
    if text == "/add":
        await update.message.reply_text("Введите интервал перерыва в формате ЧЧ:ММ-ЧЧ:ММ (например, 13:00-14:00).\n/back — назад, /cancel — отмена.")
        return SETBREAK_ADD
    if text == "/del":
        cfg = load_config()
        day = context.user_data['setbreak_day']
        br = cfg.get("breaks", {}).get(day, [])
        if not br:
            await update.message.reply_text("Нет перерывов для удаления. /back — назад.")
            return SETBREAK_ACTION
        msg = "Выберите номер перерыва для удаления:\n"
        for i, interval in enumerate(br, 1):
            msg += f"{i}. {interval}\n"
        await update.message.reply_text(msg)
        return SETBREAK_DEL
    await update.message.reply_text("Пожалуйста, выберите действие: /add, /del, /back, /cancel.")
    return SETBREAK_ACTION

async def setbreak_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if val.lower() == "/cancel":
        await update.message.reply_text("Ввод отменён.")
        return ConversationHandler.END
    if val.lower() == "/back":
        return await setbreak_day(update, context)
    import re
    if not re.match(r"^\d{2}:\d{2}-\d{2}:\d{2}$", val):
        await update.message.reply_text("Некорректный формат. Введите в формате ЧЧ:ММ-ЧЧ:ММ, например 13:00-14:00.")
        return SETBREAK_ADD
    day = context.user_data['setbreak_day']
    cfg = load_config()
    if "breaks" not in cfg:
        cfg["breaks"] = {}
    if day not in cfg["breaks"]:
        cfg["breaks"][day] = []
    cfg["breaks"][day].append(val)
    save_config(cfg)
    await update.message.reply_text(f"Перерыв {val} добавлен.")
    return await setbreak_day(update, context)

async def setbreak_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if val.lower() == "/cancel":
        await update.message.reply_text("Ввод отменён.")
        return ConversationHandler.END
    if val.lower() == "/back":
        return await setbreak_day(update, context)
    try:
        idx = int(val) - 1
    except Exception:
        await update.message.reply_text("Введите номер перерыва для удаления или /back.")
        return SETBREAK_DEL
    day = context.user_data['setbreak_day']
    cfg = load_config()
    br = cfg.get("breaks", {}).get(day, [])
    if not (0 <= idx < len(br)):
        await update.message.reply_text("Некорректный номер. /back — назад.")
        return SETBREAK_DEL
    removed = br.pop(idx)
    cfg["breaks"][day] = br
    save_config(cfg)
    await update.message.reply_text(f"Перерыв {removed} удалён.")
    return await setbreak_day(update, context)

def main():
    """
    Точка входа: запускает Telegram-бота и обработчики команд.
    """
    if DEBUG:
        print("[DEBUG] Запуск Telegram-бота...")
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
        entry_points=[CommandHandler('settime', settime_start)],
        states={
            SETTIME_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, settime_day)],
            SETTIME_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settime_value)],
        },
        fallbacks=[]
    )
    setbreak_conv = ConversationHandler(
        entry_points=[CommandHandler('setbreak', setbreak_start)],
        states={
            SETBREAK_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbreak_day)],
            SETBREAK_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbreak_action)],
            SETBREAK_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbreak_add)],
            SETBREAK_DEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbreak_del)],
        },
        fallbacks=[]
    )
    app.add_handler(CommandHandler('start', start))
    app.add_handler(conv_handler)
    app.add_handler(tz_conv)
    app.add_handler(settime_conv)
    app.add_handler(setbreak_conv)
    app.add_handler(CommandHandler('status', status))
    app.add_handler(CommandHandler('enable_schedule', enable_schedule))
    app.add_handler(CommandHandler('disable_schedule', disable_schedule))
    app.add_handler(CommandHandler('open', open_lock))
    app.add_handler(CommandHandler('close', close_lock))
    logger.info("Telegram-бот успешно запущен и готов к работе.")
    app.run_polling()

if __name__ == '__main__':
    main() 