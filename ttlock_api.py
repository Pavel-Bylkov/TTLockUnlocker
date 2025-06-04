import os
import requests
import time
import hashlib
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TTLOCK_CLIENT_ID = os.getenv("TTLOCK_CLIENT_ID")
TTLOCK_CLIENT_SECRET = os.getenv("TTLOCK_CLIENT_SECRET")
TTLOCK_USERNAME = os.getenv("TTLOCK_USERNAME")
TTLOCK_PASSWORD = os.getenv("TTLOCK_PASSWORD")
DEBUG = os.getenv("DEBUG", "0").lower() in ("1", "true", "yes")


def get_token(logger=None):
    """
    Получает токен доступа для работы с TTLock API.
    
    :param logger: Логгер для записи информации (опционально).
    :return: access_token или None в случае ошибки.
    """
    url = "https://euapi.ttlock.com/oauth2/token"
    password_md5 = hashlib.md5(TTLOCK_PASSWORD.encode()).hexdigest()
    data = {
        "username": TTLOCK_USERNAME,
        "password": password_md5,
        "clientId": TTLOCK_CLIENT_ID,
        "clientSecret": TTLOCK_CLIENT_SECRET
    }
    resp = requests.post(url, data=data, timeout=10, verify=False)
    if logger:
        logger.info(f"TTLock get_token response: {resp.text}")
    if DEBUG:
        print(f"[DEBUG] get_token: {resp.text}")
    return resp.json().get("access_token")


def unlock_lock(token, lock_id, logger=None, send_telegram=None):
    """
    Открывает замок с указанным идентификатором.
    
    :param token: access_token для доступа к API.
    :param lock_id: Идентификатор замка, который нужно открыть.
    :param logger: Логгер для записи информации (опционально).
    :param send_telegram: Функция для отправки сообщений в Telegram (опционально).
    :return: Результат операции (успех или ошибка).
    """
    url = "https://euapi.ttlock.com/v3/lock/unlock"
    data = {
        "clientId": TTLOCK_CLIENT_ID,
        "lockId": lock_id,
        "accessToken": token,
        "date": int(time.time() * 1000)
    }
    intervals = [0, 30, 60]
    for attempt in range(3):
        if attempt > 0:
            delay = intervals[attempt]
            msg = f"[RETRY] Ожидание {delay} сек перед повторной попыткой открытия (попытка {attempt+1}/3)"
            if logger:
                logger.info(msg)
            if DEBUG:
                print(msg)
            time.sleep(delay)
        try:
            response = requests.post(url, data=data, verify=False)
            if DEBUG:
                print(f"[DEBUG] unlock_lock (попытка {attempt+1}): {response.text}")
            if logger:
                logger.info(f"Ответ TTLock (unlock, попытка {attempt+1}): {response.text}")
            response_data = response.json()
            if "errcode" in response_data and response_data["errcode"] == 0:
                msg = f"✅ Замок {lock_id} открыт успешно (попытка {attempt+1})"
                if logger:
                    logger.info(msg)
                if DEBUG:
                    print(msg)
                if send_telegram:
                    send_telegram(msg)
                return True
            else:
                msg = f"Ошибка при открытии замка {lock_id} (попытка {attempt+1}): {response_data.get('errmsg', 'Unknown error')} (Код: {response_data.get('errcode')})"
                if logger:
                    logger.error(msg)
                if DEBUG:
                    print(msg)
                if send_telegram:
                    send_telegram(f"❗️ <b>Ошибка открытия замка</b>\n{msg}")
        except Exception as e:
            msg = f"Ошибка при запросе открытия замка {lock_id} (попытка {attempt+1}): {str(e)}"
            if logger:
                logger.error(msg)
            if DEBUG:
                print(msg)
            if send_telegram:
                send_telegram(f"❗️ <b>Ошибка открытия замка</b>\n{msg}")
    return False


