"""
Тесты для telegram_bot.py.
"""
import pytest
import telegram_bot
import os
import json
import types
from unittest.mock import patch, MagicMock, AsyncMock, mock_open
from telegram import Update, Message, Chat, User, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from typing import Dict, List, Any, Optional, Tuple, Generator

@pytest.fixture(autouse=True)
def setup_env() -> Generator[None, None, None]:
    """
    Фикстура для настройки переменных окружения перед каждым тестом.
    """
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

    # Мокаем pytz для тестов
    with patch('pytz.timezone', return_value=MagicMock()):
        yield

    # Восстанавливаем оригинальные значения
    for key, value in original_values.items():
        if value is not None:
            os.environ[key] = value
        elif key in os.environ:
            del os.environ[key]

@pytest.fixture
def mock_update() -> MagicMock:
    """
    Фикстура для создания мока объекта Update.

    Returns:
        MagicMock: Мок объекта Update
    """
    update = MagicMock(spec=Update)
    update.effective_chat = MagicMock(spec=Chat)
    update.effective_chat.id = 123456
    update.message = MagicMock(spec=Message)
    update.message.chat_id = 123456
    update.message.text = "test message"
    return update

@pytest.fixture
def mock_context() -> MagicMock:
    """
    Фикстура для создания мока объекта Context.

    Returns:
        MagicMock: Мок объекта Context
    """
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {}
    return context

@pytest.fixture
def mock_send_message() -> Tuple[AsyncMock, List[str]]:
    """
    Фикстура для перехвата отправки сообщений в тестах.

    Returns:
        Tuple[AsyncMock, List[str]]: Кортеж из функции отправки и списка отправленных сообщений
    """
    sent_messages = []

    async def mock_send(*args: Any, **kwargs: Any) -> None:
        # Берем текст сообщения из первого позиционного аргумента или из kwargs
        text = args[0] if args else kwargs.get('text', '')
        sent_messages.append(text)
        return None

    return mock_send, sent_messages

@pytest.fixture
def mock_restart_and_notify(mock_send_message: Tuple[AsyncMock, List[str]]) -> AsyncMock:
    """
    Фикстура для мока функции restart_auto_unlocker_and_notify.

    Args:
        mock_send_message: Фикстура для перехвата сообщений

    Returns:
        AsyncMock: Мок функции restart_auto_unlocker_and_notify
    """
    mock_send, sent_messages = mock_send_message

    async def mock_restart(update: Any, logger: Any, message_success: str, message_error: str) -> None:
        sent_messages.append(message_success)
        return None

    return mock_restart

@pytest.fixture(autouse=True)
def mock_datetime(monkeypatch: Any) -> None:
    """
    Фикстура для мока работы с датой и временем.
    """
    class MockDateTime:
        @staticmethod
        def fromtimestamp(timestamp: float) -> Any:
            mock = MagicMock()
            mock.strftime.return_value = "2025-06-16 09:00:00"
            return mock

    monkeypatch.setattr('datetime.datetime', MockDateTime)

def test_load_and_save_config(tmp_path: Any) -> None:
    """
    Тест загрузки и сохранения конфигурации.

    Args:
        tmp_path: Временный путь для тестовых файлов
    """
    config = {"timezone": "Europe/Moscow", "schedule_enabled": False}
    config_path = tmp_path / "config.json"
    telegram_bot.CONFIG_PATH = str(config_path)
    telegram_bot.save_config(config)
    loaded = telegram_bot.load_config()
    assert loaded["timezone"] == "Europe/Moscow"
    assert loaded["schedule_enabled"] is False

def test_is_authorized_true(monkeypatch: Any) -> None:
    """
    Тест проверки авторизации с правильным chat_id.

    Args:
        monkeypatch: Фикстура для модификации объектов
    """
    telegram_bot.AUTHORIZED_CHAT_ID = '123'
    class DummyUpdate:
        class Chat:
            def __init__(self, id: str) -> None:
                self.id = id
        def __init__(self, chat_id: str) -> None:
            self.effective_chat = self.Chat(chat_id)
    update = DummyUpdate('123')
    assert telegram_bot.is_authorized(update)

