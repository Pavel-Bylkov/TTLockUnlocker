import pytest
import telegram_bot
import os
import json
import types
from unittest.mock import patch, MagicMock, AsyncMock
from telegram import Update, Message, Chat, User
from telegram.ext import ContextTypes

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
def mock_update():
    update = MagicMock(spec=Update)
    update.effective_chat = MagicMock(spec=Chat)
    update.effective_chat.id = 123456
    update.message = MagicMock(spec=Message)
    update.message.chat_id = 123456
    update.message.text = "test message"
    return update

@pytest.fixture
def mock_context():
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {}
    return context

def test_load_and_save_config(tmp_path):
    config = {"timezone": "Europe/Moscow", "schedule_enabled": False}
    config_path = tmp_path / "config.json"
    telegram_bot.CONFIG_PATH = str(config_path)
    telegram_bot.save_config(config)
    loaded = telegram_bot.load_config()
    assert loaded["timezone"] == "Europe/Moscow"
    assert loaded["schedule_enabled"] is False

def test_is_authorized_true(monkeypatch):
    telegram_bot.AUTHORIZED_CHAT_ID = '123'
    class DummyUpdate:
        class Chat:
            def __init__(self, id):
                self.id = id
        def __init__(self, chat_id):
            self.effective_chat = self.Chat(chat_id)
    update = DummyUpdate('123')
    assert telegram_bot.is_authorized(update)

def test_is_authorized_false(monkeypatch):
    telegram_bot.AUTHORIZED_CHAT_ID = '123'
    class DummyUpdate:
        class Chat:
            def __init__(self, id):
                self.id = id
        def __init__(self, chat_id):
            self.effective_chat = self.Chat(chat_id)
    update = DummyUpdate('456')
    assert not telegram_bot.is_authorized(update)

def test_send_telegram_message(monkeypatch):
    called = {}
    def fake_post(url, data, timeout):
        called['url'] = url
        called['data'] = data
        return type('Resp', (), {'status_code': 200})()
    monkeypatch.setattr('requests.post', fake_post)
    telegram_bot.BOT_TOKEN = 'token'
    telegram_bot.send_telegram_message('token', 123, 'test')
    assert called['url'].startswith('https://api.telegram.org/bot')
    assert called['data']['chat_id'] == 123
    assert called['data']['text'] == 'test'

class DummyMessage:
    def __init__(self):
        self.text = ''
        self.chat_id = 123
        self.replies = []
    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))

class DummyUpdate:
    def __init__(self, text=None, chat_id=123):
        self.message = DummyMessage()
        self.message.text = text or ''
        self.effective_chat = types.SimpleNamespace(id=chat_id)

class DummyContext:
    def __init__(self):
        self.user_data = {}

@pytest.mark.asyncio
async def test_start():
    update = DummyUpdate()
    context = DummyContext()
    await telegram_bot.start(update, context)
    assert any("Доступные команды" in r[0] for r in update.message.replies)

@pytest.mark.asyncio
async def test_setchat():
    update = DummyUpdate()
    context = DummyContext()
    res = await telegram_bot.setchat(update, context)
    assert res == telegram_bot.ASK_CODEWORD
    assert any("кодовое слово" in r[0].lower() for r in update.message.replies)

@pytest.mark.asyncio
async def test_check_codeword(monkeypatch):
    update = DummyUpdate(text=telegram_bot.CODEWORD)
    context = DummyContext()
    res = await telegram_bot.check_codeword(update, context)
    assert res == telegram_bot.CONFIRM_CHANGE
    update2 = DummyUpdate(text="wrongword")
    context2 = DummyContext()
    res2 = await telegram_bot.check_codeword(update2, context2)
    assert res2 == types.SimpleNamespace.END if hasattr(types.SimpleNamespace, 'END') else telegram_bot.ConversationHandler.END

