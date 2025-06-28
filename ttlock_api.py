import os
import requests
import time
import hashlib
import urllib3
import pytz
from datetime import datetime
import json
import logging
from typing import Optional, Dict, List, Union, Callable

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TTLOCK_CLIENT_ID = os.getenv("TTLOCK_CLIENT_ID")
TTLOCK_CLIENT_SECRET = os.getenv("TTLOCK_CLIENT_SECRET")
TTLOCK_USERNAME = os.getenv("TTLOCK_USERNAME")
TTLOCK_PASSWORD = os.getenv("TTLOCK_PASSWORD")
DEBUG = os.getenv("DEBUG", "0").lower() in ("1", "true", "yes")
CONFIG_PATH = os.getenv("CONFIG_PATH", "config.json")


def get_token(logger: Optional[logging.Logger] = None) -> Optional[str]:
    """
    Получает токен доступа для работы с TTLock API.
    
    Параметры:
        logger: логгер для записи информации (опционально)
    
    Возвращает:
        access_token (str) или None в случае ошибки
    """
    url = "https://euapi.ttlock.com/oauth2/token"
    password_md5 = hashlib.md5(TTLOCK_PASSWORD.encode()).hexdigest()
    data = {
        "username": TTLOCK_USERNAME,
        "password": password_md5,
        "clientId": TTLOCK_CLIENT_ID,
        "clientSecret": TTLOCK_CLIENT_SECRET
    }
    try:
        resp = requests.post(url, data=data, timeout=10, verify=False)
        if logger:
            logger.info(f"TTLock get_token response: {resp.text}")
        return resp.json().get("access_token")
    except Exception as e:
        msg = f"Ошибка получения токена: {str(e)}"
        if logger:
            logger.error(msg)
        return None


def unlock_lock(token: str, lock_id: str, logger: Optional[logging.Logger] = None, 
                send_telegram: Optional[Callable] = None) -> Dict[str, Union[int, str, bool]]:
    """
    Пытается открыть замок с помощью TTLock API.
    
    Параметры:
        token: access_token
        lock_id: идентификатор замка
        logger: логгер (опционально)
        send_telegram: функция для отправки уведомлений (опционально)
    
    Возвращает:
        dict с результатом операции
    """
    url = "https://euapi.ttlock.com/v3/lock/unlock"
    data = {
        "clientId": TTLOCK_CLIENT_ID,
        "lockId": lock_id,
        "accessToken": token,
        "date": int(time.time() * 1000)
    }
    
    try:
        response = requests.post(url, data=data, verify=False)
        if logger:
            logger.info(f"Ответ TTLock (unlock): {response.text}")
        response_data = response.json()
        
        if "errcode" in response_data and response_data["errcode"] == 0:
            msg = f"✅ Замок {lock_id} открыт успешно"
            if logger:
                logger.info(msg)
            if send_telegram:
                send_telegram(msg)
            return {"errcode": 0, "errmsg": "OK", "success": True}
        else:
            errmsg = response_data.get('errmsg', 'Неизвестная ошибка')
            errcode = response_data.get('errcode', -1)
            msg = f"Ошибка при открытии замка {lock_id}: {errmsg} (Код: {errcode})"
            if logger:
                logger.error(msg)
            if send_telegram:
                send_telegram(f"❗️ <b>Ошибка открытия замка</b>\n{msg}")
            return {"errcode": errcode, "errmsg": errmsg, "success": False}
            
    except Exception as e:
        msg = f"Ошибка при запросе открытия замка {lock_id}: {str(e)}"
        if logger:
            logger.error(msg)
        if send_telegram:
            send_telegram(f"❗️ <b>Ошибка открытия замка</b>\n{msg}")
        return {"errcode": -1, "errmsg": str(e), "success": False}


def lock_lock(token: str, lock_id: str, logger: Optional[logging.Logger] = None,
             send_telegram: Optional[Callable] = None) -> Dict[str, Union[int, str, bool]]:
    """
    Пытается закрыть замок с помощью TTLock API.
    
    Параметры:
        token: access_token
        lock_id: идентификатор замка
        logger: логгер (опционально)
        send_telegram: функция для отправки уведомлений (опционально)
    
    Возвращает:
        dict с результатом операции
    """
    url = "https://euapi.ttlock.com/v3/lock/lock"
    data = {
        "clientId": TTLOCK_CLIENT_ID,
        "lockId": lock_id,
        "accessToken": token,
        "date": int(time.time() * 1000)
    }
    
    try:
        response = requests.post(url, data=data, verify=False)
        if logger:
            logger.info(f"Ответ TTLock (lock): {response.text}")
        response_data = response.json()
        
        if "errcode" in response_data and response_data["errcode"] == 0:
            msg = f"✅ Замок {lock_id} закрыт успешно"
            if logger:
                logger.info(msg)
            if send_telegram:
                send_telegram(msg)
            return {"errcode": 0, "errmsg": "OK", "success": True}
        else:
            errmsg = response_data.get('errmsg', 'Неизвестная ошибка')
            errcode = response_data.get('errcode', -1)
            msg = f"Ошибка при закрытии замка {lock_id}: {errmsg} (Код: {errcode})"
            if logger:
                logger.error(msg)
            if send_telegram:
                send_telegram(f"❗️ <b>Ошибка закрытия замка</b>\n{msg}")
            return {"errcode": errcode, "errmsg": errmsg, "success": False}
            
    except Exception as e:
        msg = f"Ошибка при запросе закрытия замка {lock_id}: {str(e)}"
        if logger:
            logger.error(msg)
        if send_telegram:
            send_telegram(f"❗️ <b>Ошибка закрытия замка</b>\n{msg}")
        return {"errcode": -1, "errmsg": str(e), "success": False}


