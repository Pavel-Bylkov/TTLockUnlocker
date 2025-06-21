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
import importlib

@pytest.fixture(autouse=True)
def setup_and_reload(monkeypatch):
    """Set up environment variables and reload the module for each test."""
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test_token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '123456')
    monkeypatch.setenv('TTLOCK_LOCK_ID', 'test_lock_id')
    monkeypatch.setenv('CONFIG_PATH', 'config.json')
    monkeypatch.setenv("TTLOCK_CLIENT_ID", "test_client_id")
    monkeypatch.setenv("TTLOCK_CLIENT_SECRET", "test_client_secret")
    monkeypatch.setenv("TTLOCK_USERNAME", "test_username")
    monkeypatch.setenv("TTLOCK_PASSWORD", "test_password")
    monkeypatch.setenv("EMAIL_TO", "test@example.com")
    monkeypatch.setenv("SMTP_SERVER", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "password")

    # Reload modules to apply the new environment variables
    importlib.reload(auto_unlocker)
    importlib.reload(telegram_utils)

    # Clear the scheduler before each test
    schedule.clear()

    # Reset global variables in the module
    auto_unlocker.TIME_SHIFT = None

@pytest.fixture
def mock_logger():
    """Fixture for a mock logger."""
    with patch('auto_unlocker.logger', MagicMock()) as mock_log:
        yield mock_log

@pytest.fixture
def mock_config():
    """Fixture for a test configuration."""
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
            "Вт": [], "Ср": [], "Чт": [], "Пт": [], "Сб": [], "Вс": []
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

@pytest.fixture
def mock_get_now():
    """Fixture to mock ttlock_api.get_now()"""
    # Monday, 09:00
    mock_dt = datetime(2025, 6, 16, 9, 0)
    with patch('ttlock_api.get_now', return_value=mock_dt) as mock_time:
        yield mock_time

@patch('telegram_utils.send_telegram_message')
def test_resolve_lock_id_from_env(mock_send_msg, monkeypatch, mock_logger):
    """Test that lock_id is resolved from environment variables."""
    monkeypatch.setenv('TTLOCK_LOCK_ID', 'env_lock_id')
    importlib.reload(auto_unlocker)
    with patch('ttlock_api.list_locks') as mock_list_locks:
        lock_id = auto_unlocker.resolve_lock_id('test_token')
        assert lock_id == 'env_lock_id'
        mock_list_locks.assert_not_called()
        # It sends a telegram message
        mock_send_msg.assert_called_once()

@patch('telegram_utils.send_telegram_message')
def test_resolve_lock_id_from_api(mock_send_msg, monkeypatch, mock_logger):
    """Test that lock_id is resolved from the API if not in env."""
    monkeypatch.delenv('TTLOCK_LOCK_ID', raising=False)
    os.environ.pop('TTLOCK_LOCK_ID', None) # Make sure it is gone
    importlib.reload(auto_unlocker) # reload to pick up changed env
    with patch('ttlock_api.list_locks') as mock_list_locks:
        mock_list_locks.return_value = [{'lockId': 'api_lock_id', 'lockName': 'Test Lock'}]

        lock_id = auto_unlocker.resolve_lock_id('test_token')

        assert lock_id == 'api_lock_id'
        mock_list_locks.assert_called_once_with('test_token')
        assert mock_send_msg.call_count == 1

@patch('telegram_utils.send_telegram_message')
@patch('auto_unlocker.ttlock_api.unlock_lock')
@patch('auto_unlocker.ttlock_api.get_token', return_value='test_token')
def test_job_success_on_time(mock_get_token, mock_unlock, mock_send, mock_config, mock_get_now, mock_logger):
    """Test successful execution of the job to unlock the lock."""
    mock_unlock.return_value = {"errcode": 0}
    with patch('telegram_utils.load_config', return_value=mock_config):
        auto_unlocker.job()

        mock_unlock.assert_called_once_with('test_token', 'test_lock_id', mock_logger)
        mock_send.assert_called_once_with(
            'test_token', '123456',
            '✅ <b>Замок успешно открыт (попытка 1)</b>',
            mock_logger
        )

def test_job_not_unlock_time(mock_config, mock_get_now, mock_logger):
    """Test that job does nothing if it's not the scheduled time."""
    # It's Monday 09:00, but let's change open time to 10:00
    mock_config["open_times"]["Пн"] = "10:00"
    with patch('telegram_utils.load_config', return_value=mock_config), \
         patch('auto_unlocker.ttlock_api.unlock_lock') as mock_unlock:

        auto_unlocker.job()
        mock_unlock.assert_not_called()