def test_is_authorized_false(monkeypatch: Any) -> None:
    """
    Тест проверки авторизации с неправильным chat_id.

    Args:
        monkeypatch: Фикстура для модификации объектов
    """
    telegram_bot.AUTHORIZED_CHAT_ID = '123'
    class DummyUpdate:
        class Chat:
            def __init__(self, id: str) -> None:
                self.id = id
        def __init__(self, chat_id: str) -> None:
            self.effective_chat = self.Chat(chat_id)
    update = DummyUpdate('456')
    assert not telegram_bot.is_authorized(update)

def test_send_telegram_message(monkeypatch: Any) -> None:
    """
    Тест отправки сообщения в Telegram.

    Args:
        monkeypatch: Фикстура для модификации объектов
    """
    called = {}
    def fake_post(url: str, data: Dict[str, Any], timeout: int) -> Any:
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
    """
    Мок объекта Message для тестов.
    """
    def __init__(self) -> None:
        self.text = ''
        self.chat_id = 123
        self.replies: List[Tuple[str, Dict[str, Any]]] = []

    async def reply_text(self, text: str, **kwargs: Any) -> None:
        self.replies.append((text, kwargs))

class DummyUpdate:
    """
    Мок объекта Update для тестов.
    """
    def __init__(self, text: Optional[str] = None, chat_id: int = 123) -> None:
        self.message = DummyMessage()
        self.message.text = text or ''
        self.effective_chat = types.SimpleNamespace(id=chat_id)

class DummyContext:
    """
    Мок объекта Context для тестов.
    """
    def __init__(self) -> None:
        self.user_data: Dict[str, Any] = {}

@pytest.mark.asyncio
async def test_start() -> None:
    """
    Тест команды /start.
    """
    update = DummyUpdate()
    context = DummyContext()
    await telegram_bot.start(update, context)
    assert any("Выберите действие" in r[0] for r in update.message.replies)
    # Проверяем, что в сообщении есть кнопки
    assert any(isinstance(r[1].get('reply_markup'), ReplyKeyboardMarkup) for r in update.message.replies)

@pytest.mark.asyncio
async def test_setchat() -> None:
    """
    Тест команды /setchat.
    """
    update = DummyUpdate()
    context = DummyContext()
    res = await telegram_bot.setchat(update, context)
    assert res == telegram_bot.ASK_CODEWORD
    assert any("кодовое слово" in r[0].lower() for r in update.message.replies)

@pytest.mark.asyncio
async def test_check_codeword(monkeypatch: Any) -> None:
    """
    Тест проверки кодового слова.

    Args:
        monkeypatch: Фикстура для модификации объектов
    """
    update = DummyUpdate(text=telegram_bot.CODEWORD)
    context = DummyContext()
    res = await telegram_bot.check_codeword(update, context)
    assert res == telegram_bot.CONFIRM_CHANGE
    update2 = DummyUpdate(text="wrongword")
    context2 = DummyContext()
    res2 = await telegram_bot.check_codeword(update2, context2)
    assert res2 == types.SimpleNamespace.END if hasattr(types.SimpleNamespace, 'END') else telegram_bot.ConversationHandler.END

@pytest.mark.asyncio
async def test_status(monkeypatch: Any) -> None:
    """
    Тест команды /status.

    Args:
        monkeypatch: Фикстура для модификации объектов
    """
    update = DummyUpdate()
    context = DummyContext()
    monkeypatch.setattr(telegram_bot, 'is_authorized', lambda u: True)
    monkeypatch.setattr(telegram_bot, 'load_config', lambda: {"timezone": "Europe/Moscow", "schedule_enabled": True, "open_times": {}, "breaks": {}})
    monkeypatch.setattr(telegram_bot, 'AUTO_UNLOCKER_CONTAINER', 'auto_unlocker_1')
    monkeypatch.setattr(telegram_bot, 'os', telegram_bot.os)
    await telegram_bot.status(update, context)
    assert any("Статус расписания" in r[0] for r in update.message.replies)

