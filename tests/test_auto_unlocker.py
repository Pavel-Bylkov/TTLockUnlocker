import pytest
import os
import importlib
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call
import schedule
from datetime import tzinfo
import telegram_utils

# Устанавливаем переменные окружения ДО импорта модулей
os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
os.environ['TELEGRAM_CHAT_ID'] = '123456'
os.environ['TTLOCK_LOCK_ID'] = 'test_lock_id'
os.environ['CONFIG_PATH'] = '/tmp/test_config.json'
os.environ['TTLOCK_CLIENT_ID'] = 'test_client_id'
os.environ['TTLOCK_CLIENT_SECRET'] = 'test_client_secret'
os.environ['TTLOCK_USERNAME'] = 'test_username'
os.environ['TTLOCK_PASSWORD'] = 'test_password'
os.environ['EMAIL_TO'] = 'test@example.com'
os.environ['SMTP_SERVER'] = 'smtp.example.com'
os.environ['SMTP_PORT'] = '587'
os.environ['SMTP_USER'] = 'user'
os.environ['SMTP_PASSWORD'] = 'password'

# Теперь импортируем модули
import auto_unlocker

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    """
    Фикстура: перезагружает модули и очищает планировщик перед каждым тестом.
    """
    importlib.reload(auto_unlocker)
    importlib.reload(telegram_utils)
    schedule.clear()

    # Сбрасываем глобальную переменную перед каждым тестом
    auto_unlocker.LOCK_ID = os.getenv('TTLOCK_LOCK_ID')

@pytest.fixture
def mock_logger():
    """
    Фикстура для мока логгера.
    """
    with patch('auto_unlocker.logger', MagicMock()) as mock_log:
        yield mock_log

