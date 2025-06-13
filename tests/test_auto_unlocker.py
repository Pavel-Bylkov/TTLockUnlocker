import pytest
import auto_unlocker
import os
import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call
import schedule

@pytest.fixture(autouse=True)
def setup_env():
    # Сохраняем оригинальные значения
    original_values = {}
    for key in ['TTLOCK_PASSWORD', 'TTLOCK_CLIENT_ID', 'TTLOCK_CLIENT_SECRET', 
                'TTLOCK_USERNAME', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'TTLOCK_LOCK_ID']:
        original_values[key] = os.environ.get(key)
        if key in os.environ:
            del os.environ[key]
    
    # Устанавливаем тестовые значения
    os.environ['TTLOCK_PASSWORD'] = 'test_password'
    os.environ['TTLOCK_CLIENT_ID'] = 'test_client_id'
    os.environ['TTLOCK_CLIENT_SECRET'] = 'test_client_secret'
    os.environ['TTLOCK_USERNAME'] = 'test_username'
    os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
    os.environ['TELEGRAM_CHAT_ID'] = 'test_chat_id'
    
    yield
    
    # Восстанавливаем оригинальные значения
    for key, value in original_values.items():
        if value is not None:
            os.environ[key] = value
        elif key in os.environ:
            del os.environ[key]

@pytest.fixture
def mock_config():
    return {
        "timezone": "Asia/Novosibirsk",
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

def test_load_config_default():
    with patch('builtins.open', MagicMock(side_effect=FileNotFoundError())):
        config = auto_unlocker.load_config()
        assert config["timezone"] == "Asia/Novosibirsk"
        assert config["schedule_enabled"] is True
        assert config["open_times"]["monday"] == "09:00"
        assert config["breaks"]["monday"] == ["13:00-14:00"]

def test_load_config_from_file(mock_config):
    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = json.dumps(mock_config)
    with patch('builtins.open', return_value=mock_file):
        config = auto_unlocker.load_config()
        assert config == mock_config

def test_load_config_file_not_found():
    """Тест загрузки конфигурации при отсутствии файла"""
    with patch('builtins.open', MagicMock(side_effect=FileNotFoundError())):
        config = auto_unlocker.load_config()
        assert config["timezone"] == "Asia/Novosibirsk"
        assert config["schedule_enabled"] is True
        assert config["open_times"]["monday"] == "09:00"
        assert config["breaks"]["monday"] == ["13:00-14:00"]

def test_load_config_invalid_json():
    """Тест загрузки конфигурации при некорректном JSON"""
    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = "invalid json"
    with patch('builtins.open', return_value=mock_file):
        config = auto_unlocker.load_config()
        assert config["timezone"] == "Asia/Novosibirsk"
        assert config["schedule_enabled"] is True

def test_load_config_custom_values():
    """Тест загрузки конфигурации с пользовательскими значениями"""
    custom_config = {
        "timezone": "Europe/Moscow",
        "schedule_enabled": False,
        "open_times": {
            "monday": "10:00",
            "tuesday": "10:00",
            "wednesday": "10:00",
            "thursday": "10:00",
            "friday": "10:00",
            "saturday": None,
            "sunday": None
        },
        "breaks": {
            "monday": ["12:00-13:00", "15:00-16:00"],
            "tuesday": [],
            "wednesday": [],
            "thursday": [],
            "friday": [],
            "saturday": [],
            "sunday": []
        }
    }
    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = json.dumps(custom_config)
    with patch('builtins.open', return_value=mock_file):
        config = auto_unlocker.load_config()
        assert config == custom_config

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

def test_job_success():
    with patch('ttlock_api.get_token') as mock_get_token, \
         patch('ttlock_api.unlock_lock') as mock_unlock, \
         patch('auto_unlocker.resolve_lock_id') as mock_resolve:
        
        mock_get_token.return_value = 'test_token'
        mock_resolve.return_value = 'test_lock_id'
        mock_unlock.return_value = {'errcode': 0, 'success': True}
        
        auto_unlocker.LOCK_ID = None
        auto_unlocker.job()
        
        mock_get_token.assert_called_once()
        mock_resolve.assert_called_once()
        mock_unlock.assert_called_once()

def test_job_with_retries():
    with patch('ttlock_api.get_token') as mock_get_token, \
         patch('ttlock_api.unlock_lock') as mock_unlock, \
         patch('auto_unlocker.resolve_lock_id') as mock_resolve, \
         patch('ttlock_api.get_now') as mock_now:
        
        mock_get_token.return_value = 'test_token'
        mock_resolve.return_value = 'test_lock_id'
        mock_unlock.side_effect = [
            {'errcode': -3037, 'success': False},  # Первая попытка - замок занят
            {'errcode': -3037, 'success': False},  # Вторая попытка - замок занят
            {'errcode': -3037, 'success': False},  # Третья попытка - замок занят
            {'errcode': 0, 'success': True}        # Четвертая попытка - успех
        ]
        
        # Устанавливаем текущее время 9:00
        mock_now.return_value = datetime.now().replace(hour=9, minute=0)
        
        auto_unlocker.LOCK_ID = 'test_lock_id'
        auto_unlocker.job()
        
        assert mock_unlock.call_count == 4
        # Проверяем, что последняя попытка была в 9:15
        assert mock_now.call_count > 0

def test_job_max_retries():
    with patch('ttlock_api.get_token') as mock_get_token, \
         patch('ttlock_api.unlock_lock') as mock_unlock, \
         patch('auto_unlocker.resolve_lock_id') as mock_resolve, \
         patch('ttlock_api.get_now') as mock_now:
        
        mock_get_token.return_value = 'test_token'
        mock_resolve.return_value = 'test_lock_id'
        mock_unlock.return_value = {'errcode': -3037, 'success': False}
        
        # Устанавливаем текущее время 20:45
        mock_now.return_value = datetime.now().replace(hour=20, minute=45)
        
        auto_unlocker.LOCK_ID = 'test_lock_id'
        auto_unlocker.job()
        
        # Проверяем, что не было попыток после 21:00
        assert mock_unlock.call_count <= 3

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