"""
Тесты для telegram_bot.py.
"""
import pytest
import telegram_bot
import os
import json
import types
from unittest.mock import patch, MagicMock, AsyncMock, mock_open
from telegram import Update, Message, Chat, User
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
    
    async def mock_send(update: Any, text: str, parse_mode: str = "HTML", **kwargs: Any) -> None:
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
    mock_send, _ = mock_send_message
    
    async def mock_restart(update: Any, logger: Any, message_success: str, message_error: str) -> None:
        await mock_send(update, message_success)
        return None
    
    return mock_restart

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
    assert any("Доступные команды" in r[0] for r in update.message.replies)

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
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()
    
    # Тест открытия замка
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.ttlock_api.get_token', return_value='test_token'), \
         patch('telegram_bot.ttlock_api.unlock_lock', return_value={'success': True}):
        await telegram_bot.open_lock(update, context)
        assert any("Замок успешно открыт" in msg for msg in sent_messages)
    
    # Тест закрытия замка
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.ttlock_api.get_token', return_value='test_token'), \
         patch('telegram_bot.ttlock_api.lock_lock', return_value={'success': True}):
        await telegram_bot.close_lock(update, context)
        assert any("Замок успешно закрыт" in msg for msg in sent_messages)

@pytest.mark.asyncio
async def test_setchat_command(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест команды /setchat.
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()
    
    await telegram_bot.setchat(update, context)
    assert any("кодовое слово" in msg.lower() for msg in sent_messages)

@pytest.mark.asyncio
async def test_check_codeword_correct(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест проверки правильного кодового слова.
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate(text=telegram_bot.CODEWORD)
    context = DummyContext()
    
    result = await telegram_bot.check_codeword(update, context)
    assert result == telegram_bot.CONFIRM_CHANGE
    assert any("подтвердите" in msg.lower() for msg in sent_messages)

@pytest.mark.asyncio
async def test_check_codeword_incorrect(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест проверки неправильного кодового слова.
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate(text="wrong_codeword")
    context = DummyContext()
    
    result = await telegram_bot.check_codeword(update, context)
    assert result == telegram_bot.ConversationHandler.END
    assert any("неверное" in msg.lower() for msg in sent_messages)

@pytest.mark.asyncio
async def test_confirm_change_no(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест отмены изменения chat_id.
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate(text="нет")
    context = DummyContext()
    
    result = await telegram_bot.confirm_change(update, context)
    assert result == telegram_bot.ConversationHandler.END
    assert any("отменено" in msg.lower() for msg in sent_messages)

@pytest.mark.asyncio
async def test_settime_flow(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест процесса настройки времени.
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()
    
    # Начало настройки времени
    with patch('telegram_bot.is_authorized', return_value=True):
        result = await telegram_bot.settime(update, context)
        assert result == telegram_bot.SETTIME_DAY
        assert any("Выберите день недели" in msg for msg in sent_messages)
    
    # Выбор дня
    update.message.text = "Понедельник"
    result = await telegram_bot.settime_day(update, context)
    assert result == telegram_bot.SETTIME_VALUE
    assert any("Введите время" in msg for msg in sent_messages)
    
    # Ввод времени
    update.message.text = "09:00"
    with patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify'):
        result = await telegram_bot.settime_value(update, context)
        assert result == telegram_bot.SETTIME_DAY
        assert any("Хотите изменить время для другого дня" in msg for msg in sent_messages)

@pytest.mark.asyncio
async def test_setbreak_flow(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест процесса настройки перерывов.
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()
    
    # Начало настройки перерывов
    with patch('telegram_bot.is_authorized', return_value=True):
        result = await telegram_bot.setbreak(update, context)
        assert result == telegram_bot.SETBREAK_DAY
        assert any("Выберите день недели" in msg for msg in sent_messages)
    
    # Выбор дня
    update.message.text = "Понедельник"
    result = await telegram_bot.setbreak_day(update, context)
    assert result == telegram_bot.SETBREAK_ACTION
    assert any("Текущие перерывы" in msg for msg in sent_messages)
    
    # Выбор действия
    update.message.text = "Добавить"
    result = await telegram_bot.setbreak_action(update, context)
    assert result == telegram_bot.SETBREAK_ADD
    assert any("Введите время" in msg for msg in sent_messages)
    
    # Ввод времени
    update.message.text = "13:00-14:00"
    with patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify'):
        result = await telegram_bot.setbreak_add(update, context)
        assert result == telegram_bot.SETBREAK_DAY
        assert any("Перерыв добавлен" in msg for msg in sent_messages)

@pytest.mark.asyncio
async def test_settimezone_flow(mock_send_message: Tuple[AsyncMock, List[str]], mock_restart_and_notify: AsyncMock) -> None:
    """
    Тест процесса настройки часового пояса.
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
        mock_restart_and_notify: Фикстура для мока функции перезапуска
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()
    
    # Начало настройки часового пояса
    with patch('telegram_bot.is_authorized', return_value=True):
        result = await telegram_bot.settimezone(update, context)
        assert result == telegram_bot.SETTIMEZONE_VALUE
        assert any("Введите часовой пояс" in msg for msg in sent_messages)
    
    # Ввод часового пояса
    update.message.text = "Europe/Moscow"
    with patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', mock_restart_and_notify):
        result = await telegram_bot.settimezone_value(update, context)
        assert result == telegram_bot.ConversationHandler.END
        assert any("Часовой пояс изменен" in msg for msg in sent_messages)

@pytest.mark.asyncio
async def test_setchat_flow(mock_send_message: Tuple[AsyncMock, List[str]], mock_restart_and_notify: AsyncMock) -> None:
    """
    Тест процесса настройки chat_id.
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
        mock_restart_and_notify: Фикстура для мока функции перезапуска
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()
    
    # Начало настройки chat_id
    result = await telegram_bot.setchat(update, context)
    assert result == telegram_bot.ASK_CODEWORD
    assert any("кодовое слово" in msg.lower() for msg in sent_messages)
    
    # Ввод кодового слова
    update.message.text = telegram_bot.CODEWORD
    result = await telegram_bot.check_codeword(update, context)
    assert result == telegram_bot.CONFIRM_CHANGE
    assert any("подтвердите" in msg.lower() for msg in sent_messages)
    
    # Подтверждение изменения
    update.message.text = "да"
    with patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', mock_restart_and_notify):
        result = await telegram_bot.confirm_change(update, context)
        assert result == telegram_bot.ConversationHandler.END
        assert any("chat_id изменен" in msg.lower() for msg in sent_messages)

@pytest.mark.asyncio
async def test_close_lock_command(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест команды закрытия замка.
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()
    
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.ttlock_api.get_token', return_value='test_token'), \
         patch('telegram_bot.ttlock_api.lock_lock', return_value={'success': True}):
        await telegram_bot.close_lock(update, context)
        assert any("Замок успешно закрыт" in msg for msg in sent_messages)

@pytest.mark.asyncio
async def test_enable_schedule_command(mock_send_message: Tuple[AsyncMock, List[str]], mock_restart_and_notify: AsyncMock) -> None:
    """
    Тест команды включения расписания.
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
        mock_restart_and_notify: Фикстура для мока функции перезапуска
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()
    
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.load_config', return_value={"schedule_enabled": False}), \
         patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', mock_restart_and_notify):
        await telegram_bot.enable_schedule(update, context)
        assert any("Расписание включено" in msg for msg in sent_messages)

@pytest.mark.asyncio
async def test_disable_schedule_command(mock_send_message: Tuple[AsyncMock, List[str]], mock_restart_and_notify: AsyncMock) -> None:
    """
    Тест команды выключения расписания.
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
        mock_restart_and_notify: Фикстура для мока функции перезапуска
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()
    
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('telegram_bot.load_config', return_value={"schedule_enabled": True}), \
         patch('telegram_bot.save_config'), \
         patch('telegram_bot.restart_auto_unlocker_and_notify', mock_restart_and_notify):
        await telegram_bot.disable_schedule(update, context)
        assert any("Расписание выключено" in msg for msg in sent_messages)

@pytest.mark.asyncio
async def test_logs_command(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест команды просмотра логов.
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate()
    context = DummyContext()
    
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('builtins.open', mock_open(read_data="test log line")):
        await telegram_bot.logs(update, context)
        assert any("test log line" in msg for msg in sent_messages)

@pytest.mark.asyncio
async def test_logs_command_with_days(mock_send_message: Tuple[AsyncMock, List[str]]) -> None:
    """
    Тест команды просмотра логов с указанием количества дней.
    
    Args:
        mock_send_message: Фикстура для перехвата сообщений
    """
    mock_send, sent_messages = mock_send_message
    update = DummyUpdate(text="7")
    context = DummyContext()
    
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('builtins.open', mock_open(read_data="test log line")):
        await telegram_bot.logs(update, context)
        assert any("test log line" in msg for msg in sent_messages)

@pytest.mark.asyncio
async def test_logs_command_file_not_found(mock_update: MagicMock, mock_context: MagicMock) -> None:
    """
    Тест команды просмотра логов при отсутствии файла логов.
    
    Args:
        mock_update: Фикстура для мока объекта Update
        mock_context: Фикстура для мока объекта Context
    """
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('builtins.open', side_effect=FileNotFoundError):
        await telegram_bot.logs(mock_update, mock_context)
        assert any("Файл логов не найден" in msg for msg in mock_update.message.replies)

@pytest.mark.asyncio
async def test_logs_command_error(mock_update: MagicMock, mock_context: MagicMock) -> None:
    """
    Тест команды просмотра логов при ошибке чтения.
    
    Args:
        mock_update: Фикстура для мока объекта Update
        mock_context: Фикстура для мока объекта Context
    """
    with patch('telegram_bot.is_authorized', return_value=True), \
         patch('builtins.open', side_effect=Exception("Test error")):
        await telegram_bot.logs(mock_update, mock_context)
        assert any("Ошибка чтения логов" in msg for msg in mock_update.message.replies)
