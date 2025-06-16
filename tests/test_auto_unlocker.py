import pytest
import auto_unlocker
import os
import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call, mock_open
import schedule
import pytz
from datetime import tzinfo

@pytest.fixture(autouse=True)
def setup_env():
    # Сохраняем оригинальные значения
    original_values = {}
    for key in ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'TELEGRAM_CODEWORD',
                'AUTO_UNLOCKER_CONTAINER', 'TTLOCK_CLIENT_ID', 'TTLOCK_CLIENT_SECRET',
                'TTLOCK_USERNAME', 'TTLOCK_PASSWORD', 'TTLOCK_LOCK_ID']:
        original_values[key] = os.environ.get(key)
        if key in os.environ:
            del os.environ[key]

    # Устанавливаем тестовые значения
    os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
    os.environ['TELEGRAM_CHAT_ID'] = '123456'
    os.environ['TELEGRAM_CODEWORD'] = 'test_codeword'
    os.environ['AUTO_UNLOCKER_CONTAINER'] = 'test_container'
    os.environ['TTLOCK_CLIENT_ID'] = 'test_client_id'
    os.environ['TTLOCK_CLIENT_SECRET'] = 'test_client_secret'
    os.environ['TTLOCK_USERNAME'] = 'test_username'
    os.environ['TTLOCK_PASSWORD'] = 'test_password'

    yield

    # Восстанавливаем оригинальные значения
    for key, value in original_values.items():
        if value is not None:
            os.environ[key] = value
        elif key in os.environ:
            del os.environ[key]

@pytest.fixture
def mock_config():
    """
    Фикстура для создания тестовой конфигурации.
    """
    return {
        "timezone": "Asia/Krasnoyarsk",
        "schedule_enabled": True,
        "open_times": {
            "monday": "09:00",
            "tuesday": "09:00",
            "wednesday": "09:00",
            "thursday": "09:00",
            "friday": "09:00",
            "saturday": None,
            "sunday": None
        },
        "breaks": {
            "monday": ["13:00-14:00"],
            "tuesday": [],
            "wednesday": [],
            "thursday": [],
            "friday": [],
            "saturday": [],
            "sunday": []
        }
    }

@pytest.fixture
def mock_timezone():
    """
    Фикстура для мока часового пояса.
    """
    class MockTimezone(tzinfo):
        def __init__(self, *args, **kwargs):
            pass

        def utcoffset(self, dt):
            return timedelta(hours=7)  # Для Asia/Krasnoyarsk

        def dst(self, dt):
            return timedelta(0)

        def tzname(self, dt):
            return "Asia/Krasnoyarsk"

        def localize(self, dt):
            return dt

        def normalize(self, dt):
            return dt

    with patch('pytz.timezone') as mock_tz:
        mock_tz.return_value = MockTimezone()
        yield mock_tz

