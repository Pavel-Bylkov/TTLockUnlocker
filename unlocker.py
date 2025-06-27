"""
Ручной скрипт для экспериментов с TTLock API.
Позволяет получать токен, список замков, открывать/закрывать замок, получать статус.
Используйте только для тестов и отладки! Для автоматизации используйте auto_unlocker.py.
"""
import requests
import json
import time
import hashlib
import urllib3
import os
from dotenv import load_dotenv
import ttlock_api

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Определяем путь к .env: сначала из ENV_PATH, иначе env/.env
ENV_PATH = os.getenv('ENV_PATH') or 'env/.env'
# Загрузка переменных окружения
load_dotenv(ENV_PATH)

# TTLock API параметры из .env
client_id = os.getenv("TTLOCK_CLIENT_ID")
client_secret = os.getenv("TTLOCK_CLIENT_SECRET")
username = os.getenv("TTLOCK_USERNAME")
password = os.getenv("TTLOCK_PASSWORD")
lock_id = os.getenv("TTLOCK_LOCK_ID")

MAX_RETRIES = 3
RETRY_DELAY = 2  # секунд

def init():
    """
    Инициализация модуля, проверка переменных окружения.
    """
    if not all([client_id, client_secret, username, password]):
        raise RuntimeError("Не заданы все переменные окружения TTLOCK_CLIENT_ID, TTLOCK_CLIENT_SECRET, TTLOCK_USERNAME, TTLOCK_PASSWORD. Проверьте .env файл!")


def debug_request(name, url, data, response):
    """
    Печатает подробную отладочную информацию о каждом HTTP-запросе и ответе.
    """
    print(f"\n[DEBUG] {name}")
    print(f"URL: {url}")
    print(f"Параметры запроса: {json.dumps(data, ensure_ascii=False)}")
    print(f"Статус ответа: {response.status_code}")
    try:
        print(f"Тело ответа: {json.dumps(response.json(), ensure_ascii=False)}")
    except Exception:
        print(f"Тело ответа (не JSON): {response.text}")


def get_lock_status(token, lock_id):
    """Пытается получить статус замка (открыт/закрыт), если поддерживается моделью и есть шлюз."""
    url = "https://euapi.ttlock.com/v3/lock/queryStatus"
    data = {
        "clientId": client_id,
        "accessToken": token,
        "lockId": lock_id,
        "date": int(time.time() * 1000)
    }
    try:
        response = requests.post(url, data=data, verify=False)
        debug_request("Статус замка", url, data, response)
        response_data = response.json()
        if "errcode" in response_data and response_data["errcode"] == 0:
            status = response_data.get("lockStatus")
            if status == 1:
                print("Статус замка: ЗАКРЫТ")
            elif status == 2:
                print("Статус замка: ОТКРЫТ")
            else:
                print(f"Статус замка: Неизвестно ({status})")
            return status
        else:
            print(f"Ошибка получения статуса: {response_data.get('errmsg', 'Unknown error')}")
            return None
    except Exception as e:
        print(f"Ошибка при получении статуса замка: {str(e)}")
        return None


def lock_lock(token, lock_id):
    """
    Пытается закрыть замок с указанным lock_id через облако.
    """
    url = "https://euapi.ttlock.com/v3/lock/lock"
    data = {
        "clientId": client_id,
        "lockId": lock_id,
        "accessToken": token,
        "date": int(time.time() * 1000)
    }
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(url, data=data, verify=False)
            debug_request("Закрытие замка", url, data, response)
            response_data = response.json()
            if "errcode" in response_data:
                if response_data["errcode"] == 0:
                    print("Замок закрыт успешно")
                    return True
                elif response_data["errcode"] == -3037:
                    if attempt < MAX_RETRIES - 1:
                        print(f"Замок занят. Повтор через {RETRY_DELAY} сек... (Попытка {attempt + 1}/{MAX_RETRIES})")
                        time.sleep(RETRY_DELAY)
                        continue
                    else:
                        print("Замок занят. Достигнут лимит попыток. Попробуйте позже.")
                        return False
                else:
                    print(f"Ошибка при закрытии: {response_data.get('errmsg', 'Неизвестная ошибка')} (Код: {response_data['errcode']})")
                    return False
            else:
                print("Неожиданный формат ответа:", response_data)
                return False
        except Exception as e:
            print(f"Ошибка при запросе закрытия: {str(e)}")
            return False
    return False


def get_token():
    """
    Получает access_token для TTLock Cloud API по логину/паролю владельца аккаунта.
    """
    url = "https://euapi.ttlock.com/oauth2/token"
    password_md5 = hashlib.md5(password.encode()).hexdigest()
    data = {
        "username": username,
        "password": password_md5,
        "clientId": client_id,
        "clientSecret": client_secret
    }
    response = requests.post(url, data=data, verify=False)
    debug_request("Получение токена", url, data, response)
    response_data = response.json()
    if response.status_code == 200 and "access_token" in response_data:
        print("Токен получен успешно")
        return response_data["access_token"]
    else:
        print("Ошибка: ", response_data)
        return None


