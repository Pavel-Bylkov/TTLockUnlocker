import pytest
import telegram_bot
import os
import json
import types
from unittest.mock import patch, MagicMock, AsyncMock, mock_open
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

@pytest.fixture
def mock_send_message():
    """
    Фикстура для перехвата отправки сообщений в тестах.
    """
    sent_messages = []

    async def mock_send(update, text, parse_mode="HTML", **kwargs):
        sent_messages.append(text)
        return None

    return mock_send, sent_messages

@pytest.fixture
def mock_restart_and_notify():
    """
    Фикстура для мока функции restart_auto_unlocker_and_notify.
    """
    async def mock_restart(update, logger, message_success, message_error):
        await send_message(update, message_success)
        return None

    return mock_restart

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
async def test_open_close_lock(mock_send_message):
    """
    Тест команды /open.
    """
    mock_send, sent_messages = mock_send_message

    # Создаем мок для update
    update = MagicMock()
    update.effective_chat.id = 123456

    # Мокаем функции
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.TTLOCK_LOCK_ID', 'test_lock_id'), \
         patch('telegram_bot.ttlock_api.get_token', return_value='test_token'), \
         patch('telegram_bot.ttlock_api.unlock_lock', return_value={'errcode': 0, 'attempt': 1}), \
         patch('telegram_bot.send_message', mock_send):
        # Вызываем функцию
        await telegram_bot.open_lock(update, None)

        # Проверяем, что сообщение было отправлено
        assert len(sent_messages) == 1
        assert "Замок <b>открыт</b>" in sent_messages[0]

@pytest.mark.asyncio
async def test_setchat_command(mock_send_message):
    """Тест команды /setchat"""
    mock_send, sent_messages = mock_send_message

    update = MagicMock()
    update.effective_chat.id = 123456

    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.send_message', mock_send):
        await telegram_bot.setchat(update, None)
        assert len(sent_messages) == 1
        assert "Введите кодовое слово" in sent_messages[0]

@pytest.mark.asyncio
async def test_check_codeword_correct(mock_send_message):
    """Тест проверки правильного кодового слова"""
    mock_send, sent_messages = mock_send_message

    update = MagicMock()
    update.effective_chat.id = 123456
    update.message.text = "test_codeword"
    update.message.chat_id = 123456  # Добавляем chat_id

    context = MagicMock()
    context.user_data = {}

    telegram_bot.CODEWORD = "test_codeword"

    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.send_message', mock_send):
        result = await telegram_bot.check_codeword(update, context)
        assert result == telegram_bot.CONFIRM_CHANGE
        assert context.user_data['new_chat_id'] == 123456
        assert len(sent_messages) == 1
        assert "Кодовое слово верно" in sent_messages[0]

@pytest.mark.asyncio
async def test_check_codeword_incorrect(mock_send_message):
    """Тест проверки неправильного кодового слова"""
    mock_send, sent_messages = mock_send_message

    update = MagicMock()
    update.effective_chat.id = 123456
    update.message.text = "wrong_codeword"

    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.send_message', mock_send):
        result = await telegram_bot.check_codeword(update, None)
        assert result == telegram_bot.ConversationHandler.END
        assert len(sent_messages) == 1
        assert "Неверное кодовое слово" in sent_messages[0]

@pytest.mark.asyncio
async def test_confirm_change_no(mock_send_message):
    """Тест подтверждения смены chat_id (нет)"""
    mock_send, sent_messages = mock_send_message

    update = MagicMock()
    update.effective_chat.id = 123456
    update.message.text = "нет"

    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.send_message', mock_send):
        result = await telegram_bot.confirm_change(update, None)
        assert result == telegram_bot.ConversationHandler.END
        assert len(sent_messages) == 1
        assert "Операция отменена" in sent_messages[0]

@pytest.mark.asyncio
async def test_settime_flow(mock_send_message):
    """
    Тест полного флоу настройки времени.
    """
    mock_send, sent_messages = mock_send_message

    # Создаем мок для update и context
    update = MagicMock()
    update.effective_chat.id = 123456
    update.message.text = "Пн"  # Выбор дня недели

    context = MagicMock()
    context.user_data = {}

    # Мокаем функции
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.send_message', mock_send), \
         patch('telegram_bot.load_config', return_value={}), \
         patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify'), \
         patch('telegram_bot.DAY_MAP', {'Пн': 'monday'}), \
         patch('telegram_bot.DAYS_RU', ['Пн']):

        # Вызываем функцию выбора дня
        result = await telegram_bot.settime_day(update, context)
        assert result == telegram_bot.SETTIME_VALUE
        assert len(sent_messages) == 1
        assert "Введите время открытия" in sent_messages[0]

        # Сбрасываем список сообщений
        sent_messages.clear()

        # Устанавливаем время
        update.message.text = "09:00"
        result = await telegram_bot.settime_value(update, context)
        assert result == telegram_bot.SETTIME_DAY
        assert len(sent_messages) == 1
        assert "Хотите изменить время для другого дня" in sent_messages[0]