@pytest.fixture
def mock_datetime():
    """
    Фикстура для мока текущего времени.
    """
    mock_dt = datetime(2025, 6, 16, 9, 0)  # Понедельник, 09:00
    with patch('auto_unlocker.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        yield mock_datetime

def test_load_config_default():
    """
    Тест загрузки конфигурации по умолчанию.
    """
    config = auto_unlocker.load_config()
    assert config["timezone"] == "Asia/Krasnoyarsk"
    assert config["schedule_enabled"] is True
    assert "monday" in config["open_times"]
    assert "monday" in config["breaks"]

def test_load_config_from_file(mock_config):
    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = json.dumps(mock_config)
    with patch('builtins.open', return_value=mock_file):
        config = auto_unlocker.load_config()
        assert config == mock_config

def test_load_config_file_not_found():
    """
    Тест загрузки конфигурации при отсутствии файла.
    """
    with patch('builtins.open', side_effect=FileNotFoundError):
        config = auto_unlocker.load_config()
        assert config["timezone"] == "Asia/Krasnoyarsk"
        assert config["schedule_enabled"] is True
        assert "monday" in config["open_times"]
        assert "monday" in config["breaks"]

def test_load_config_invalid_json():
    """
    Тест загрузки конфигурации при некорректном JSON.
    """
    with patch('builtins.open', mock_open(read_data="invalid json")):
        config = auto_unlocker.load_config()
        assert config["timezone"] == "Asia/Krasnoyarsk"
        assert config["schedule_enabled"] is True
        assert "monday" in config["open_times"]
        assert "monday" in config["breaks"]

def test_load_config_custom_values():
    """
    Тест загрузки конфигурации с пользовательскими значениями.
    """
    custom_config = {
        "timezone": "Asia/Krasnoyarsk",
        "schedule_enabled": False,
        "open_times": {"monday": "10:00"},
        "breaks": {"monday": ["12:00-13:00"]}
    }
    with patch('builtins.open', mock_open(read_data=json.dumps(custom_config))):
        config = auto_unlocker.load_config()
        assert config["timezone"] == "Asia/Krasnoyarsk"
        assert config["schedule_enabled"] is False
        assert config["open_times"]["monday"] == "10:00"
        assert config["breaks"]["monday"] == ["12:00-13:00"]

def test_send_telegram_message():
    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        auto_unlocker.send_telegram_message("Test message")
        mock_post.assert_called_once()

def test_send_telegram_message_success():
    """Тест успешной отправки сообщения в Telegram"""
    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        auto_unlocker.send_telegram_message("Test message")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "sendMessage" in args[0]
        assert kwargs["data"]["text"] == "Test message"
        assert kwargs["data"]["parse_mode"] == "HTML"

def test_send_telegram_message_failure():
    """Тест отправки сообщения в Telegram при ошибке"""
    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_post.return_value = mock_response

        auto_unlocker.send_telegram_message("Test message")
        mock_post.assert_called_once()

def test_send_telegram_message_exception():
    """Тест отправки сообщения в Telegram при исключении"""
    with patch('requests.post', side_effect=Exception("Network error")):
        auto_unlocker.send_telegram_message("Test message")

def test_resolve_lock_id_from_env():
    with patch('ttlock_api.list_locks') as mock_list_locks:
        os.environ['TTLOCK_LOCK_ID'] = 'test_lock_id'
        token = 'test_token'

        lock_id = auto_unlocker.resolve_lock_id(token)
        assert lock_id == 'test_lock_id'
        mock_list_locks.assert_not_called()

def test_resolve_lock_id_from_list():
    with patch('ttlock_api.list_locks') as mock_list_locks:
        mock_list_locks.return_value = [{'lockId': 'test_lock_id', 'lockName': 'Test Lock'}]

        lock_id = auto_unlocker.resolve_lock_id('test_token')
        assert lock_id == 'test_lock_id'
        mock_list_locks.assert_called_once()

def test_job_success(mock_timezone, mock_datetime):
    """
    Тест успешного выполнения задачи открытия замка.
    """
    with patch('auto_unlocker.load_config', return_value={
        "timezone": "Asia/Krasnoyarsk",
        "schedule_enabled": True,
        "open_times": {"monday": "09:00"},
        "breaks": {"monday": []}
    }), \
         patch('auto_unlocker.ttlock_api.get_token', return_value="test_token"), \
         patch('auto_unlocker.ttlock_api.unlock_lock', return_value={"errcode": 0}), \
         patch('auto_unlocker.send_telegram_message') as mock_send:

        auto_unlocker.job()
        mock_send.assert_called_once()

def test_job_with_retries(mock_timezone, mock_datetime):
    """
    Тест повторных попыток открытия замка при ошибке.
    """
    with patch('auto_unlocker.load_config', return_value={
        "timezone": "Asia/Krasnoyarsk",
        "schedule_enabled": True,
        "open_times": {"monday": "09:00"},
        "breaks": {"monday": []}
    }), \
         patch('auto_unlocker.ttlock_api.get_token', return_value="test_token"), \
         patch('auto_unlocker.ttlock_api.unlock_lock', side_effect=[
             {"errcode": 10003, "errmsg": "Lock is busy"},  # Первая попытка
             {"errcode": 10003, "errmsg": "Lock is busy"},  # Вторая попытка
             {"errcode": 10003, "errmsg": "Lock is busy"}   # Третья попытка
         ]), \
         patch('auto_unlocker.send_telegram_message') as mock_send, \
         patch('time.sleep') as mock_sleep:

        auto_unlocker.job()
        assert mock_send.call_count == 3

def test_job_with_successful_retry(mock_timezone, mock_datetime):
    """
    Тест успешного открытия замка со второй попытки.
    """
    with patch('auto_unlocker.load_config', return_value={
        "timezone": "Asia/Krasnoyarsk",
        "schedule_enabled": True,
        "open_times": {"monday": "09:00"},
        "breaks": {"monday": []}
    }), \
         patch('auto_unlocker.ttlock_api.get_token', return_value="test_token"), \
         patch('auto_unlocker.ttlock_api.unlock_lock', side_effect=[
             {"errcode": 10003, "errmsg": "Lock is busy"},  # Первая попытка
             {"errcode": 0}  # Успешная вторая попытка
         ]), \
         patch('auto_unlocker.send_telegram_message') as mock_send, \
         patch('time.sleep') as mock_sleep:

        auto_unlocker.job()
        assert mock_send.call_count == 2

def test_job_with_other_error(mock_timezone, mock_datetime):
    """
    Тест обработки других ошибок при открытии замка.
    """
    with patch('auto_unlocker.load_config', return_value={
        "timezone": "Asia/Krasnoyarsk",
        "schedule_enabled": True,
        "open_times": {"monday": "09:00"},
        "breaks": {"monday": []}
    }), \
         patch('auto_unlocker.ttlock_api.get_token', return_value="test_token"), \
         patch('auto_unlocker.ttlock_api.unlock_lock', return_value={"errcode": 10001, "errmsg": "Other error"}), \
         patch('auto_unlocker.send_telegram_message') as mock_send, \
         patch('time.sleep') as mock_sleep:

        auto_unlocker.job()
        assert mock_send.call_count == 1

def test_debug_request():
    """Тест отладочного вывода HTTP-запроса"""
    with patch('builtins.print') as mock_print:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}

        auto_unlocker.debug_request("Test Request", "http://test.com", {"param": "value"}, mock_response)

        assert mock_print.call_count == 5
        calls = [call.args[0] for call in mock_print.call_args_list]
        assert "[DEBUG] Test Request" in calls[0]
        assert "URL: http://test.com" in calls[1]
        assert "Параметры запроса: " in calls[2]
        assert "Статус ответа: 200" in calls[3]
        assert "Тело ответа: " in calls[4]

def test_debug_request_non_json_response():
    """Тест отладочного вывода HTTP-запроса с не-JSON ответом"""
    with patch('builtins.print') as mock_print:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = Exception("Not JSON")
        mock_response.text = "Plain text response"

        auto_unlocker.debug_request("Test Request", "http://test.com", {"param": "value"}, mock_response)

        assert mock_print.call_count == 5
        calls = [call.args[0] for call in mock_print.call_args_list]
        assert "[DEBUG] Test Request" in calls[0]
        assert "URL: http://test.com" in calls[1]
        assert "Параметры запроса: " in calls[2]
        assert "Статус ответа: 200" in calls[3]
        assert "Тело ответа (не JSON): Plain text response" in calls[4]
