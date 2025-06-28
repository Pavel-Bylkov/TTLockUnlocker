import pytest
import requests
import smtplib
import json
from unittest.mock import MagicMock, patch, mock_open

from telegram_utils import (
    is_authorized,
    send_telegram_message,
    load_config,
    save_config,
    log_exception,
    send_email_notification,
    log_message
)

# --- Mocks and Fixtures ---

class DummyUpdate:
    """Заглушка для имитации объекта telegram.Update."""
    class Chat:
        def __init__(self, id):
            self.id = id
    def __init__(self, chat_id):
        self.effective_chat = self.Chat(chat_id)

@pytest.fixture
def mock_logger():
    """Фикстура для создания мок-логгера."""
    return MagicMock()

# --- Tests for is_authorized ---

def test_is_authorized_true():
    """Проверяет, что is_authorized возвращает True для правильного chat_id."""
    update = DummyUpdate(123)
    assert is_authorized(update, 123) is True

def test_is_authorized_false():
    """Проверяет, что is_authorized возвращает False для неправильного chat_id."""
    update = DummyUpdate(123)
    assert is_authorized(update, 456) is False

def test_is_authorized_string_comparison():
    """Проверяет, что is_authorized корректно работает при сравнении строк и чисел."""
    update = DummyUpdate('123')
    assert is_authorized(update, 123) is True
    update = DummyUpdate(123)
    assert is_authorized(update, '123') is True

# --- Tests for send_telegram_message ---

@patch('requests.post')
def test_send_telegram_message_success(mock_post, mock_logger):
    """Проверяет успешную отправку сообщения в Telegram."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response

    send_telegram_message('token', 123, 'test', mock_logger)
    
    mock_post.assert_called_once()
    assert 'https://api.telegram.org/bottoken/sendMessage' in mock_post.call_args[0][0]
    assert mock_post.call_args[1]['data']['chat_id'] == 123
    assert mock_post.call_args[1]['data']['text'] == 'test'
    mock_logger.warning.assert_not_called()

@patch('requests.post')
def test_send_telegram_message_with_env_chat_id(mock_post, mock_logger, monkeypatch):
    """Проверяет отправку сообщения в Telegram с chat_id из переменных окружения."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "456")

    send_telegram_message('token', None, 'test', mock_logger)

    mock_post.assert_called_once()
    assert 'https://api.telegram.org/bottoken/sendMessage' in mock_post.call_args[0][0]
    assert mock_post.call_args[1]['data']['chat_id'] == "456"
    assert mock_post.call_args[1]['data']['text'] == 'test'
    mock_logger.warning.assert_not_called()

@patch('requests.post')
def test_send_telegram_message_no_chat_id(mock_post, mock_logger, monkeypatch):
    """Проверяет поведение при отсутствии chat_id и переменной окружения."""
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    result = send_telegram_message('token', None, 'test', mock_logger)

    assert result is False
    mock_post.assert_not_called()
    mock_logger.error.assert_called_once_with("TELEGRAM_CHAT_ID не задан в переменных окружения")