def test_job_schedule_disabled(mock_config, mock_get_now, mock_logger):
    """Test that job does nothing if the schedule is disabled."""
    mock_config["schedule_enabled"] = False
    with patch('telegram_utils.load_config', return_value=mock_config), \
         patch('auto_unlocker.ttlock_api.unlock_lock') as mock_unlock:

        auto_unlocker.job()
        mock_unlock.assert_not_called()

def test_job_during_break(mock_config, mock_logger):
    """Test that job does nothing during a break."""
    mock_config["open_times"]["Пн"] = "13:30"
    mock_config["breaks"]["Пн"] = ["13:00-14:00"]

    # Monday, 13:30
    mock_dt = datetime(2025, 6, 16, 13, 30)
    with patch('ttlock_api.get_now', return_value=mock_dt), \
         patch('telegram_utils.load_config', return_value=mock_config), \
         patch('auto_unlocker.ttlock_api.unlock_lock') as mock_unlock:

        auto_unlocker.job()
        mock_unlock.assert_not_called()

@patch('telegram_utils.send_email_notification')
@patch('telegram_utils.send_telegram_message')
@patch('auto_unlocker.ttlock_api.unlock_lock')
@patch('auto_unlocker.ttlock_api.get_token', return_value='test_token')
@patch('time.sleep')
def test_job_full_retry_failure(mock_sleep, mock_get_token, mock_unlock, mock_send, mock_send_email, mock_config, mock_get_now, mock_logger):
    """Test the retry logic when unlock fails all 10 times."""
    mock_unlock.return_value = {"errcode": 1, "errmsg": "Failed"}
    with patch('telegram_utils.load_config', return_value=mock_config):
        auto_unlocker.job()

        assert mock_unlock.call_count == 10
        # 10 error messages + 1 for 3 fails + 1 for 5 fails (email) + 1 final error
        assert mock_send.call_count == 13
        mock_send_email.assert_called_once()
        # 30s, 60s, 5min, 10min, 5 * 15min
        assert mock_sleep.call_count == 2 + 5

@patch('telegram_utils.send_telegram_message')
@patch('auto_unlocker.ttlock_api.unlock_lock')
@patch('auto_unlocker.ttlock_api.get_token', return_value='test_token')
@patch('time.sleep')
def test_job_retry_success(mock_sleep, mock_get_token, mock_unlock, mock_send, mock_config, mock_get_now, mock_logger):
    """Test successful unlock on the 2nd retry attempt."""
    mock_unlock.side_effect = [
        {"errcode": 1, "errmsg": "Failed"}, # 1st fails
        {"errcode": 0}                     # 2nd succeeds
    ]
    with patch('telegram_utils.load_config', return_value=mock_config):
        auto_unlocker.job()

        assert mock_unlock.call_count == 2
        # 1 error message, 1 success message
        assert mock_send.call_count == 2
        mock_sleep.assert_called_once_with(30)

@patch('schedule.every')
def test_main_schedules_jobs_correctly(mock_every, mock_config, mock_logger):
    """Test that main() sets up schedule correctly based on config."""
    mock_config["open_times"]["Сб"] = "12:00" # Add a saturday job
    mock_config["breaks"]["Пн"] = ["13:00-14:00"]

    mock_day = MagicMock()
    # to allow chaining like schedule.every().monday...
    mock_every.return_value = mock_day

    with patch('telegram_utils.load_config', return_value=mock_config):
        # We need to interrupt the infinite loop in main
        with patch('time.sleep', side_effect=InterruptedError):
            with pytest.raises(InterruptedError):
                auto_unlocker.main()

    # Check job scheduling
    calls = mock_day.monday.at.call_args_list
    assert call('09:00') in calls

    # Check break scheduling for Monday
    assert call('13:00') in calls # close
    assert call('14:00') in calls # reopen

    mock_day.tuesday.at.assert_called_with("09:00")
    mock_day.saturday.at.assert_called_with("12:00")
    # Sunday has time=None, so it shouldn't be scheduled
    mock_day.sunday.at.assert_not_called()

    # Check heartbeat
    mock_day.hour.do.assert_called_with(auto_unlocker.log_heartbeat)

def test_main_with_schedule_disabled(mock_config, mock_logger):
    """Test that main() loop doesn't schedule jobs when disabled."""
    mock_config["schedule_enabled"] = False

    with patch('telegram_utils.load_config', return_value=mock_config), \
         patch('schedule.every') as mock_every, \
         patch('time.sleep', side_effect=InterruptedError):

        with pytest.raises(InterruptedError):
            auto_unlocker.main()

    mock_every.assert_not_called()
