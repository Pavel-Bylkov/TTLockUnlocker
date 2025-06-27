import pytest
import unlocker
import os
from unittest.mock import patch, MagicMock

@pytest.fixture(autouse=True)
def setup_env():
    """Фикстура: установка переменных окружения для тестов и их очистка после выполнения."""
    os.environ['TTLOCK_PASSWORD'] = 'test_password'
    os.environ['TTLOCK_CLIENT_ID'] = 'test_client_id'
    os.environ['TTLOCK_CLIENT_SECRET'] = 'test_client_secret'
    os.environ['TTLOCK_USERNAME'] = 'test_username'
    os.environ['TTLOCK_LOCK_ID'] = 'test_lock_id'
    unlocker.init()  # Инициализируем модуль после установки переменных окружения
    yield
    for key in ['TTLOCK_PASSWORD', 'TTLOCK_CLIENT_ID', 'TTLOCK_CLIENT_SECRET', 'TTLOCK_USERNAME', 'TTLOCK_LOCK_ID']:
        os.environ.pop(key, None)

def test_get_token_success():
    """Тест: успешное получение токена."""
    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {'access_token': 'test_token'}
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        token = unlocker.get_token()
        assert token == 'test_token'
        mock_post.assert_called_once()

def test_get_token_failure():
    """Тест: неудачное получение токена (ошибка авторизации)."""
    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {'error': 'invalid credentials'}
        mock_response.status_code = 400
        mock_post.return_value = mock_response

        token = unlocker.get_token()
        assert token is None

def test_unlock_lock_success():
    """Тест: успешное открытие замка."""
    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {'errcode': 0}
        mock_post.return_value = mock_response

        result = unlocker.unlock_lock('test_token', 'test_lock_id')
        assert result is True
        mock_post.assert_called_once()

def test_unlock_lock_busy():
    """Тест: замок занят, повторные попытки открытия."""
    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {'errcode': -3037}
        mock_post.return_value = mock_response

        result = unlocker.unlock_lock('test_token', 'test_lock_id')
        assert result is False
        assert mock_post.call_count == 3  # Проверяем, что было 3 попытки

def test_lock_lock_success():
    """Тест: успешное закрытие замка."""
    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {'errcode': 0}
        mock_post.return_value = mock_response

        result = unlocker.lock_lock('test_token', 'test_lock_id')
        assert result is True
        mock_post.assert_called_once()

def test_get_lock_status():
    """Тест: получение статуса замка."""
    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {'errcode': 0, 'lockStatus': 1}
        mock_post.return_value = mock_response

        status = unlocker.get_lock_status('test_token', 'test_lock_id')
        assert status == 1
        mock_post.assert_called_once()

def test_list_locks():
    """Тест: получение списка замков."""
    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'errcode': 0,
            'list': [
                {'lockId': '1', 'lockName': 'Test Lock 1'},
                {'lockId': '2', 'lockName': 'Test Lock 2'}
            ]
        }
        mock_post.return_value = mock_response

        result = unlocker.list_locks('test_token')
        assert result['errcode'] == 0
        assert len(result['list']) == 2
        mock_post.assert_called_once() 
