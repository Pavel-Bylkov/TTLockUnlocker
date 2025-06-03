"""
Telegram-бот для управления рассылкой уведомлений TTLock и смены chat_id через Docker.
Используется совместно с auto_unlocker.py. Все параметры берутся из .env.

Для отладки можно установить переменную окружения DEBUG=1 (или true/True) — тогда будет подробный вывод в консоль.
"""
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import os
import docker
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Уровень отладки
DEBUG = os.getenv('DEBUG', '0').lower() in ('1', 'true', 'yes')

# Настройка логирования
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    filename='logs/telegram_bot.log',
    format='%(asctime)s %(levelname)s: %(message)s',
    level=logging.INFO
)

CODEWORD = os.getenv('TELEGRAM_CODEWORD', 'secretword')
# Определяем путь к .env: сначала из ENV_PATH, иначе ./env
ENV_PATH = os.getenv('ENV_PATH') or './.env'
if DEBUG:
    print(f"[DEBUG] Используется путь к .env: {ENV_PATH}")
AUTO_UNLOCKER_CONTAINER = os.getenv('AUTO_UNLOCKER_CONTAINER', 'auto_unlocker_1')
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

ASK_CODEWORD, CONFIRM_CHANGE = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает команду /start. Приветствие и краткая инструкция.
    """
    if DEBUG:
        print("[DEBUG] /start вызван")
    await update.message.reply_text("Привет! Я бот для управления рассылкой уведомлений TTLock.\nКоманда /setchat — сменить получателя уведомлений.")

async def setchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Запрашивает у пользователя кодовое слово для смены chat_id.
    """
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
    app.add_handler(CommandHandler('start', start))
    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == '__main__':
    main() 