@pytest.fixture
def mock_config():
    """
    Фикстура для тестовой конфигурации.
    """
    return {
        "timezone": "Asia/Krasnoyarsk",
        "schedule_enabled": True,
        "open_times": {"Пн": "09:00", "Вт": "10:00"},
        "breaks": {"Пн": ["13:00-14:00"]}
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

@pytest.fixture
def mock_get_now():
    """
    Фикстура для мока ttlock_api.get_now, возвращает Понедельник 09:00.
    """
    mock_dt = datetime(2025, 6, 16, 9, 0) # Понедельник 09:00
    with patch('ttlock_api.get_now', return_value=mock_dt) as mock_time:
        yield mock_time

# --- Тесты для основной логики job() ---

@patch('auto_unlocker.execute_lock_action_with_retries')
@patch('auto_unlocker.ttlock_api.get_token', return_value='test_token')
def test_job_calls_executor_on_time(mock_get_token, mock_executor, mock_config, mock_get_now, mock_logger):
    """
    Проверяет, что job вызывает execute_lock_action_with_retries в правильное время.
    """
    with patch('auto_unlocker.load_config', return_value=mock_config):
        auto_unlocker.job()
        mock_executor.assert_called_once_with(
            action_func=auto_unlocker.ttlock_api.unlock_lock,
            token='test_token',
            lock_id='test_lock_id',
            action_name="открытия",
            success_msg="открыт",
            failure_msg_part="открытие замка"
        )

def test_job_does_not_run_if_not_time(mock_config, mock_get_now, mock_logger):
    """
    Проверяет, что job не выполняется, если время не совпадает.
    """
    mock_config["open_times"]["Пн"] = "10:00" # Меняем время на 10:00
    with patch('auto_unlocker.load_config', return_value=mock_config), \
         patch('auto_unlocker.execute_lock_action_with_retries') as mock_executor:
        auto_unlocker.job()
        mock_executor.assert_not_called()

def test_job_does_not_run_during_break(mock_config, mock_logger):
    """
    Проверяет, что job не выполняется во время перерыва.
    """
    mock_dt = datetime(2025, 6, 16, 13, 30)  # Понедельник 13:30, перерыв с 13:00 до 14:00
    with patch('ttlock_api.get_now', return_value=mock_dt), \
         patch('auto_unlocker.load_config', return_value=mock_config), \
         patch('auto_unlocker.execute_lock_action_with_retries') as mock_executor:
        auto_unlocker.job()
        mock_executor.assert_not_called()

def test_job_does_not_run_if_schedule_disabled(mock_config, mock_get_now, mock_logger):
    """
    Проверяет, что job не выполняется, если расписание отключено.
    """
    mock_config["schedule_enabled"] = False
    with patch('auto_unlocker.load_config', return_value=mock_config), \
         patch('auto_unlocker.execute_lock_action_with_retries') as mock_executor:
        auto_unlocker.job()
        mock_executor.assert_not_called()

# --- Тесты для execute_lock_action_with_retries ---

@patch('time.sleep')
@patch('auto_unlocker.send_email_notification')
@patch('auto_unlocker.send_telegram_message')
@patch('auto_unlocker.ttlock_api.unlock_lock')
def test_executor_success_first_try(mock_unlock, mock_send_msg, mock_send_email, mock_sleep, mock_logger):
    """
    Проверяет, что исполнитель успешно открывает замок с первой попытки.
    """
    mock_unlock.return_value = {"errcode": 0}

    result = auto_unlocker.execute_lock_action_with_retries(
        auto_unlocker.ttlock_api.unlock_lock, 'token', 'lock_id', 'открытия', 'открыт', 'открытие'
    )

    assert result is True
    mock_unlock.assert_called_once()
    mock_send_msg.assert_called_once_with(
        'test_token', None, '✅ <b>Замок успешно открыт (попытка #1)</b>', mock_logger
    )
    mock_send_email.assert_not_called()
    mock_sleep.assert_not_called()

@patch('time.sleep')
@patch('auto_unlocker.send_email_notification')
@patch('auto_unlocker.send_telegram_message')
@patch('auto_unlocker.ttlock_api.unlock_lock')
def test_executor_success_on_retry(mock_unlock, mock_send_msg, mock_send_email, mock_sleep, mock_logger):
    """
    Проверяет, что исполнитель успешно открывает замок на 3-й попытке.
    """
    mock_unlock.side_effect = [
        {"errcode": 1, "errmsg": "fail 1"},
        {"errcode": 1, "errmsg": "fail 2"},
        {"errcode": 0}
    ]

    result = auto_unlocker.execute_lock_action_with_retries(
        auto_unlocker.ttlock_api.unlock_lock, 'token', 'lock_id', 'открытия', 'открыт', 'открытие замка'
    )

    assert result is True
    assert mock_unlock.call_count == 3
    assert mock_send_msg.call_count == 3
    mock_send_email.assert_not_called()
    # Проверяем, что были вызваны задержки 30с и 60с
    mock_sleep.assert_has_calls([call(30), call(60)])

@patch('time.sleep')
@patch('auto_unlocker.send_email_notification')
@patch('auto_unlocker.send_telegram_message')
@patch('auto_unlocker.ttlock_api.unlock_lock')
def test_executor_all_retries_fail(mock_unlock, mock_send_msg, mock_send_email, mock_sleep, mock_logger):
    """
    Проверяет, что при 10 неудачных попытках отправляются все уведомления.
    """
    mock_unlock.return_value = {"errcode": 1, "errmsg": "critical fail"}

    result = auto_unlocker.execute_lock_action_with_retries(
        auto_unlocker.ttlock_api.unlock_lock, 'token', 'lock_id', 'открытия', 'открыт', 'открытие замка'
    )

    assert result is False
    assert mock_unlock.call_count == 10
    # 10 сообщений об ошибках + 1 сообщение после 5-й попытки + 1 финальное
    assert mock_send_msg.call_count == 12
    # 1 email после 5-й попытки + 1 финальный
    assert mock_send_email.call_count == 2

# --- Тесты для main() ---

@patch('time.sleep', side_effect=InterruptedError) # Прерываем бесконечный цикл
@patch('auto_unlocker.resolve_lock_id', return_value='resolved_lock_id')
@patch('auto_unlocker.ttlock_api.get_token', return_value='test_token')
@patch('schedule.every')
def test_main_schedules_jobs(mock_every, mock_get_token, mock_resolve_lock, mock_sleep, mock_config, mock_logger):
    """
    Проверяет, что main() корректно настраивает расписание.
    """
    mock_day = MagicMock()
    mock_every.return_value = mock_day
    with patch('auto_unlocker.load_config', return_value=mock_config):
        with pytest.raises(InterruptedError):
            auto_unlocker.main()

    # Проверяем, что задачи запланированы
    assert mock_every.call_count > 0
    # Проверяем, что для Пн запланировано 1 открытие и 2 задачи для перерыва
    # (открытие в 09:00, закрытие в 13:00, открытие в 14:00)
    assert mock_day.monday.at.call_count == 3
    mock_day.monday.at.assert_has_calls([
        call('09:00'), call('13:00'), call('14:00')
    ], any_order=True)
    # Проверяем, что для Вт запланировано только открытие
    assert mock_day.tuesday.at.call_count == 1
    mock_day.tuesday.at.assert_called_with('10:00')

@patch('time.sleep', side_effect=InterruptedError)
@patch('auto_unlocker.resolve_lock_id', return_value='resolved_lock_id')
@patch('auto_unlocker.ttlock_api.get_token', return_value='test_token')
@patch('schedule.every')
def test_main_schedule_disabled(mock_every, mock_get_token, mock_resolve_lock, mock_sleep, mock_config, mock_logger):
    """
    Проверяет, что main() не планирует задачи, если расписание отключено.
    """
    mock_config['schedule_enabled'] = False
    with patch('auto_unlocker.load_config', return_value=mock_config):
        with pytest.raises(InterruptedError):
            auto_unlocker.main()
    mock_every.assert_called_once_with(10) # Только для heartbeat