@pytest.mark.asyncio
async def test_enable_disable_schedule(monkeypatch: Any) -> None:
    """
    Тест включения/выключения расписания.

    Args:
        monkeypatch: Фикстура для модификации объектов
    """
    update = DummyUpdate()
    context = DummyContext()
    monkeypatch.setattr(telegram_bot, 'is_authorized', lambda u: True)
    monkeypatch.setattr(telegram_bot, 'load_config', lambda: {"timezone": "Europe/Moscow", "schedule_enabled": True, "open_times": {}, "breaks": {}})
    monkeypatch.setattr(telegram_bot, 'save_config', lambda cfg: None)
    async def fake_restart(*a: Any, **kw: Any) -> None:
        update.message.replies.append(("FAKE RESTART", {}))
    monkeypatch.setattr(telegram_bot, 'restart_auto_unlocker_and_notify', fake_restart)
    await telegram_bot.enable_schedule(update, context)
    await telegram_bot.disable_schedule(update, context)
    assert any("FAKE RESTART" in r[0] for r in update.message.replies)

@pytest.mark.asyncio
async def test_open_close_lock(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест команд открытия/закрытия замка.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    # Тест открытия замка
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send), \
         patch('telegram_bot.ttlock_api.get_token', return_value='test_token'), \
         patch('telegram_bot.ttlock_api.unlock_lock', return_value={'success': True, 'errcode': 0, 'attempt': 1}):
        await telegram_bot.open_lock(update, context)
        assert any("открыт" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

    # Очищаем список сообщений
    sent_messages.clear()

    # Тест закрытия замка
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send), \
         patch('telegram_bot.ttlock_api.get_token', return_value='test_token'), \
         patch('telegram_bot.ttlock_api.lock_lock', return_value={'success': True, 'errcode': 0}):
        await telegram_bot.close_lock(update, context)
        assert any("закрыт" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_setchat_command(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест команды /setchat.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    with patch.object(update.message, 'reply_text', side_effect=mock_send):
        result = await telegram_bot.setchat(update, context)
        assert result == telegram_bot.ASK_CODEWORD
        assert any("кодовое слово" in msg.lower() for msg in sent_messages)

@pytest.mark.asyncio
async def test_check_codeword_correct(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест проверки правильного кодового слова.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate(text=telegram_bot.CODEWORD)
    context = DummyContext()

    with patch.object(update.message, 'reply_text', side_effect=mock_send):
        result = await telegram_bot.check_codeword(update, context)
        assert result == telegram_bot.CONFIRM_CHANGE
        assert any("подтвердите" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_check_codeword_incorrect(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест проверки неправильного кодового слова.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate(text="wrong_codeword")
    context = DummyContext()

    with patch.object(update.message, 'reply_text', side_effect=mock_send):
        result = await telegram_bot.check_codeword(update, context)
        assert result == telegram_bot.ConversationHandler.END
        assert any("неверное" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_confirm_change_no(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест отмены изменения chat_id.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate(text="нет")
    context = DummyContext()

    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send):
        result = await telegram_bot.confirm_change(update, context)
        assert result == telegram_bot.ConversationHandler.END
        assert any("операция отменена" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_settime_flow(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест процесса настройки времени.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    # Начало настройки времени
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send):
        result = await telegram_bot.settime(update, context)
        assert result == telegram_bot.SETTIME_DAY
        assert any("выберите день недели" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_setbreak_flow(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест процесса настройки перерывов.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    # Начало настройки перерывов
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send):
        result = await telegram_bot.setbreak(update, context)
        assert result == telegram_bot.SETBREAK_DAY
        assert any("выберите день недели" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_settimezone_flow(mock_send_message: Tuple[AsyncMock, List[str]], mock_restart_and_notify: AsyncMock) -> None:
    """
    Тест процесса настройки часового пояса.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    # Начало настройки часового пояса
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send):
        result = await telegram_bot.settimezone(update, context)
        assert result == telegram_bot.SETTIMEZONE_VALUE
        assert any("введите часовой пояс" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_setchat_flow(mock_send_message: Tuple[AsyncMock, List[str]], mock_restart_and_notify: AsyncMock) -> None:
    """
    Тест процесса настройки chat_id.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    # Начало настройки chat_id
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send):
        result = await telegram_bot.setchat(update, context)
        assert result == telegram_bot.ASK_CODEWORD
        assert any("кодовое слово" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

    # Очищаем список сообщений
    sent_messages.clear()

    # Ввод кодового слова
    update.message.text = telegram_bot.CODEWORD
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send):
        result = await telegram_bot.check_codeword(update, context)
        assert result == telegram_bot.CONFIRM_CHANGE
        assert any("подтвердите" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

    # Очищаем список сообщений
    sent_messages.clear()

    # Подтверждение изменения
    update.message.text = "да"
    mock_env_content = "TELEGRAM_CHAT_ID=123\nOTHER_VAR=value\n"
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', mock_restart_and_notify), \
         patch('builtins.open', mock_open(read_data=mock_env_content)), \
         patch('telegram_bot.ENV_PATH', '/app/.env'):
        result = await telegram_bot.confirm_change(update, context)
        assert result == telegram_bot.ConversationHandler.END
        assert any("изменён" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_close_lock_command(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест команды закрытия замка.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send), \
         patch('telegram_bot.ttlock_api.get_token', return_value='test_token'), \
         patch('telegram_bot.ttlock_api.lock_lock', return_value={'success': True, 'errcode': 0}):
        await telegram_bot.close_lock(update, context)
        assert any("закрыт" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_enable_schedule_command(mock_send_message: Tuple[AsyncMock, List[str]], mock_restart_and_notify: AsyncMock) -> None:
    """
    Тест команды включения расписания.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send), \
         patch('telegram_bot.load_config', return_value={"schedule_enabled": False}), \
         patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', mock_restart_and_notify):
        await telegram_bot.enable_schedule(update, context)
        assert any("включено" in msg.lower() for msg in sent_messages)
        assert any("перезапущен" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_disable_schedule_command(mock_send_message: Tuple[AsyncMock, List[str]], mock_restart_and_notify: AsyncMock) -> None:
    """
    Тест команды выключения расписания.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send), \
         patch('telegram_bot.load_config', return_value={"schedule_enabled": True}), \
         patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', mock_restart_and_notify):
        await telegram_bot.disable_schedule(update, context)
        assert any("отключено" in msg.lower() for msg in sent_messages)
        assert any("перезапущен" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_logs_command(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест команды просмотра логов.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send), \
         patch('builtins.open', mock_open(read_data="test log line")):
        await telegram_bot.logs(update, context)
        assert any("test log line" in msg for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_logs_command_with_days(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест команды просмотра логов с указанием количества дней.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate(text="7")
    context = DummyContext()

    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send), \
         patch('builtins.open', mock_open(read_data="test log line")):
        await telegram_bot.logs(update, context)
        assert any("test log line" in msg for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_logs_command_file_not_found(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест команды просмотра логов при отсутствии файла логов.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send), \
         patch('builtins.open', side_effect=FileNotFoundError), \
         patch('telegram_bot.log_message'):
        await telegram_bot.logs(update, context)
        assert any("ошибка чтения логов" in msg.lower() for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_logs_command_error(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест команды просмотра логов при ошибке чтения.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send), \
         patch('builtins.open', side_effect=Exception("Test error")):
        await telegram_bot.logs(update, context)
        assert any("Ошибка чтения логов" in msg for msg in sent_messages)
        assert len(sent_messages) == 1

@pytest.mark.asyncio
async def test_setmaxretrytime_flow(mock_send_message: Tuple[AsyncMock, List[str]], mock_restart_and_notify: AsyncMock) -> None:
    """
    Тест процесса настройки максимального времени для попыток.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    # Начало настройки максимального времени
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send):
        result = await telegram_bot.setmaxretrytime(update, context)
        assert result == telegram_bot.SETMAXRETRYTIME_VALUE
        assert any("Введите максимальное время" in msg for msg in sent_messages)

    # Ввод времени
    update.message.text = "21:00"
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send), \
         patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', mock_restart_and_notify):
        result = await telegram_bot.setmaxretrytime_value(update, context)
        assert result == telegram_bot.ConversationHandler.END
        assert any("Максимальное время для попыток открытия установлено" in msg for msg in sent_messages)

@pytest.mark.asyncio
async def test_setmaxretrytime_invalid_format(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест ввода некорректного формата времени.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate(text="25:00")  # Некорректное время
    context = DummyContext()

    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send):
        result = await telegram_bot.setmaxretrytime_value(update, context)
        assert result == telegram_bot.SETMAXRETRYTIME_VALUE
        assert any("Неверный формат времени" in msg for msg in sent_messages)

@pytest.mark.asyncio
async def test_setmaxretrytime_unauthorized(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест попытки настройки времени неавторизованным пользователем.

    Args:
        mock_send_message: Фикстура для перехвата сообщений
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    with patch('telegram_bot.is_authorized', return_value=False):
        result = await telegram_bot.setmaxretrytime(update, context)
        assert result == telegram_bot.ConversationHandler.END
        assert not sent_messages  # Сообщения не должны отправляться

@pytest.mark.asyncio
async def test_settime_full_flow(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест полного цикла настройки времени открытия.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    # Начало настройки времени
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send):
        result = await telegram_bot.settime(update, context)
        assert any("выберите день недели" in msg.lower() for msg in sent_messages)

    # Очищаем список сообщений
    sent_messages.clear()

    # Симулируем нажатие на inline-кнопку выбора дня
    callback_update = MagicMock()
    callback_update.callback_query = MagicMock()
    callback_update.callback_query.data = "Пн"
    callback_update.callback_query.edit_message_text = AsyncMock()
    callback_update.callback_query.answer = AsyncMock()

    with patch('telegram_bot.is_authorized', return_value=True):
        await telegram_bot.handle_settime_callback(callback_update, context)
        assert context.user_data["state"] == telegram_bot.SETTIME_VALUE
        assert context.user_data["day"] == "Пн"

    # Очищаем список сообщений
    sent_messages.clear()

    # Ввод времени
    update.message.text = "09:00"
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send), \
         patch('telegram_bot.load_config', return_value={"open_times": {}}), \
         patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', AsyncMock()):
        # Устанавливаем состояние и день напрямую
        context.user_data["state"] = telegram_bot.SETTIME_VALUE
        context.user_data["day"] = "Пн"
        await telegram_bot.settime_value(update, context)
        assert any("время открытия" in msg.lower() for msg in sent_messages)
        assert "state" not in context.user_data  # Проверяем, что состояние очищено

@pytest.mark.asyncio
async def test_setbreak_full_flow(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест полного цикла настройки перерывов.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    # Начало настройки перерывов
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send):
        result = await telegram_bot.setbreak(update, context)
        assert any("выберите день недели" in msg.lower() for msg in sent_messages)

    # Очищаем список сообщений
    sent_messages.clear()

    # Симулируем нажатие на inline-кнопку выбора дня
    callback_update = MagicMock()
    callback_update.callback_query = MagicMock()
    callback_update.callback_query.data = "setbreak_Пн"
    callback_update.callback_query.edit_message_text = AsyncMock()
    callback_update.callback_query.answer = AsyncMock()

    with patch('telegram_bot.is_authorized', return_value=True):
        await telegram_bot.handle_setbreak_callback(callback_update, context)
        assert context.user_data["day"] == "Пн"

    # Симулируем нажатие на кнопку добавления перерыва
    callback_update.callback_query.data = "add_break"
    with patch('telegram_bot.is_authorized', return_value=True):
        await telegram_bot.handle_setbreak_action(callback_update, context)
        assert context.user_data["state"] == telegram_bot.SETBREAK_ADD

    # Очищаем список сообщений
    sent_messages.clear()

    # Ввод времени перерыва
    update.message.text = "12:00-13:00"
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send), \
         patch('telegram_bot.load_config', return_value={"breaks": {}}), \
         patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', AsyncMock()):
        # Устанавливаем состояние и день напрямую
        context.user_data["state"] = telegram_bot.SETBREAK_ADD
        context.user_data["day"] = "Пн"
        await telegram_bot.setbreak_add(update, context)
        assert any("добавлен перерыв" in msg.lower() for msg in sent_messages)
        assert "state" not in context.user_data  # Проверяем, что состояние очищено

@pytest.mark.asyncio
async def test_settime_invalid_time(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест обработки некорректного времени.
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()

    # Устанавливаем состояние и день
    context.user_data["state"] = telegram_bot.SETTIME_VALUE
    context.user_data["day"] = "Пн"

    # Ввод некорректного времени
    update.message.text = "25:00"
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch.object(update.message, 'reply_text', side_effect=mock_send):
        await telegram_bot.handle_menu_button(update, context)
        assert any("некорректный формат времени" in msg.lower() for msg in sent_messages)
        assert context.user_data["state"] == telegram_bot.SETTIME_VALUE  # Состояние не должно измениться
