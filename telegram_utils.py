import requests
import traceback
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import json

logger = logging.getLogger(__name__)

def send_telegram_message(token, chat_id=None, text=None, logger=None):
    """
    Отправляет сообщение в Telegram.

    Параметры:
        token: токен бота
        chat_id: ID чата для отправки (если None, читается из TELEGRAM_CHAT_ID)
        text: текст сообщения
        logger: логгер для записи ошибок (опционально)
    """
    # Если chat_id не передан, читаем из переменных окружения
    if chat_id is None:
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not chat_id:
            if logger:
                logger.error("TELEGRAM_CHAT_ID не задан в переменных окружения")
            return False


    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, data=payload, timeout=10)
        if resp.status_code != 200 and logger:
            logger.warning(f"Ошибка отправки Telegram: {resp.text}")
    except Exception as e:
        if logger:
            logger.warning(f"Ошибка отправки Telegram: {str(e)}\n{traceback.format_exc()}")


def log_message(logger, level, message):
    """
    Унифицированная функция для логирования сообщений.
    
    Параметры:
        logger: объект логгера
        level: строка ('ERROR', 'INFO', 'DEBUG')
        message: текст сообщения
    """
    if level == "ERROR":
        print(f"[ERROR] {message}")
        logger.error(message)
    elif level == "INFO":
        print(f"[INFO] {message}")
        logger.info(message)
    elif level == "DEBUG":
        print(f"[DEBUG] {message}")
        logger.debug(message)


def load_config(config_path, logger=None, default=None):
    """
    Загружает конфиг из файла. Возвращает default при ошибке.
    
    Параметры:
        config_path: путь к файлу конфигурации
        logger: логгер (опционально)
        default: значения по умолчанию (опционально)
    """
    if default is None:
        default = {}
    try:
        if logger:
            log_message(logger, "DEBUG", f"Чтение конфигурации из {config_path}")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            return config
    except Exception as e:
        if logger:
            log_message(logger, "ERROR", f"Ошибка чтения конфигурации: {e}")
        return default


def save_config(config, config_path, logger=None):
    """
    Сохраняет конфиг в файл.
    
    Параметры:
        config: словарь конфигурации
        config_path: путь к файлу
        logger: логгер (опционально)
    """
    try:
        if logger:
            log_message(logger, "DEBUG", f"Сохранение конфигурации в {config_path}")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        if logger:
            log_message(logger, "ERROR", f"Ошибка сохранения конфигурации: {e}")
        raise


def is_authorized(update, authorized_chat_id):
    """
    Проверяет, авторизован ли пользователь.
    
    Параметры:
        update: объект обновления Telegram
        authorized_chat_id: разрешённый ID чата
    
    Возвращает:
        bool: True если пользователь авторизован, False в противном случае
    """
    return str(update.effective_chat.id) == str(authorized_chat_id)


def log_exception(logger):
    """
    Логирует текущий стек вызовов.
    
    Параметры:
        logger: логгер для записи ошибки
    """
    logger.error(traceback.format_exc())


def send_email_notification(subject: str, body: str):
    """
    Отправляет email-уведомление.
    
    Параметры:
        subject: тема письма
        body: текст письма
    
    Возвращает:
        True — если письмо отправлено, иначе False
    """
    EMAIL_TO = os.getenv("EMAIL_TO")
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = os.getenv("SMTP_PORT")
    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

    if not all([EMAIL_TO, SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD]):
        logger.warning("Параметры для отправки email не настроены. Уведомление не отправлено.")
        # Возвращаем False, чтобы вызывающая функция знала о неудаче
        return False

    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = SMTP_USER
    msg['To'] = EMAIL_TO

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, int(SMTP_PORT)) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())
        logger.info(f"Email-уведомление отправлено на {EMAIL_TO}.")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки email: {e}")
        return False 