def lock_lock(token, lock_id, logger=None, send_telegram=None):
    """
    Закрывает замок с указанным идентификатором.
    
    :param token: access_token для доступа к API.
    :param lock_id: Идентификатор замка, который нужно закрыть.
    :param logger: Логгер для записи информации (опционально).
    :param send_telegram: Функция для отправки сообщений в Telegram (опционально).
    :return: Результат операции (успех или ошибка).
    """
    url = "https://euapi.ttlock.com/v3/lock/lock"
    data = {
        "clientId": TTLOCK_CLIENT_ID,
        "lockId": lock_id,
        "accessToken": token,
        "date": int(time.time() * 1000)
    }
    intervals = [0, 30, 60]
    for attempt in range(3):
        if attempt > 0:
            delay = intervals[attempt]
            msg = f"[RETRY] Ожидание {delay} сек перед повторной попыткой закрытия (попытка {attempt+1}/3)"
            if logger:
                logger.info(msg)
            if DEBUG:
                print(msg)
            time.sleep(delay)
        try:
            response = requests.post(url, data=data, verify=False)
            if DEBUG:
                print(f"[DEBUG] lock_lock (попытка {attempt+1}): {response.text}")
            if logger:
                logger.info(f"Ответ TTLock (lock, попытка {attempt+1}): {response.text}")
            response_data = response.json()
            if "errcode" in response_data and response_data["errcode"] == 0:
                msg = f"✅ Замок {lock_id} закрыт успешно (попытка {attempt+1})"
                if logger:
                    logger.info(msg)
                if DEBUG:
                    print(msg)
                if send_telegram:
                    send_telegram(msg)
                return True
            else:
                msg = f"Ошибка при закрытии замка {lock_id} (попытка {attempt+1}): {response_data.get('errmsg', 'Unknown error')} (Код: {response_data.get('errcode')})"
                if logger:
                    logger.error(msg)
                if DEBUG:
                    print(msg)
                if send_telegram:
                    send_telegram(f"❗️ <b>Ошибка закрытия замка</b>\n{msg}")
        except Exception as e:
            msg = f"Ошибка при запросе закрытия замка {lock_id} (попытка {attempt+1}): {str(e)}"
            if logger:
                logger.error(msg)
            if DEBUG:
                print(msg)
            if send_telegram:
                send_telegram(f"❗️ <b>Ошибка закрытия замка</b>\n{msg}")
    return False


def list_locks(token, logger=None):
    """
    Запрашивает список замков, доступных для данного access_token (только для владельца).
    
    :param token: access_token.
    :param logger: Логгер для записи информации (опционально).
    :return: Список замков (list) или пустой список.
    """
    url = "https://euapi.ttlock.com/v3/lock/list"
    data = {
        "clientId": TTLOCK_CLIENT_ID,
        "accessToken": token,
        "pageNo": 1,
        "pageSize": 20,
        "date": int(time.time() * 1000)
    }
    try:
        response = requests.post(url, data=data, verify=False)
        if logger:
            logger.info(f"Ответ TTLock (list_locks): {response.text}")
        if DEBUG:
            print(f"[DEBUG] list_locks: {response.text}")
        response_data = response.json()
        return response_data.get("list", [])
    except Exception as e:
        msg = f"Ошибка получения списка замков: {str(e)}"
        if logger:
            logger.error(msg)
        if DEBUG:
            print(msg)
        return []


def get_lock_status(token, lock_id, logger=None):
    """
    Получает статус замка с указанным идентификатором.
    
    :param token: access_token для доступа к API.
    :param lock_id: Идентификатор замка, статус которого нужно получить.
    :param logger: Логгер для записи информации (опционально).
    :return: Статус замка или None в случае ошибки.
    """
    url = "https://euapi.ttlock.com/v3/lock/queryStatus"
    data = {
        "clientId": TTLOCK_CLIENT_ID,
        "accessToken": token,
        "lockId": lock_id,
        "date": int(time.time() * 1000)
    }
    try:
        response = requests.post(url, data=data, verify=False)
        if logger:
            logger.info(f"Ответ TTLock (get_lock_status): {response.text}")
        if DEBUG:
            print(f"[DEBUG] get_lock_status: {response.text}")
        response_data = response.json()
        if "errcode" in response_data and response_data["errcode"] == 0:
            return response_data.get("lockStatus")
        else:
            return None
    except Exception as e:
        if logger:
            logger.error(f"Ошибка получения статуса замка: {str(e)}")
        if DEBUG:
            print(f"Ошибка получения статуса замка: {str(e)}")
        return None 