@pytest.mark.asyncio
async def test_status(monkeypatch):
    update = DummyUpdate()
    context = DummyContext()
    monkeypatch.setattr(telegram_bot, 'is_authorized', lambda u: True)
    monkeypatch.setattr(telegram_bot, 'load_config', lambda: {"timezone": "Asia/Novosibirsk", "schedule_enabled": True, "open_times": {}, "breaks": {}})
    monkeypatch.setattr(telegram_bot, 'AUTO_UNLOCKER_CONTAINER', 'auto_unlocker_1')
    monkeypatch.setattr(telegram_bot, 'os', telegram_bot.os)
    await telegram_bot.status(update, context)
    assert any("Статус расписания" in r[0] for r in update.message.replies)

@pytest.mark.asyncio
async def test_enable_disable_schedule(monkeypatch):
    update = DummyUpdate()
    context = DummyContext()
    monkeypatch.setattr(telegram_bot, 'is_authorized', lambda u: True)
    monkeypatch.setattr(telegram_bot, 'load_config', lambda: {"timezone": "Asia/Novosibirsk", "schedule_enabled": True, "open_times": {}, "breaks": {}})
    monkeypatch.setattr(telegram_bot, 'save_config', lambda cfg: None)
    async def fake_restart(*a, **kw):
        update.message.replies.append(("FAKE RESTART", {}))
    monkeypatch.setattr(telegram_bot, 'restart_auto_unlocker_and_notify', fake_restart)
    await telegram_bot.enable_schedule(update, context)
    await telegram_bot.disable_schedule(update, context)
    assert any("FAKE RESTART" in r[0] for r in update.message.replies)

@pytest.mark.asyncio
async def test_open_close_lock(monkeypatch):
    update = DummyUpdate()
    context = DummyContext()
    monkeypatch.setattr(telegram_bot, 'is_authorized', lambda u: True)
    monkeypatch.setattr(telegram_bot, 'TTLOCK_LOCK_ID', 'lockid')
    monkeypatch.setattr(telegram_bot.ttlock_api, 'get_token', lambda logger: 'token')
    monkeypatch.setattr(telegram_bot.ttlock_api, 'unlock_lock', lambda token, lock_id, logger: {"errcode": 0, "attempt": 1})
    monkeypatch.setattr(telegram_bot.ttlock_api, 'lock_lock', lambda token, lock_id, logger: {"errcode": 0, "attempt": 1})
    await telegram_bot.open_lock(update, context)
    await telegram_bot.close_lock(update, context)
    assert any("открыт" in r[0] or "закрыт" in r[0] for r in update.message.replies)

@pytest.mark.asyncio
async def test_settimezone(monkeypatch):
    update = DummyUpdate()
    context = DummyContext()
    monkeypatch.setattr(telegram_bot, 'is_authorized', lambda u: True)
    res = await telegram_bot.settimezone(update, context)
    assert res == telegram_bot.SET_TIMEZONE
    assert any("часовой пояс" in r[0].lower() for r in update.message.replies)

def test_load_config_file_not_found():
    """Тест загрузки конфигурации при отсутствии файла"""
    with patch('builtins.open', MagicMock(side_effect=FileNotFoundError())):
        config = telegram_bot.load_config()
        assert config == {}

def test_load_config_invalid_json():
    """Тест загрузки конфигурации при некорректном JSON"""
    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = "invalid json"
    with patch('builtins.open', return_value=mock_file):
        config = telegram_bot.load_config()
        assert config == {}

def test_load_config_success():
    """Тест успешной загрузки конфигурации"""
    test_config = {
        "timezone": "Europe/Moscow",
        "schedule_enabled": True,
        "open_times": {"monday": "09:00"},
        "breaks": {"monday": ["13:00-14:00"]}
    }
    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = json.dumps(test_config)
    with patch('builtins.open', return_value=mock_file):
        config = telegram_bot.load_config()
        assert config == test_config

