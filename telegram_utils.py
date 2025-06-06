import requests
import traceback

def send_telegram_message(token, chat_id, text, logger=None):
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
    return str(update.effective_chat.id) == str(authorized_chat_id)


def log_exception(logger):
    import traceback
    logger.error(traceback.format_exc()) 