@patch('requests.post')
def test_send_telegram_message_http_error(mock_post, mock_logger):
    """Проверяет обработку HTTP-ошибки при отправке сообщения в Telegram."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = 'Bad Request'
    mock_post.return_value = mock_response

    send_telegram_message('token', 123, 'test', mock_logger)
    
    mock_post.assert_called_once()
    mock_logger.warning.assert_called_once_with("Ошибка отправки Telegram: Bad Request")

@patch('requests.post', side_effect=requests.exceptions.RequestException("Network Error"))
def test_send_telegram_message_network_error(mock_post, mock_logger):
    """Проверяет обработку сетевой ошибки при отправке сообщения в Telegram."""
    send_telegram_message('token', 123, 'test', mock_logger)
    
    mock_post.assert_called_once()
    assert "Ошибка отправки Telegram: Network Error" in mock_logger.warning.call_args[0][0]



# --- Tests for load_config ---

def test_load_config_success(mock_logger):
    """Проверяет успешную загрузку конфигурационного файла."""
    m = mock_open(read_data='{"key": "value"}')
    with patch('builtins.open', m):
        config = load_config('fake_path.json', mock_logger)
        assert config == {"key": "value"}
        mock_logger.debug.assert_called()

def test_load_config_file_not_found(mock_logger):
    """Проверяет загрузку конфигурации, когда файл не найден."""
    with patch('builtins.open', side_effect=FileNotFoundError("File not found")):
        config = load_config('fake_path.json', mock_logger, default={"default": True})
        assert config == {"default": True}
        mock_logger.error.assert_called_once_with("Ошибка чтения конфигурации: File not found")

def test_load_config_invalid_json(mock_logger):
    """Проверяет загрузку конфигурации с некорректным JSON."""
    m = mock_open(read_data='invalid json')
    with patch('builtins.open', m):
        config = load_config('fake_path.json', mock_logger, default={"default": True})
        assert config == {"default": True}
        assert "Ошибка чтения конфигурации" in mock_logger.error.call_args[0][0]

# --- Tests for save_config ---

def test_save_config_success(mock_logger):
    """Проверяет успешное сохранение конфигурационного файла."""
    m = mock_open()
    with patch('builtins.open', m):
        save_config({"key": "value"}, 'fake_path.json', mock_logger)
        m.assert_called_once_with('fake_path.json', 'w', encoding='utf-8')
        handle = m()
        # Instead of checking for a single call, we join all write calls and compare the result
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)
        expected_content = json.dumps({"key": "value"}, ensure_ascii=False, indent=2)
        assert written_content == expected_content
        mock_logger.debug.assert_called()

def test_save_config_write_error(mock_logger):
    """Проверяет обработку ошибки записи при сохранении конфигурационного файла."""
    m = mock_open()
    m.side_effect = IOError("Permission denied")
    with patch('builtins.open', m):
        with pytest.raises(IOError):
            save_config({"key": "value"}, 'fake_path.json', mock_logger)
        mock_logger.error.assert_called_once_with("Ошибка сохранения конфигурации: Permission denied")

# --- Tests for log_exception ---

def test_log_exception(mock_logger):
    """Проверяет, что log_exception логирует текущий traceback."""
    try:
        raise ValueError("Test exception")
    except ValueError:
        log_exception(mock_logger)
    
    mock_logger.error.assert_called_once()
    # Check that the logged message contains the traceback header and the exception type
    logged_error = mock_logger.error.call_args[0][0]
    assert "Traceback (most recent call last):" in logged_error
    assert 'raise ValueError("Test exception")' in logged_error
    assert "ValueError: Test exception" in logged_error

# --- Tests for send_email_notification ---

@patch('smtplib.SMTP_SSL')
def test_send_email_notification_success(mock_smtp, mock_logger, monkeypatch):
    """Проверяет успешную отправку email-уведомления."""
    monkeypatch.setenv("EMAIL_TO", "to@example.com")
    monkeypatch.setenv("SMTP_SERVER", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "password")

    result = send_email_notification("Subject", "Body")
    
    assert result is True
    mock_smtp.assert_called_once_with("smtp.example.com", 465)
    server = mock_smtp.return_value.__enter__.return_value
    server.login.assert_called_once_with("user@example.com", "password")
    server.sendmail.assert_called_once()
    
@patch('telegram_utils.logger')
def test_send_email_notification_missing_env_vars(mock_logger_direct, monkeypatch):
    """Проверяет отправку email при отсутствии необходимых переменных окружения."""
    monkeypatch.delenv("EMAIL_TO", raising=False)
    
    result = send_email_notification("Subject", "Body")
    
    assert result is False
    mock_logger_direct.warning.assert_called_once_with(
        "Параметры для отправки email не настроены. Уведомление не отправлено."
    )

@patch('smtplib.SMTP_SSL', side_effect=smtplib.SMTPException("SMTP Error"))
def test_send_email_notification_smtp_error(mock_smtp, mock_logger, monkeypatch):
    """Проверяет обработку SMTP-ошибки при отправке email-уведомления."""
    monkeypatch.setenv("EMAIL_TO", "to@example.com")
    monkeypatch.setenv("SMTP_SERVER", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "password")

    result = send_email_notification("Subject", "Body")
    
    assert result is False

# --- Tests for log_message ---

@patch('builtins.print')
def test_log_message_error(mock_print, mock_logger):
    """Проверяет логирование сообщения уровня ERROR."""
    log_message(mock_logger, "ERROR", "Error message")
    mock_print.assert_called_once_with("[ERROR] Error message")
    mock_logger.error.assert_called_once_with("Error message")

@patch('builtins.print')
def test_log_message_info(mock_print, mock_logger):
    """Проверяет логирование сообщения уровня INFO."""
    log_message(mock_logger, "INFO", "Info message")
    mock_print.assert_called_once_with("[INFO] Info message")
    mock_logger.info.assert_called_once_with("Info message")

@patch('builtins.print')
def test_log_message_debug(mock_print, mock_logger):
    """Проверяет логирование сообщения уровня DEBUG."""
    log_message(mock_logger, "DEBUG", "Debug message")
    mock_print.assert_called_once_with("[DEBUG] Debug message")
    mock_logger.debug.assert_called_once_with("Debug message") 
