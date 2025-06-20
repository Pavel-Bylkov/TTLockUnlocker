import requests
import traceback
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header

logger = logging.getLogger(__name__)

def send_telegram_message(token, chat_id, text, logger=None):
    """
    Отправляет сообщение в Telegram.
    
    Args:
        token: Токен бота
        chat_id: ID чата для отправки
        text: Текст сообщения
        logger: Логгер для записи ошибок (опционально)
    """
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


def is_authorized(update, authorized_chat_id):
    """
    Проверяет, авторизован ли пользователь.
    
    Args:
        update: Объект обновления Telegram
        authorized_chat_id: Разрешенный ID чата
    
    Returns:
        bool: True если пользователь авторизован, False в противном случае
    """
    return str(update.effective_chat.id) == str(authorized_chat_id)


def log_exception(logger):
    """
    Логирует текущий стек вызовов.
    
    Args:
        logger: Логгер для записи ошибки
    """
    logger.error(traceback.format_exc())


def send_email_notification(subject: str, body: str):
    """
    Отправляет email-уведомление.
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