def test_save_config():
    """Тест сохранения конфигурации"""
    test_config = {
        "timezone": "Europe/Moscow",
        "schedule_enabled": True
    }
    mock_file = MagicMock()
    with patch('builtins.open', return_value=mock_file) as mock_open:
        telegram_bot.save_config(test_config)
        mock_open.assert_called_once()

        # Получаем все вызовы write
        write_calls = mock_file.__enter__.return_value.write.call_args_list
        # Объединяем все части в одну строку
        actual_content = ''.join(call.args[0] for call in write_calls)
        # Сравниваем с ожидаемым JSON
        expected_json = json.dumps(test_config, indent=2)
        assert actual_content == expected_json

def test_is_authorized():
    """Тест проверки авторизации"""
    update = MagicMock(spec=Update)
    update.effective_chat = MagicMock(spec=Chat)

    # Тест с правильным chat_id
    update.effective_chat.id = 123456
    telegram_bot.AUTHORIZED_CHAT_ID = '123456'
    assert telegram_bot.is_authorized(update) is True

    # Тест с неправильным chat_id
    update.effective_chat.id = 654321
    assert telegram_bot.is_authorized(update) is False

@pytest.mark.asyncio
async def test_start_command(mock_update, mock_context):
    """Тест команды /start"""
    with patch('telegram_bot.menu', new_callable=AsyncMock) as mock_menu:
        await telegram_bot.start(mock_update, mock_context)
        mock_menu.assert_called_once_with(mock_update, mock_context)