@pytest.mark.asyncio
async def test_setbreak_flow(mock_send_message):
    """
    Тест полного флоу настройки перерывов.
    """
    mock_send, sent_messages = mock_send_message

    # Создаем мок для update и context
    update = MagicMock()
    update.effective_chat.id = 123456
    update.message.text = "Пн"  # Выбор дня недели

    context = MagicMock()
    context.user_data = {}

    # Мокаем функции
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.send_message', mock_send), \
         patch('telegram_bot.load_config', return_value={}), \
         patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify'), \
         patch('telegram_bot.DAY_MAP', {'Пн': 'monday'}), \
         patch('telegram_bot.DAYS_RU', ['Пн']):

        # Вызываем функцию выбора дня
        result = await telegram_bot.setbreak_day(update, context)
        assert result == telegram_bot.SETBREAK_ACTION
        assert len(sent_messages) == 1
        assert "Текущие перерывы" in sent_messages[0]

        # Сбрасываем список сообщений
        sent_messages.clear()

        # Выбираем действие "Добавить"
        update.message.text = "Добавить"
        result = await telegram_bot.setbreak_action(update, context)
        assert result == telegram_bot.SETBREAK_ADD
        assert len(sent_messages) == 1
        assert "Введите интервал перерыва" in sent_messages[0]

        # Сбрасываем список сообщений
        sent_messages.clear()

        # Добавляем перерыв
        update.message.text = "13:00-14:00"
        result = await telegram_bot.setbreak_add(update, context)
        assert result == telegram_bot.SETBREAK_DAY
        assert len(sent_messages) == 1
        assert "Пожалуйста, выберите день из списка" in sent_messages[0]

@pytest.mark.asyncio
async def test_settimezone_flow(mock_send_message, mock_restart_and_notify):
    """
    Тест полного флоу настройки часового пояса.
    """
    mock_send, sent_messages = mock_send_message

    # Создаем мок для update
    update = MagicMock()
    update.effective_chat.id = 123456
    update.message.text = "Europe/Moscow"  # Ввод часового пояса

    # Мокаем функции
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.send_message', mock_send), \
         patch('telegram_bot.load_config', return_value={}), \
         patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', mock_restart_and_notify), \
         patch('pytz.timezone') as mock_tz:

        # Вызываем функцию
        result = await telegram_bot.settimezone_apply(update, None)
        assert result == telegram_bot.ConversationHandler.END
        assert len(sent_messages) == 1
        assert "Часовой пояс изменён" in sent_messages[0]

@pytest.mark.asyncio
async def test_setchat_flow(mock_send_message, mock_restart_and_notify):
    """
    Тест полного флоу смены chat_id.
    """
    mock_send, sent_messages = mock_send_message

    # Создаем мок для update
    update = MagicMock()
    update.effective_chat.id = 123456
    update.message.text = "secretword"  # Ввод кодового слова
    update.message.chat_id = 123456  # Добавляем chat_id

    context = MagicMock()
    context.user_data = {}

    # Мокаем функции
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.send_message', mock_send), \
         patch('telegram_bot.CODEWORD', 'secretword'), \
         patch('builtins.open', mock_open(read_data='TELEGRAM_CHAT_ID=old_id\n')), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', mock_restart_and_notify):

        # Вызываем функцию проверки кодового слова
        result = await telegram_bot.check_codeword(update, context)
        assert result == telegram_bot.CONFIRM_CHANGE
        assert len(sent_messages) == 1
        assert "Кодовое слово верно" in sent_messages[0]

        # Сбрасываем список сообщений
        sent_messages.clear()

        # Подтверждаем смену
        update.message.text = "да"
        result = await telegram_bot.confirm_change(update, context)
        assert result == telegram_bot.ConversationHandler.END
        assert len(sent_messages) == 1
        assert "Получатель уведомлений изменён" in sent_messages[0]

@pytest.mark.asyncio
async def test_close_lock_command(mock_send_message):
    """
    Тест команды /close.
    """
    mock_send, sent_messages = mock_send_message

    # Создаем мок для update
    update = MagicMock()
    update.effective_chat.id = 123456

    # Мокаем функции
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.TTLOCK_LOCK_ID', 'test_lock_id'), \
         patch('telegram_bot.ttlock_api.get_token', return_value='test_token'), \
         patch('telegram_bot.ttlock_api.lock_lock', return_value={'errcode': 0, 'attempt': 1}), \
         patch('telegram_bot.send_message', mock_send):
        # Вызываем функцию
        await telegram_bot.close_lock(update, None)

        # Проверяем, что сообщение было отправлено
        assert len(sent_messages) == 1
        assert "Замок <b>закрыт</b>" in sent_messages[0]