def list_locks(token):
    """
    Запрашивает список замков, доступных для данного access_token (только для владельца).
    """
    url = "https://euapi.ttlock.com/v3/lock/list"
    data = {
        "clientId": client_id,
        "accessToken": token,
        "pageNo": 1,
        "pageSize": 20,
        "date": int(time.time() * 1000)
    }
    try:
        response = requests.post(url, data=data, verify=False)
        debug_request("Список замков", url, data, response)
        response_data = response.json()
        if "errcode" in response_data:
            if response_data["errcode"] == 0:
                print("\nДоступные замки:")
                for lock in response_data.get("list", []):
                    print(f"Lock ID: {lock.get('lockId')}, Name: {lock.get('lockName')}, Alias: {lock.get('lockAlias')}")
                return response_data
            else:
                print(f"Ошибка получения списка: {response_data.get('errmsg', 'Неизвестная ошибка')} (Код: {response_data['errcode']})")
                return {}
    except Exception as e:
        print(f"Ошибка получения списка замков: {str(e)}")
        return {}
    return response_data


def unlock_lock(token, lock_id):
    """
    Пытается открыть замок с указанным lock_id через облако.
    """
    url = "https://euapi.ttlock.com/v3/lock/unlock"
    data = {
        "clientId": client_id,
        "lockId": lock_id,
        "accessToken": token,
        "date": int(time.time() * 1000)
    }
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(url, data=data, verify=False)
            debug_request("Открытие замка", url, data, response)
            response_data = response.json()
            if "errcode" in response_data:
                if response_data["errcode"] == 0:
                    print("Замок открыт успешно")
                    return True
                elif response_data["errcode"] == -3037:
                    if attempt < MAX_RETRIES - 1:
                        print(f"Замок занят. Повтор через {RETRY_DELAY} сек... (Попытка {attempt + 1}/{MAX_RETRIES})")
                        time.sleep(RETRY_DELAY)
                        continue
                    else:
                        print("Замок занят. Достигнут лимит попыток. Попробуйте позже.")
                        return False
                else:
                    print(f"Ошибка при открытии: {response_data.get('errmsg', 'Неизвестная ошибка')} (Код: {response_data['errcode']})")
                    print(f"Использован lock ID: {lock_id}")
                    return False
            else:
                print("Неожиданный формат ответа:", response_data)
                return False
        except Exception as e:
            print(f"Ошибка при запросе открытия: {str(e)}")
            return False
    return False


if __name__ == "__main__":
    def input_lock_id(default=None):
        val = input(f"Введите Lock ID (Enter для текущего: {default}): ").strip()
        return val if val else default
    def print_menu():
        print("\nВыберите действие:")
        print("1. Получить access_token")
        print("2. Получить список замков")
        print("3. Открыть замок")
        print("4. Закрыть замок")
        print("5. Получить статус замка")
        print("6. Сменить Lock ID (только для этой сессии)")
        print("0. Выход")

    current_lock_id = lock_id
    token = None
    while True:
        print_menu()
        choice = input("Ваш выбор: ").strip()
        if choice == "1":
            token = get_token()
            print(f"Текущий access_token: {token}")
        elif choice == "2":
            if not token:
                token = get_token()
            if token:
                locks = list_locks(token)
                lock_list = locks.get("list", []) if locks else []
                if lock_list:
                    print("\nСписок замков:")
                    for lock in lock_list:
                        print(f"Lock ID: {lock.get('lockId')}, Name: {lock.get('lockName')}, Alias: {lock.get('lockAlias')}")
                else:
                    print("Замки не найдены. Проверьте права доступа.")
        elif choice == "3":
            if not token:
                token = get_token()
            lid = input_lock_id(current_lock_id)
            if token and lid:
                unlock_lock(token, lid)
        elif choice == "4":
            if not token:
                token = get_token()
            lid = input_lock_id(current_lock_id)
            if token and lid:
                lock_lock(token, lid)
        elif choice == "5":
            if not token:
                token = get_token()
            lid = input_lock_id(current_lock_id)
            if token and lid:
                get_lock_status(token, lid)
        elif choice == "6":
            new_id = input("Введите новый Lock ID: ").strip()
            if new_id:
                current_lock_id = new_id
                print(f"Lock ID для сессии изменён на: {current_lock_id}")
        elif choice == "0":
            print("Выход.")
            break
        else:
            print("Некорректный выбор. Попробуйте снова.")