@pytest.mark.asyncio
async def test_setchat_command(mock_update, mock_context):
    """Тест команды /setchat"""
    await telegram_bot.setchat(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once_with("Введите кодовое слово:")
    assert mock_context.user_data == {}

@pytest.mark.asyncio
async def test_check_codeword_correct(mock_update, mock_context):
    """Тест проверки правильного кодового слова"""
    mock_update.message.text = "test_codeword"
    telegram_bot.CODEWORD = "test_codeword"
    result = await telegram_bot.check_codeword(mock_update, mock_context)
    assert result == telegram_bot.CONFIRM_CHANGE
    assert mock_context.user_data['new_chat_id'] == 123456
    mock_update.message.reply_text.assert_called_once_with(
        "Кодовое слово верно! Подтвердите смену получателя (да/нет):"
    )

@pytest.mark.asyncio
async def test_check_codeword_incorrect(mock_update, mock_context):
    """Тест проверки неправильного кодового слова"""
    mock_update.message.text = "wrong_codeword"
    result = await telegram_bot.check_codeword(mock_update, mock_context)
    assert result == telegram_bot.ConversationHandler.END
    mock_update.message.reply_text.assert_called_once_with("Неверное кодовое слово.")

@pytest.mark.asyncio
async def test_confirm_change_yes(mock_update, mock_context):
    """Тест подтверждения смены chat_id (да)"""
    mock_update.message.text = "да"
    mock_context.user_data['new_chat_id'] = 123456

    with patch('builtins.open', MagicMock()) as mock_file, \
         patch('telegram_bot.restart_auto_unlocker_and_notify', new_callable=AsyncMock) as mock_restart:

        result = await telegram_bot.confirm_change(mock_update, mock_context)
        assert result == telegram_bot.ConversationHandler.END
        mock_restart.assert_called_once()

@pytest.mark.asyncio
async def test_confirm_change_no(mock_update, mock_context):
    """Тест подтверждения смены chat_id (нет)"""
    mock_update.message.text = "нет"
    result = await telegram_bot.confirm_change(mock_update, mock_context)
    assert result == telegram_bot.ConversationHandler.END
    mock_update.message.reply_text.assert_called_once_with("Операция отменена.")

@pytest.mark.asyncio
async def test_status_command(mock_update, mock_context):
    """Тест команды /status"""
    telegram_bot.AUTHORIZED_CHAT_ID = '123456'
    with patch('telegram_bot.load_config', return_value={
        "timezone": "Europe/Moscow",
        "schedule_enabled": True,
        "open_times": {"monday": "09:00"},
        "breaks": {"monday": ["13:00-14:00"]}
    }), \
    patch('docker.from_env') as mock_docker:
        mock_container = MagicMock()
        mock_container.status = "running"
        mock_docker.return_value.containers.get.return_value = mock_container

        await telegram_bot.status(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        assert "работает" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_menu_command(mock_update, mock_context):
    """Тест команды /menu"""
    telegram_bot.AUTHORIZED_CHAT_ID = '123456'
    await telegram_bot.menu(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    assert "Доступные команды" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_settimezone_command(mock_update, mock_context):
    """Тест команды /settimezone"""
    telegram_bot.AUTHORIZED_CHAT_ID = '123456'
    result = await telegram_bot.settimezone(mock_update, mock_context)
    assert result == telegram_bot.SET_TIMEZONE
    mock_update.message.reply_text.assert_called_once()
    assert "часовой пояс" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_settimezone_apply(mock_update, mock_context):
    """Тест применения часового пояса"""
    telegram_bot.AUTHORIZED_CHAT_ID = '123456'
    mock_update.message.text = "Europe/Moscow"

    with patch('telegram_bot.load_config', return_value={}), \
         patch('telegram_bot.save_config') as mock_save, \
         patch('telegram_bot.restart_auto_unlocker_and_notify', new_callable=AsyncMock) as mock_restart:

        result = await telegram_bot.settimezone_apply(mock_update, mock_context)
        assert result == telegram_bot.ConversationHandler.END
        mock_save.assert_called_once()
        mock_restart.assert_called_once()

@pytest.mark.asyncio
async def test_settime_flow(mock_update, mock_context):
    """Тест полного процесса настройки времени"""
    telegram_bot.AUTHORIZED_CHAT_ID = '123456'

    # Тест начала настройки времени
    result = await telegram_bot.settime_start(mock_update, mock_context)
    assert result == telegram_bot.SETTIME_DAY
    mock_update.message.reply_text.assert_called_once()
    assert "день недели" in mock_update.message.reply_text.call_args[0][0]

    # Сброс мока для следующего теста
    mock_update.message.reply_text.reset_mock()

    # Тест выбора дня
    mock_update.message.text = "Пн"
    with patch('telegram_bot.DAYS_MAPPING', {'Пн': 'monday'}):
        result = await telegram_bot.settime_day(mock_update, mock_context)
        assert result == telegram_bot.SETTIME_VALUE
        assert mock_context.user_data['day'] == "monday"

    # Сброс мока для следующего теста
    mock_update.message.reply_text.reset_mock()

    # Тест установки времени
    mock_update.message.text = "09:00"
    with patch('telegram_bot.load_config', return_value={}), \
         patch('telegram_bot.save_config') as mock_save, \
         patch('telegram_bot.restart_auto_unlocker_and_notify', new_callable=AsyncMock) as mock_restart:

        result = await telegram_bot.settime_value(mock_update, mock_context)
        assert result == telegram_bot.ConversationHandler.END
        mock_save.assert_called_once()
        mock_restart.assert_called_once()

@pytest.mark.asyncio
async def test_setbreak_flow(mock_update, mock_context):
    """Тест полного процесса настройки перерывов"""
    telegram_bot.AUTHORIZED_CHAT_ID = '123456'

    # Тест начала настройки перерывов
    result = await telegram_bot.setbreak_start(mock_update, mock_context)
    assert result == telegram_bot.SETBREAK_DAY
    mock_update.message.reply_text.assert_called_once()
    assert "день недели" in mock_update.message.reply_text.call_args[0][0]

    # Сброс мока для следующего теста
    mock_update.message.reply_text.reset_mock()

    # Тест выбора дня
    mock_update.message.text = "Пн"
    with patch('telegram_bot.DAYS_MAPPING', {'Пн': 'monday'}):
        result = await telegram_bot.setbreak_day(mock_update, mock_context)
        assert result == telegram_bot.SETBREAK_ACTION
        assert mock_context.user_data['day'] == "monday"

    # Сброс мока для следующего теста
    mock_update.message.reply_text.reset_mock()

    # Тест выбора действия
    mock_update.message.text = "Добавить"
    result = await telegram_bot.setbreak_action(mock_update, mock_context)
    assert result == telegram_bot.SETBREAK_ADD

    # Сброс мока для следующего теста
    mock_update.message.reply_text.reset_mock()

    # Тест добавления перерыва
    mock_update.message.text = "13:00-14:00"
    with patch('telegram_bot.load_config', return_value={}), \
         patch('telegram_bot.save_config') as mock_save, \
         patch('telegram_bot.restart_auto_unlocker_and_notify', new_callable=AsyncMock) as mock_restart:

        result = await telegram_bot.setbreak_add(mock_update, mock_context)
        assert result == telegram_bot.ConversationHandler.END
        mock_save.assert_called_once()
        mock_restart.assert_called_once()

@pytest.mark.asyncio
async def test_open_close_lock(mock_update, mock_context):
    """Тест команд открытия/закрытия замка"""
    telegram_bot.AUTHORIZED_CHAT_ID = '123456'

    with patch('telegram_bot.ttlock_api.get_token', return_value='test_token'), \
         patch('telegram_bot.ttlock_api.unlock_lock', return_value={'errcode': 0}), \
         patch('telegram_bot.ttlock_api.lock_lock', return_value={'errcode': 0}):

        # Тест открытия замка
        await telegram_bot.open_lock(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        assert "открыт" in mock_update.message.reply_text.call_args[0][0]

        # Сброс мока для следующего теста
        mock_update.message.reply_text.reset_mock()

        # Тест закрытия замка
        await telegram_bot.close_lock(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        assert "закрыт" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_enable_disable_schedule(mock_update, mock_context):
    """Тест команд включения/выключения расписания"""
    telegram_bot.AUTHORIZED_CHAT_ID = '123456'

    with patch('telegram_bot.load_config', return_value={}), \
         patch('telegram_bot.save_config') as mock_save, \
         patch('telegram_bot.restart_auto_unlocker_and_notify', new_callable=AsyncMock) as mock_restart:

        # Тест включения расписания
        await telegram_bot.enable_schedule(mock_update, mock_context)
        mock_save.assert_called_once()
        mock_restart.assert_called_once()

        # Сброс моков для следующего теста
        mock_save.reset_mock()
        mock_restart.reset_mock()

        # Тест выключения расписания
        await telegram_bot.disable_schedule(mock_update, mock_context)
        mock_save.assert_called_once()
        mock_restart.assert_called_once()

@pytest.mark.asyncio
async def test_restart_auto_unlocker_cmd(mock_update, mock_context):
    """Тест команды перезапуска сервиса"""
    telegram_bot.AUTHORIZED_CHAT_ID = '123456'

    with patch('docker.from_env') as mock_docker:
        mock_container = MagicMock()
        mock_docker.return_value.containers.get.return_value = mock_container

        await telegram_bot.restart_auto_unlocker_cmd(mock_update, mock_context)
        mock_container.restart.assert_called_once()
        mock_update.message.reply_text.assert_called_once()
        assert "перезапущен" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_logs_command(mock_update, mock_context):
    """Тест команды просмотра логов"""
    telegram_bot.AUTHORIZED_CHAT_ID = '123456'

    test_log = b"Test log message"
    with patch('docker.from_env') as mock_docker, \
         patch('telegram_bot.AUTO_UNLOCKER_CONTAINER', 'test_container'):
        mock_container = MagicMock()
        mock_container.logs.return_value = test_log
        mock_docker.return_value.containers.get.return_value = mock_container

        await telegram_bot.logs(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        response_text = mock_update.message.reply_text.call_args[0][0]
        assert "Последние логи сервиса" in response_text
        assert test_log.decode() in response_text