@pytest.mark.asyncio
async def test_enable_schedule_command(mock_send_message, mock_restart_and_notify):
    """
    Тест команды /enable_schedule.
    """
    mock_send, sent_messages = mock_send_message

    # Создаем мок для update
    update = MagicMock()
    update.effective_chat.id = 123456

    # Мокаем функции
    with patch('telegram_bot.load_config', return_value={}), \
         patch('telegram_bot.save_config'), \
         patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.send_message', mock_send), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', mock_restart_and_notify):
        # Вызываем функцию
        await telegram_bot.enable_schedule(update, None)

        # Проверяем, что сообщение было отправлено
        assert len(sent_messages) == 1
        assert "Расписание включено" in sent_messages[0]

@pytest.mark.asyncio
async def test_disable_schedule_command(mock_send_message, mock_restart_and_notify):
    """
    Тест команды /disable_schedule.
    """
    mock_send, sent_messages = mock_send_message

    # Создаем мок для update
    update = MagicMock()
    update.effective_chat.id = 123456

    # Мокаем функции
    with patch('telegram_bot.load_config', return_value={}), \
         patch('telegram_bot.save_config'), \
         patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.send_message', mock_send), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', mock_restart_and_notify):
        # Вызываем функцию
        await telegram_bot.disable_schedule(update, None)

        # Проверяем, что сообщение было отправлено
        assert len(sent_messages) == 1
        assert "Расписание отключено" in sent_messages[0]

@pytest.mark.asyncio
async def test_logs_command(mock_send_message):
    """
    Тест команды /logs с успешным чтением логов.
    """
    mock_send, sent_messages = mock_send_message

    # Создаем тестовые логи
    test_logs = [
        "2024-02-20 10:00:00 INFO: Test log message 1",
        "2024-02-20 10:01:00 INFO: Test log message 2",
        "",  # Пустая строка
        "",  # Пустая строка
        "",  # Пустая строка
        "",  # Пустая строка
        "",  # Пустая строка
        "",  # Пустая строка
        "",  # Пустая строка
        "",  # Пустая строка
    ]

    # Создаем мок для update
    update = MagicMock()
    update.effective_chat.id = 123456

    # Мокаем функции
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.send_message', mock_send), \
         patch('builtins.open', mock_open(read_data='\n'.join(test_logs))):
        # Вызываем функцию
        await telegram_bot.logs(update, None)

        # Проверяем, что сообщение было отправлено
        assert len(sent_messages) == 1
        assert "Последние логи сервиса" in sent_messages[0]
        assert "Test log message 1" in sent_messages[0]
        assert "Test log message 2" in sent_messages[0]

@pytest.mark.asyncio
async def test_logs_command_with_days(mock_send_message):
    """
    Тест команды /logs с заменой дней недели.
    """
    mock_send, sent_messages = mock_send_message

    # Создаем тестовые логи с днями недели
    test_logs = [
        "2024-02-20 10:00:00 INFO: Test on monday",
        "2024-02-20 10:01:00 INFO: Test on tuesday",
        "",  # Пустая строка
        "",  # Пустая строка
        "",  # Пустая строка
        "",  # Пустая строка
        "",  # Пустая строка
        "",  # Пустая строка
        "",  # Пустая строка
        "",  # Пустая строка
    ]

    # Создаем мок для update
    update = MagicMock()
    update.effective_chat.id = 123456

    # Мокаем функции
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.send_message', mock_send), \
         patch('builtins.open', mock_open(read_data='\n'.join(test_logs))):
        # Вызываем функцию
        await telegram_bot.logs(update, None)

        # Проверяем, что сообщение было отправлено
        assert len(sent_messages) == 1
        assert "Последние логи сервиса" in sent_messages[0]
        assert "Понедельник" in sent_messages[0]
        assert "Вторник" in sent_messages[0]

@pytest.mark.asyncio
async def test_logs_command_file_not_found(mock_update, mock_context):
    """Тест команды просмотра логов, когда файл не найден"""
    telegram_bot.AUTHORIZED_CHAT_ID = '123456'

    with patch('os.path.exists', return_value=False):
        await telegram_bot.logs(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        response_text = mock_update.message.reply_text.call_args[0][0]
        assert "Последние логи сервиса" in response_text
        assert "Лог-файл не найден" in response_text

@pytest.mark.asyncio
async def test_logs_command_error(mock_update, mock_context):
    """Тест команды просмотра логов при ошибке чтения"""
    telegram_bot.AUTHORIZED_CHAT_ID = '123456'

    with patch('os.path.exists', return_value=True), \
         patch('builtins.open', MagicMock(side_effect=Exception("Test error"))):
        await telegram_bot.logs(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        response_text = mock_update.message.reply_text.call_args[0][0]
        assert "Последние логи сервиса" in response_text
        assert "Ошибка чтения логов" in response_text

