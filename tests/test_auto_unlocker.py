import pytest
import auto_unlocker
import os
import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call, mock_open
import schedule
import pytz
from datetime import tzinfo
import telegram_utils

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    """Настройка окружения для всех тестов."""
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test_token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '123456')
    monkeypatch.setenv('TTLOCK_LOCK_ID', 'test_lock_id')
    monkeypatch.setenv('CONFIG_PATH', 'config.json')
    auto_unlocker.CONFIG_PATH = 'config.json'
    auto_unlocker.AUTHORIZED_CHAT_ID = '123456'
    auto_unlocker.BOT_TOKEN = 'test_token'

@pytest.fixture
def mock_logger():
    """Фикстура для мока логгера."""
    return MagicMock()

@pytest.fixture
def mock_config():
    """
    Фикстура для создания тестовой конфигурации.
    """
    return {
        "timezone": "Asia/Krasnoyarsk",
        "schedule_enabled": True,
        "open_times": {
            "Пн": "09:00",
            "Вт": "09:00",
            "Ср": "09:00",
            "Чт": "09:00",
            "Пт": "09:00",
            "Сб": None,
            "Вс": None
        },
        "breaks": {
            "Пн": ["13:00-14:00"],
            "Вт": [],
            "Ср": [],
            "Чт": [],
            "Пт": [],
            "Сб": [],
            "Вс": []
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
    with patch('ttlock_api.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        mock_fromtimestamp = MagicMock()
        mock_fromtimestamp.strftime.return_value = "2025-06-16 09:00:00"
        mock_datetime.fromtimestamp.return_value = mock_fromtimestamp
        yield mock_datetime

def test_load_config_default():
    """
    Тест загрузки конфигурации по умолчанию.
    Проверяет, что значения из файла конфигурации корректно загружаются.
    """
    # Тест с активным расписанием
    with patch('builtins.open', mock_open(read_data='{"schedule_enabled": true}')):
        config = auto_unlocker.load_config()
        assert config["timezone"] == "Asia/Krasnoyarsk"
        assert config["schedule_enabled"] is True

    # Тест с неактивным расписанием
    with patch('builtins.open', mock_open(read_data='{"schedule_enabled": false}')):
        config = auto_unlocker.load_config()
        assert config["timezone"] == "Asia/Krasnoyarsk"
        assert config["schedule_enabled"] is False

    # Тест с отсутствующим значением schedule_enabled
    with patch('builtins.open', mock_open(read_data='{"timezone": "Europe/Moscow"}')):
        config = auto_unlocker.load_config()
        assert config["timezone"] == "Europe/Moscow"
        assert config["schedule_enabled"] is True  # Должно быть True по умолчанию

def test_load_config_from_file(mock_config):
    """
    Тест загрузки конфигурации из файла.
    """
    mock_file = MagicMock()
    mock_config['max_retry_time'] = '21:00'  # Добавляем параметр в тестовые данные
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
        assert "Пн" in config["open_times"]
        assert "Пн" in config["breaks"]

def test_load_config_invalid_json():
    """
    Тест загрузки конфигурации при некорректном JSON.
    """
    with patch('builtins.open', mock_open(read_data="invalid json")):
        config = auto_unlocker.load_config()
        assert config["timezone"] == "Asia/Krasnoyarsk"
        assert config["schedule_enabled"] is True
        assert "Пн" in config["open_times"]
        assert "Пн" in config["breaks"]

def test_load_config_custom_values():
    """
    Тест загрузки конфигурации с пользовательскими значениями.
    """
    custom_config = {
        "timezone": "Asia/Krasnoyarsk",
        "schedule_enabled": False,
        "open_times": {"Пн": "10:00"},
        "breaks": {"Пн": ["12:00-13:00"]}
    }
    with patch('builtins.open', mock_open(read_data=json.dumps(custom_config))):
        config = auto_unlocker.load_config()
        assert config["timezone"] == "Asia/Krasnoyarsk"
        assert config["schedule_enabled"] is False
        assert config["open_times"]["Пн"] == "10:00"
        assert config["breaks"]["Пн"] == ["12:00-13:00"]

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
        "open_times": {"Пн": "09:00"},
        "breaks": {"Пн": []}
    }), \
         patch('auto_unlocker.ttlock_api.get_token', return_value="test_token"), \
         patch('auto_unlocker.ttlock_api.unlock_lock', return_value={"errcode": 0}, side_effect=lambda *args, **kwargs: {"errcode": 0}), \
         patch('auto_unlocker.send_telegram_message') as mock_send, \
         patch.dict('os.environ', {'TTLOCK_LOCK_ID': 'test_lock_id'}):

        # Создаем мок-объект для datetime.now()
        mock_now = MagicMock()
        mock_now.strftime = lambda fmt: "09:00" if fmt == "%H:%M" else "monday" if fmt == "%A" else "2025-06-16 09:00:00"
        mock_datetime.now.return_value = mock_now

        auto_unlocker.job()
        mock_send.assert_called_once()

def test_job_with_retries(mock_timezone, mock_datetime):
    """
    Тест повторных попыток открытия замка при ошибке (новая логика).
    Все 10 попыток завершаются неудачей.
    """
    with patch('auto_unlocker.load_config', return_value={
        "timezone": "Asia/Krasnoyarsk",
        "schedule_enabled": True,
        "open_times": {"Пн": "09:00"},
        "breaks": {"Пн": []}
    }), \
         patch('auto_unlocker.ttlock_api.get_token', return_value="test_token"), \
         patch('auto_unlocker.ttlock_api.unlock_lock', return_value={"errcode": 10003, "errmsg": "Lock is busy"}), \
         patch('auto_unlocker.send_telegram_message') as mock_send_telegram, \
         patch('auto_unlocker.send_email_notification') as mock_send_email, \
         patch('time.sleep') as mock_sleep, \
         patch.dict('os.environ', {'TTLOCK_LOCK_ID': 'test_lock_id'}):

        # Создаем мок-объект для datetime.now()
        mock_now = MagicMock()
        mock_now.strftime = lambda fmt: "09:00" if fmt == "%H:%M" else "monday" if fmt == "%A" else "2025-06-16 09:00:00"
        mock_datetime.now.return_value = mock_now

        auto_unlocker.job()

        # Проверяем вызовы: 10 попыток + 1 сообщение о 3-х неудачных + 1 о 5-ти + 1 итоговое
        assert mock_send_telegram.call_count == 10 + 3
        # Проверяем, что email был отправлен один раз
        mock_send_email.assert_called_once()
        # Проверяем, что были задержки
        assert mock_sleep.call_count > 0

def test_job_with_successful_retry(mock_timezone, mock_datetime):
    """
    Тест успешного открытия замка со второй попытки (новая логика).
    """
    with patch('auto_unlocker.load_config', return_value={
        "timezone": "Asia/Krasnoyarsk",
        "schedule_enabled": True,
        "open_times": {"Пн": "09:00"},
        "breaks": {"Пн": []}
    }), \
         patch('auto_unlocker.ttlock_api.get_token', return_value="test_token"), \
         patch('auto_unlocker.ttlock_api.unlock_lock', side_effect=[
             {"errcode": 10003, "errmsg": "Lock is busy"},  # 1-я попытка
             {"errcode": 0}  # 2-я попытка (успех)
         ]), \
         patch('auto_unlocker.send_telegram_message') as mock_send_telegram, \
         patch('auto_unlocker.send_email_notification') as mock_send_email, \
         patch('time.sleep') as mock_sleep, \
         patch.dict('os.environ', {'TTLOCK_LOCK_ID': 'test_lock_id'}):

        # Создаем мок-объект для datetime.now()
        mock_now = MagicMock()
        mock_now.strftime = lambda fmt: "09:00" if fmt == "%H:%M" else "monday" if fmt == "%A" else "2025-06-16 09:00:00"
        mock_datetime.now.return_value = mock_now

        auto_unlocker.job()

        # 1 сообщение об ошибке + 1 об успехе
        assert mock_send_telegram.call_count == 2
        # Email не должен был отправляться
        mock_send_email.assert_not_called()
        # Была одна задержка
        mock_sleep.assert_called_once_with(30)

def test_job_with_time_shift(mock_timezone, mock_datetime):
    """
    Тест использования смещенного времени.
    """
    with patch('auto_unlocker.load_config', return_value={
        "timezone": "Asia/Krasnoyarsk",
        "schedule_enabled": True,
        "open_times": {"Пн": "09:00"},
        "breaks": {"Пн": []},
        "max_retry_time": "21:00"
    }), \
         patch('auto_unlocker.ttlock_api.get_token', return_value="test_token"), \
         patch('auto_unlocker.ttlock_api.unlock_lock', return_value={"errcode": 0}, side_effect=lambda *args, **kwargs: {"errcode": 0}), \
         patch('auto_unlocker.send_telegram_message') as mock_send, \
         patch.dict('os.environ', {'TTLOCK_LOCK_ID': 'test_lock_id'}):

        # Устанавливаем смещение времени
        auto_unlocker.TIME_SHIFT = "09:15"

        # Создаем мок-объект для datetime.now()
        mock_now = MagicMock()
        mock_now.strftime = lambda fmt: "09:15" if fmt == "%H:%M" else "monday" if fmt == "%A" else "2025-06-16 09:15:00"
        mock_datetime.now.return_value = mock_now

        auto_unlocker.job()
        assert mock_send.call_count == 1
        calls = [call[0][0] for call in mock_send.call_args_list]
        assert "Замок успешно открыт" in calls[0]

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

def test_job_schedule_disabled(mock_logger):
    """Тест: задача не выполняется, если расписание отключено."""
    config = {"schedule_enabled": False}
    with patch('telegram_utils.load_config', return_value=config):
        with patch('auto_unlocker.process_unlock') as mock_process_unlock:
            auto_unlocker.job()
            mock_process_unlock.assert_not_called()

def test_job_schedule_enabled(mock_logger):
    """Тест: задача выполняется, если расписание включено."""
    config = {"schedule_enabled": True, "timezone": "UTC"}
    with patch('telegram_utils.load_config', return_value=config):
        with patch('auto_unlocker.process_unlock') as mock_process_unlock:
            auto_unlocker.job()
            mock_process_unlock.assert_called_once()

@patch('auto_unlocker.ttlock_api.get_token', return_value="test_token")
@patch('auto_unlocker.ttlock_api.unlock_lock')
@patch('telegram_utils.send_telegram_message')
def test_process_unlock_success(mock_send_message, mock_unlock, mock_get_token, mock_logger):
    """Тест: успешное открытие замка."""
    mock_unlock.return_value = {"errcode": 0, "attempt": 1}
    
    auto_unlocker.process_unlock()
    
    mock_get_token.assert_called_once()
    mock_unlock.assert_called_once_with("test_token", 'test_lock_id', mock_logger)
    mock_send_message.assert_called_with(
        'test_token', '123456', 
        'Замок успешно открыт (попытка 1)',
        mock_logger
    )

@patch('auto_unlocker.ttlock_api.get_token', return_value="test_token")
@patch('auto_unlocker.ttlock_api.unlock_lock')
@patch('telegram_utils.send_telegram_message')
@patch('time.sleep', return_value=None) # Чтобы не ждать в тесте
def test_process_unlock_with_retries_fail(mock_sleep, mock_send_message, mock_unlock, mock_get_token, mock_logger):
    """Тест: неуспешное открытие после всех попыток."""
    mock_unlock.return_value = {"errcode": 1, "errmsg": "Gateway timeout"}
    
    auto_unlocker.process_unlock()
    
    assert mock_unlock.call_count == 5
    mock_send_message.assert_called_with(
        'test_token', '123456',
        "Не удалось открыть замок после 5 попыток. Ошибка: Gateway timeout",
        mock_logger
    )

@patch('auto_unlocker.ttlock_api.get_token', return_value="test_token")
@patch('auto_unlocker.ttlock_api.unlock_lock')
@patch('telegram_utils.send_telegram_message')
@patch('time.sleep', return_value=None)
def test_process_unlock_with_retries_success_on_third_attempt(mock_sleep, mock_send_message, mock_unlock, mock_get_token, mock_logger):
    """Тест: успешное открытие на третьей попытке."""
    mock_unlock.side_effect = [
        {"errcode": 1, "errmsg": "Fail"},
        {"errcode": 1, "errmsg": "Fail"},
        {"errcode": 0, "attempt": 3},
    ]
    
    auto_unlocker.process_unlock()
    
    assert mock_unlock.call_count == 3
    mock_send_message.assert_called_with(
        'test_token', '123456',
        'Замок успешно открыт (попытка 3)',
        mock_logger
    )

def test_is_unlock_time_true(mock_logger):
    """Тест: проверка времени открытия - должно сработать."""
    now = datetime.strptime("09:00", "%H:%M").time()
    open_time_str = "09:00"
    breaks = []
    result = auto_unlocker.is_unlock_time(now, open_time_str, breaks, mock_logger)
    assert result is True

def test_is_unlock_time_false(mock_logger):
    """Тест: проверка времени открытия - не должно сработать."""
    now = datetime.strptime("09:01", "%H:%M").time()
    open_time_str = "09:00"
    breaks = []
    result = auto_unlocker.is_unlock_time(now, open_time_str, breaks, mock_logger)
    assert result is False

def test_is_unlock_time_in_break(mock_logger):
    """Тест: проверка времени открытия - попадает в перерыв."""
    now = datetime.strptime("13:30", "%H:%M").time()
    open_time_str = "09:00" # не имеет значения для этого теста
    breaks = ["13:00-14:00"]
    result = auto_unlocker.is_unlock_time(now, open_time_str, breaks, mock_logger)
    assert result is False

def test_is_unlock_time_no_schedule(mock_logger):
    """Тест: проверка времени открытия - расписание на день не задано."""
    now = datetime.strptime("09:00", "%H:%M").time()
    open_time_str = None
    breaks = []
    result = auto_unlocker.is_unlock_time(now, open_time_str, breaks, mock_logger)
    assert result is False

@patch('auto_unlocker.schedule.run_pending')
@patch('time.sleep')
@patch('telegram_utils.load_config')
def test_main_loop(mock_load_config, mock_sleep, mock_run_pending, mock_logger):
    """Тест главного цикла работы сервиса."""
    # Мокаем, чтобы цикл выполнился один раз и вышел
    mock_sleep.side_effect = InterruptedError
    mock_load_config.return_value = {
        "schedule_enabled": True,
        "open_times": {"Пн": "10:00"},
        "breaks": {}
    }
    
    with pytest.raises(InterruptedError):
        auto_unlocker.main()
    
    # Проверяем, что планировщик был настроен и запущен
    assert auto_unlocker.schedule.jobs # Убеждаемся, что задачи добавлены
    mock_run_pending.assert_called()
    mock_sleep.assert_called()

@patch('auto_unlocker.setup_schedule')
def test_main_loop_reloads_schedule_on_change(mock_setup_schedule, mock_logger):
    """Тест: главный цикл перезагружает расписание при изменении конфига."""
    configs = [
        {"schedule_enabled": True, "open_times": {"Пн": "10:00"}},
        {"schedule_enabled": True, "open_times": {"Пн": "11:00"}} # Измененный конфиг
    ]
    
    with patch('telegram_utils.load_config', side_effect=configs):
        with patch('time.sleep', side_effect=[None, InterruptedError]): # Выполнить цикл дважды
             with pytest.raises(InterruptedError):
                auto_unlocker.main()

    # setup_schedule должен быть вызван дважды: первый раз и при смене конфига
    assert mock_setup_schedule.call_count == 2 