def list_locks(token: str, logger: Optional[logging.Logger] = None) -> List[Dict]:
    """
    Запрашивает список замков, доступных для данного access_token (только для владельца).
    
    Args:
        token: access_token
        logger: Логгер для записи информации (опционально)
    
    Returns:
        list: Список замков или пустой список в случае ошибки
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
        response = requests.get(url, params=data, verify=False)
        if logger:
            logger.info(f"Ответ TTLock (list_locks): {response.text}")
        
        response_data = response.json()
        
        if "errcode" in response_data and response_data["errcode"] != 0:
            msg = f"Ошибка при запросе списка замков: {response_data.get('errmsg', 'Unknown error')} (Код: {response_data.get('errcode')})"
            if logger:
                logger.error(msg)
            return []
            
        return response_data.get("list", [])
        
    except Exception as e:
        msg = f"Ошибка получения списка замков: {str(e)}"
        if logger:
            logger.error(msg)
        return []


def get_lock_status_details(token: str, lock_id: str, logger: Optional[logging.Logger] = None) -> Dict[str, Optional[Union[str, int]]]:
    """
    Получает детальную информацию о состоянии замка.

    Args:
        token: access_token для доступа к API.
        lock_id: Идентификатор замка.
        logger: Логгер для записи информации.

    Returns:
        Словарь с деталями:
        {
            "battery": int (уровень заряда) или None,
            "status": "Online" | "Offline" или None
        }
    """
    details = {
        "battery": None,
        "status": None
    }

    # 1. Получаем уровень заряда и статус сети
    try:
        url_detail = "https://euapi.ttlock.com/v3/lock/detail"
        data_detail = {
            "clientId": TTLOCK_CLIENT_ID,
            "accessToken": token,
            "lockId": lock_id,
            "date": int(time.time() * 1000)
        }
        response = requests.get(url_detail, params=data_detail, verify=False, timeout=10)
        response_data = response.json()
        if logger:
            logger.debug(f"Ответ lock/detail: {response.text}")

        if "errcode" not in response_data:
            details["battery"] = response_data.get("electricQuantity")
            # Для замков с WiFi-модулем, 1 = Online
            network_status = response_data.get("isOnline")
            details["status"] = "Online" if network_status == 1 else "Offline"
        else:
            if logger:
                logger.error(f"Ошибка получения деталей замка: {response_data.get('errmsg', 'Unknown error')}")
    except Exception as e:
        if logger:
            logger.error(f"Исключение при запросе деталей замка: {e}")

    return details


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
        response_data = response.json()
        if "errcode" in response_data and response_data["errcode"] == 0:
            return response_data.get("lockStatus")
        else:
            return None
    except Exception as e:
        if logger:
            logger.error(f"Ошибка получения статуса замка: {str(e)}")
        return None


def get_timezone(config_path: str = CONFIG_PATH) -> str:
    """
    Получает часовой пояс из конфигурации.

    Args:
        config_path: Путь к файлу конфигурации

    Returns:
        str: Название часового пояса
    """
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return config.get('timezone', 'Europe/Moscow')
    except Exception:
        return 'Europe/Moscow'


def get_now(config_path: str = CONFIG_PATH) -> datetime:
    """
    Получает текущее время в указанном часовом поясе.

    Args:
        config_path: Путь к файлу конфигурации

    Returns:
        datetime: Текущее время в указанном часовом поясе
    """
    return datetime.now(pytz.timezone(get_timezone(config_path)))


class TZFormatter(logging.Formatter):
    """
    Форматтер для логов с учетом часового пояса.
    """
    def __init__(self, fmt: str, datefmt: str, config_path: str = CONFIG_PATH):
        """
        Инициализирует форматтер.

        Args:
            fmt: Формат сообщения
            datefmt: Формат даты
            config_path: Путь к файлу конфигурации
        """
        super().__init__(fmt, datefmt)
        self.config_path = config_path

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
        """
        Форматирует время записи лога.

        Args:
            record: Запись лога
            datefmt: Формат даты (опционально)

        Returns:
            str: Отформатированное время
        """
        dt = datetime.fromtimestamp(record.created)
        dt = pytz.timezone(get_timezone(self.config_path)).localize(dt)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
