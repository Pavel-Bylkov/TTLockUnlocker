import pytest
from unittest.mock import patch, MagicMock, call
import ttlock_api
import requests
import json

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    """
    Фикстура: устанавливает переменные окружения для всех тестов.
    """
    monkeypatch.setenv('TTLOCK_CLIENT_ID', 'test_client_id')
    monkeypatch.setenv('TTLOCK_CLIENT_SECRET', 'test_client_secret')
    monkeypatch.setenv('TTLOCK_USERNAME', 'test_username')
    monkeypatch.setenv('TTLOCK_PASSWORD', 'test_password')
    # Перезагружаем модуль для применения новых переменных окружения
    import importlib
    importlib.reload(ttlock_api)

@pytest.fixture
def mock_logger():
    """
    Фикстура для мока логгера.
    """
    return MagicMock()

@patch('requests.post')
def test_get_token_success(mock_post, mock_logger):
    """
    Тест: успешное получение токена.
    """
    mock_post.return_value.json.return_value = {'access_token': 'test_token'}
    token = ttlock_api.get_token(mock_logger)
    assert token == 'test_token'
    mock_post.assert_called_once()
    mock_logger.info.assert_called()

@patch('requests.post', side_effect=requests.exceptions.RequestException("Network Error"))
def test_get_token_network_error(mock_post, mock_logger):
    """
    Тест: обработка сетевой ошибки при получении токена.
    """
    token = ttlock_api.get_token(mock_logger)
    assert token is None
    mock_logger.error.assert_called_once_with("Ошибка получения токена: Network Error")

@patch('requests.post')
def test_get_token_json_error(mock_post, mock_logger):
    """
    Тест: обработка ошибок декодирования JSON от API.
    """
    mock_post.return_value.json.side_effect = json.JSONDecodeError("decoding error", "", 0)
    token = ttlock_api.get_token(mock_logger)
    assert token is None
    assert "Ошибка получения токена" in mock_logger.error.call_args[0][0]

def _test_lock_operation(operation_func, operation_name, mock_post, mock_sleep, mock_logger):
    """
    Универсальный тест для операций lock и unlock, покрывающий разные сценарии.
    """
    mock_send_telegram = MagicMock()

    # --- Сценарий 1: успех с первой попытки ---
    mock_post.reset_mock()
    mock_logger.reset_mock()
    mock_post.return_value.json.return_value = {"errcode": 0}
    result = operation_func('token', 'lock_id', mock_logger, mock_send_telegram)
    assert result == {"errcode": 0, "errmsg": "OK", "success": True}
    mock_post.assert_called_once()
    mock_logger.info.assert_called()
    mock_send_telegram.assert_called_once()

    # --- Сценарий 2: неудача (ошибка API) ---
    mock_post.reset_mock()
    mock_logger.reset_mock()
    mock_send_telegram.reset_mock()
    mock_post.return_value.json.return_value = {"errcode": -1, "errmsg": "API Error"}
    result = operation_func('token', 'lock_id', mock_logger, mock_send_telegram)
    assert result == {"errcode": -1, "errmsg": "API Error", "success": False}
    assert mock_post.call_count == 1
    assert mock_logger.error.call_count == 1
    assert mock_send_telegram.call_count == 1

    # --- Сценарий 3: неудача из-за сетевого исключения ---
    mock_post.reset_mock()
    mock_logger.reset_mock()
    mock_send_telegram.reset_mock()
    mock_post.side_effect = requests.exceptions.RequestException("Network Failure")
    result = operation_func('token', 'lock_id', mock_logger, mock_send_telegram)
    assert result == {"errcode": -1, "errmsg": "Network Failure", "success": False}
    assert mock_post.call_count == 1
    assert mock_logger.error.call_count == 1
    assert "Network Failure" in mock_logger.error.call_args_list[0][0][0]
    assert mock_send_telegram.call_count == 1

@patch('time.sleep')
@patch('requests.post')
def test_unlock_lock_scenarios(mock_post, mock_sleep, mock_logger):
    """
    Тест: различные сценарии для функции unlock_lock.
    """
    _test_lock_operation(ttlock_api.unlock_lock, 'открыть', mock_post, mock_sleep, mock_logger)

@patch('time.sleep')
@patch('requests.post')
def test_lock_lock_scenarios(mock_post, mock_sleep, mock_logger):
    """
    Тест: различные сценарии для функции lock_lock.
    """
    _test_lock_operation(ttlock_api.lock_lock, 'закрыть', mock_post, mock_sleep, mock_logger)

@patch('requests.get')
def test_list_locks_success(mock_get, mock_logger):
    """
    Тест: успешное получение списка замков.
    """
    mock_get.return_value.json.return_value = {"errcode": 0, "list": [{"lockId": 1}, {"lockId": 2}]}
    locks = ttlock_api.list_locks('token', mock_logger)
    assert locks == [{"lockId": 1}, {"lockId": 2}]
    mock_get.assert_called_once()
    mock_logger.info.assert_called_once()
    mock_logger.error.assert_not_called()

@patch('requests.get')
def test_list_locks_api_error(mock_get, mock_logger):
    """
    Тест: обработка ошибки API при получении списка замков.
    """
    mock_get.return_value.json.return_value = {"errcode": -1, "errmsg": "Auth failed"}
    locks = ttlock_api.list_locks('token', mock_logger)
    assert locks == []
    mock_logger.error.assert_called_once()
    assert "Auth failed" in mock_logger.error.call_args[0][0]
    mock_get.assert_called_once()

@patch('requests.get', side_effect=requests.exceptions.RequestException("Network Error"))
def test_list_locks_network_error(mock_get, mock_logger):
    """
    Тест: обработка сетевой ошибки при получении списка замков.
    """
    locks = ttlock_api.list_locks('token', mock_logger)
    assert locks == []
    mock_logger.error.assert_called_once()
    assert "Network Error" in mock_logger.error.call_args[0][0] 
