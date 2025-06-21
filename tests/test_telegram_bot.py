"""
Тесты для telegram_bot.py.
"""
import pytest
from telegram_bot import (
    start, menu, setchat, check_codeword, confirm_change, status, logs,
    enable_schedule, disable_schedule, open_lock, close_lock,
    settime, handle_settime_callback, settime_value,
    setbreak, handle_setbreak_callback, handle_setbreak_action, setbreak_add, setbreak_remove,
    settimezone, settimezone_apply,
    setemail, setemail_value, do_test_email,
    restart_auto_unlocker_cmd,
    ASK_CODEWORD, CONFIRM_CHANGE,
    SETTIME_DAY, SETTIME_VALUE,
    SETBREAK_DAY, SETBREAK_ACTION, SETBREAK_ADD, SETBREAK_DEL,
    SETTIMEZONE_VALUE, SETEMAIL_VALUE
)
import telegram_bot as bot_module
import os
import json
from unittest.mock import patch, MagicMock, mock_open, ANY

from telegram import Update, Message, Chat, User, ReplyKeyboardMarkup, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import ConversationHandler
import pytz

# ---- Fixtures ----

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    """Настройка окружения и моков для всех тестов."""
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test_token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '123456')
    monkeypatch.setenv('TELEGRAM_CODEWORD', 'secretword')
    monkeypatch.setenv('AUTO_UNLOCKER_CONTAINER', 'test_container')
    monkeypatch.setenv('TTLOCK_CLIENT_ID', 'test_client_id')
    monkeypatch.setenv('TTLOCK_CLIENT_SECRET', 'test_client_secret')
    monkeypatch.setenv('TTLOCK_USERNAME', 'test_username')
    monkeypatch.setenv('TTLOCK_PASSWORD', 'test_password')
    monkeypatch.setenv('TTLOCK_LOCK_ID', '123')
    bot_module.AUTHORIZED_CHAT_ID = '123456'
    bot_module.CONFIG_PATH = 'config.json'
    # Сброс изменяемых глобальных переменных перед тестом
    bot_module.BLOCKED_CHAT_IDS.clear()


@pytest.fixture
def mock_update():
    """Фикстура для создания мока объекта Update."""
    update = MagicMock(spec=Update)
    update.effective_chat = MagicMock(spec=Chat, id=123456)
    update.message = MagicMock(spec=Message, chat_id=123456, text="test")
    update.message.reply_text = MagicMock()
    
    update.callback_query = MagicMock(spec=CallbackQuery)
    update.callback_query.answer = MagicMock()
    update.callback_query.edit_message_text = MagicMock()
    return update

@pytest.fixture
def mock_context():
    """Фикстура для создания мока объекта Context."""
    context = MagicMock()
    context.user_data = {}
    context.bot_data = {}
    return context

# ---- Test Cases ----

def test_start_calls_menu(mock_update, mock_context):
    """Тест: /start должен вызывать menu."""
    with patch('telegram_bot.menu') as mock_menu:
        start(mock_update, mock_context)
        mock_menu.assert_called_once_with(mock_update, mock_context)

def test_menu_sends_keyboard(mock_update, mock_context):
    """Тест: /menu отправляет клавиатуру с командами."""
    menu(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    args, kwargs = mock_update.message.reply_text.call_args
    assert "Выберите действие" in args[0]
    assert isinstance(kwargs['reply_markup'], ReplyKeyboardMarkup)
    assert len(kwargs['reply_markup'].keyboard) > 0

# --- setchat Conversation ---

def test_setchat_authorized(mock_update, mock_context):
    """Тест: /setchat начинает диалог."""
    result = setchat(mock_update, mock_context)
    assert result == ASK_CODEWORD
    mock_update.message.reply_text.assert_called_with("Введите кодовое слово:", parse_mode='HTML', reply_markup=ANY)

def test_setchat_blocked(mock_update, mock_context):
    """Тест: /setchat для заблокированного пользователя."""
    blocked_id = 789
    mock_update.effective_chat.id = blocked_id
    bot_module.BLOCKED_CHAT_IDS.add(blocked_id)
    
    result = setchat(mock_update, mock_context)
    
    assert result == ConversationHandler.END
    mock_update.message.reply_text.assert_called_with("⛔️ Вы исчерпали лимит попыток смены получателя. Попробуйте позже или обратитесь к администратору.", parse_mode='HTML')

def test_check_codeword_correct(mock_update, mock_context):
    """Тест: правильное кодовое слово."""
    mock_update.message.text = 'secretword'
    result = check_codeword(mock_update, mock_context)
    assert result == CONFIRM_CHANGE
    mock_update.message.reply_text.assert_called_with("Кодовое слово верно! Подтвердите смену получателя (да/нет):", parse_mode='HTML', reply_markup=ANY)
    assert mock_context.user_data['new_chat_id'] == mock_update.message.chat_id

def test_check_codeword_incorrect_and_block(mock_update, mock_context):
    """Тест: 5 неверных попыток кодового слова приводят к блокировке."""
    chat_id_to_block = 456
    mock_update.effective_chat.id = chat_id_to_block
    mock_update.message.text = 'wrong'
    mock_context.bot_data = {'codeword_attempts': {chat_id_to_block: 4}}
    
    with patch('telegram_bot.save_blocked_chat_ids') as mock_save:
        result = check_codeword(mock_update, mock_context)
        assert result == ConversationHandler.END
        # При 5-й неверной попытке отправляется только сообщение о блокировке
        mock_update.message.reply_text.assert_called_once_with(
            "⛔️ Вы исчерпали лимит попыток смены получателя. Попробуйте позже или обратитесь к администратору.", 
            parse_mode='HTML'
        )
        mock_save.assert_called_once()
        assert chat_id_to_block in bot_module.BLOCKED_CHAT_IDS

@patch('builtins.open', new_callable=mock_open, read_data="TELEGRAM_CHAT_ID=123456\n")
@patch('telegram_bot.restart_auto_unlocker_and_notify')
def test_confirm_change_yes(mock_restart, mock_open_file, mock_update, mock_context):
    """Тест: подтверждение смены chat_id."""
    mock_update.message.text = 'да'
    new_id = '654321'
    mock_context.user_data['new_chat_id'] = new_id
    
    result = confirm_change(mock_update, mock_context)
    
    handle = mock_open_file()
    handle.write.assert_any_call(f'TELEGRAM_CHAT_ID={new_id}\n')
    
    mock_restart.assert_called_once()
    assert bot_module.AUTHORIZED_CHAT_ID == new_id
    assert result == ConversationHandler.END

def test_confirm_change_no(mock_update, mock_context):
    """Тест: отмена смены chat_id."""
    mock_update.message.text = 'нет'
    result = confirm_change(mock_update, mock_context)
    mock_update.message.reply_text.assert_any_call("Операция отменена.", parse_mode='HTML')
    assert result == ConversationHandler.END

@patch('builtins.open', side_effect=IOError("File read error"))
def test_confirm_change_yes_read_error(mock_open_file, mock_update, mock_context):
    """Тест: ошибка чтения .env при смене chat_id."""
    mock_update.message.text = 'да'
    mock_context.user_data['new_chat_id'] = '654321'
    
    result = confirm_change(mock_update, mock_context)
    
    assert result == ConversationHandler.END
    mock_update.message.reply_text.assert_any_call("Не удалось прочитать .env: File read error", parse_mode='HTML')

# --- Status and Logs ---

@patch('docker.from_env')
def test_status_command(mock_docker, mock_update, mock_context):
    """Тест: команда /status."""
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_docker.return_value.containers.get.return_value = mock_container
    
    config_data = json.dumps({"timezone": "Asia/Tomsk", "schedule_enabled": True, "open_times": {"Пн": "09:00"}, "breaks": {}})
    with patch('builtins.open', mock_open(read_data=config_data)):
        status(mock_update, mock_context)
    
    mock_update.message.reply_text.assert_called_once()
    text = mock_update.message.reply_text.call_args[0][0]
    assert "<b>Статус расписания</b>" in text
    assert "Asia/Tomsk" in text
    assert "<b>да</b>" in text
    assert "работает" in text
    assert "Пн: 09:00" in text

def test_logs_command(mock_update, mock_context):
    """Тест: команда /logs."""
    log_data = "INFO: log message 1\nDEBUG: log message 2"
    with patch('builtins.open', mock_open(read_data=log_data)):
        with patch('os.path.exists', return_value=True):
            logs(mock_update, mock_context)
    
    mock_update.message.reply_text.assert_called_once()
    text = mock_update.message.reply_text.call_args[0][0]
    assert "<b>Последние логи сервиса:</b>" in text
    assert "log message 1" in text

@patch('docker.from_env', side_effect=Exception("Docker error"))
def test_status_command_docker_error(mock_docker, mock_update, mock_context):
    """Тест: /status при ошибке Docker."""
    config_data = json.dumps({"timezone": "UTC", "schedule_enabled": True})
    with patch('builtins.open', mock_open(read_data=config_data)):
        status(mock_update, mock_context)
    
    mock_update.message.reply_text.assert_called_once()
    text = mock_update.message.reply_text.call_args[0][0]
    assert "<b>Сервис автооткрытия:</b>" not in text

def test_logs_command_file_not_found(mock_update, mock_context):
    """Тест: /logs, когда лог-файл не найден."""
    with patch('os.path.exists', return_value=False):
        logs(mock_update, mock_context)
    
    mock_update.message.reply_text.assert_called_once_with("Лог-файл не найден.", parse_mode='HTML')

def test_format_logs_formatting():
    """Тест: форматирование логов и замена дней недели."""
    log_data = "2023-01-01 INFO: some task on monday\n2023-01-02 DEBUG: another task on tuesday"
    expected = "<b>Последние логи сервиса:</b>\n<code>2023-01-01 INFO: some task on Понедельник\n2023-01-02 DEBUG: another task on Вторник</code>"
    
    with patch('builtins.open', mock_open(read_data=log_data)):
        with patch('os.path.exists', return_value=True):
            result = bot_module.format_logs()
    
    assert result == expected

# --- Schedule Enable/Disable ---

@patch('telegram_bot.save_config')
@patch('telegram_bot.restart_auto_unlocker_and_notify')
def test_enable_schedule(mock_restart, mock_save_config, mock_update, mock_context):
    """Тест: команда /enable_schedule."""
    with patch('telegram_bot.load_config', return_value={"schedule_enabled": False}) as mock_load:
        enable_schedule(mock_update, mock_context)
        mock_load.assert_called_once()
        mock_save_config.assert_called_with({"schedule_enabled": True}, bot_module.CONFIG_PATH, bot_module.logger)
        mock_restart.assert_called_once()

@patch('telegram_bot.save_config')
@patch('telegram_bot.restart_auto_unlocker_and_notify')
def test_disable_schedule(mock_restart, mock_save_config, mock_update, mock_context):
    """Тест: команда /disable_schedule."""
    with patch('telegram_bot.load_config', return_value={"schedule_enabled": True}) as mock_load:
        disable_schedule(mock_update, mock_context)
        mock_load.assert_called_once()
        mock_save_config.assert_called_with({"schedule_enabled": False}, bot_module.CONFIG_PATH, bot_module.logger)
        mock_restart.assert_called_once()

# --- Lock Open/Close ---

@patch('ttlock_api.unlock_lock')
@patch('ttlock_api.get_token', return_value='test_token')
def test_open_lock_success(mock_get_token, mock_unlock, mock_update, mock_context):
    """Тест: успешное открытие замка /open."""
    mock_unlock.return_value = {'errcode': 0, 'attempt': 1}
    open_lock(mock_update, mock_context)
    mock_get_token.assert_called_once()
    mock_unlock.assert_called_once_with('test_token', bot_module.TTLOCK_LOCK_ID, bot_module.logger)
    mock_update.message.reply_text.assert_any_call("Замок <b>открыт</b>.\nПопытка: 1", parse_mode='HTML')

@patch('ttlock_api.get_token', return_value=None)
def test_open_lock_no_token(mock_get_token, mock_update, mock_context):
    """Тест: /open, когда не удалось получить токен."""
    open_lock(mock_update, mock_context)
    mock_get_token.assert_called_once()
    mock_update.message.reply_text.assert_any_call("Ошибка при открытии замка: Не удалось получить токен.", parse_mode='HTML')

@patch('ttlock_api.get_token', side_effect=Exception("Unexpected error"))
def test_open_lock_exception(mock_get_token, mock_update, mock_context):
    """Тест: /open, когда возникает непредвиденная ошибка."""
    open_lock(mock_update, mock_context)
    mock_get_token.assert_called_once()
    mock_update.message.reply_text.assert_any_call("Ошибка при открытии замка: Unexpected error", parse_mode='HTML')

@patch('ttlock_api.lock_lock')
@patch('ttlock_api.get_token', return_value='test_token')
def test_close_lock_success(mock_get_token, mock_lock, mock_update, mock_context):
    """Тест: успешное закрытие замка /close."""
    mock_lock.return_value = {'errcode': 0, 'attempt': 1}
    close_lock(mock_update, mock_context)
    mock_get_token.assert_called_once()
    mock_lock.assert_called_once_with('test_token', bot_module.TTLOCK_LOCK_ID, bot_module.logger)
    mock_update.message.reply_text.assert_any_call("Замок <b>закрыт</b>.\nПопытка: 1", parse_mode='HTML')

@patch('ttlock_api.get_token', return_value=None)
def test_close_lock_no_token(mock_get_token, mock_update, mock_context):
    """Тест: /close, когда не удалось получить токен."""
    close_lock(mock_update, mock_context)
    mock_get_token.assert_called_once()
    mock_update.message.reply_text.assert_any_call("Ошибка при закрытии замка: Не удалось получить токен.", parse_mode='HTML')

@patch('ttlock_api.get_token', side_effect=Exception("Unexpected error"))
def test_close_lock_exception(mock_get_token, mock_update, mock_context):
    """Тест: /close, когда возникает непредвиденная ошибка."""
    close_lock(mock_update, mock_context)
    mock_get_token.assert_called_once()
    mock_update.message.reply_text.assert_any_call("Ошибка при закрытии замка: Unexpected error", parse_mode='HTML')

# --- settime Conversation ---

def test_settime_starts_conversation(mock_update, mock_context):
    """Тест: /settime начинает диалог выбора дня."""
    result = settime(mock_update, mock_context)
    assert result == SETTIME_DAY
    mock_update.message.reply_text.assert_called_once()
    args, kwargs = mock_update.message.reply_text.call_args
    assert "Выберите день недели" in args[0]
    assert isinstance(kwargs['reply_markup'], InlineKeyboardMarkup)

def test_handle_settime_callback(mock_update, mock_context):
    """Тест: выбор дня в /settime."""
    mock_update.callback_query.data = "Пн"
    result = handle_settime_callback(mock_update, mock_context)
    assert result == SETTIME_VALUE
    assert mock_context.user_data['day'] == "Пн"
    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_called_with(
        text="Выбран день: Пн\nВведите время открытия в формате ЧЧ:ММ (например, 09:00):"
    )

@patch('telegram_bot.save_config')
@patch('telegram_bot.restart_auto_unlocker_and_notify')
def test_settime_value_valid(mock_restart, mock_save_config, mock_update, mock_context):
    """Тест: установка корректного времени."""
    mock_update.message.text = "09:30"
    mock_context.user_data['day'] = "Пн"
    with patch('telegram_bot.load_config', return_value={"open_times": {}}) as mock_load:
        result = settime_value(mock_update, mock_context)
    
        assert result == ConversationHandler.END
        mock_load.assert_called_once()
        mock_save_config.assert_called_once_with({'open_times': {'Пн': '09:30'}}, bot_module.CONFIG_PATH, bot_module.logger)
        mock_restart.assert_called_once()

def test_settime_value_invalid(mock_update, mock_context):
    """Тест: некорректный формат времени в /settime."""
    mock_update.message.text = 'invalid-time'
    result = settime_value(mock_update, mock_context)
    assert result == SETTIME_VALUE
    mock_update.message.reply_text.assert_called_with(
        "Некорректный формат времени. Используйте ЧЧ:ММ (например, 09:00).", parse_mode='HTML'
    )

def test_settime_value_invalid_range(mock_update, mock_context):
    """Тест: некорректный диапазон времени в /settime (например, 25:00)."""
    mock_update.message.text = '25:00'
    result = settime_value(mock_update, mock_context)
    assert result == SETTIME_VALUE
    mock_update.message.reply_text.assert_called_with(
        "Некорректное время. Часы должны быть от 0 до 23, минуты от 0 до 59.", parse_mode='HTML'
    )

# --- setbreak Conversation ---

def test_setbreak_starts_conversation(mock_update, mock_context):
    """Тест: /setbreak начинает диалог."""
    result = setbreak(mock_update, mock_context)
    assert result == SETBREAK_DAY
    mock_update.message.reply_text.assert_called_once()
    assert isinstance(mock_update.message.reply_text.call_args[1]['reply_markup'], InlineKeyboardMarkup)

def test_handle_setbreak_callback(mock_update, mock_context):
    """Тест: выбор дня в /setbreak."""
    mock_update.callback_query.data = "setbreak_Вт"
    result = handle_setbreak_callback(mock_update, mock_context)
    assert result == SETBREAK_ACTION
    assert mock_context.user_data['day'] == "Вт"
    mock_update.callback_query.edit_message_text.assert_called_once()

def test_handle_setbreak_action_add(mock_update, mock_context):
    """Тест: выбор 'Добавить' перерыв."""
    mock_update.callback_query.data = "add_break"
    result = handle_setbreak_action(mock_update, mock_context)
    assert result == SETBREAK_ADD
    mock_update.callback_query.edit_message_text.assert_called_with(
        text="Введите время перерыва в формате ЧЧ:ММ-ЧЧ:ММ (например, 12:00-13:00):"
    )

def test_handle_setbreak_action_remove_no_breaks(mock_update, mock_context):
    """Тест: попытка удалить перерыв, когда их нет."""
    mock_update.callback_query.data = "remove_break"
    mock_context.user_data['day'] = "Пн"
    with patch('telegram_bot.load_config', return_value={"breaks": {"Пн": []}}):
        result = handle_setbreak_action(mock_update, mock_context)
        assert result == ConversationHandler.END
        mock_update.callback_query.edit_message_text.assert_called_with(text="Нет перерывов для удаления.")

def test_handle_setbreak_action_remove_with_breaks(mock_update, mock_context):
    """Тест: начало удаления перерыва, когда они есть."""
    mock_update.callback_query.data = "remove_break"
    mock_context.user_data['day'] = "Пн"
    with patch('telegram_bot.load_config', return_value={"breaks": {"Пн": ["12:00-13:00"]}}):
        result = handle_setbreak_action(mock_update, mock_context)
        assert result == SETBREAK_DEL
        mock_update.callback_query.edit_message_text.assert_called_with(
            text="Введите время перерыва для удаления в формате ЧЧ:ММ-ЧЧ:ММ:"
        )

@patch('telegram_bot.save_config')
@patch('telegram_bot.restart_auto_unlocker_and_notify')
def test_setbreak_add_valid(mock_restart, mock_save_config, mock_update, mock_context):
    """Тест: добавление корректного перерыва."""
    mock_update.message.text = "13:00-14:00"
    mock_context.user_data['day'] = "Вт"
    with patch('telegram_bot.load_config', return_value={"breaks": {}}) as mock_load:
        result = setbreak_add(mock_update, mock_context)
    
        assert result == ConversationHandler.END
        mock_load.assert_called_once()
        mock_save_config.assert_called_once_with({'breaks': {'Вт': ['13:00-14:00']}}, bot_module.CONFIG_PATH, bot_module.logger)
        mock_restart.assert_called_once()

@patch('telegram_bot.save_config')
@patch('telegram_bot.restart_auto_unlocker_and_notify')
def test_setbreak_remove_valid(mock_restart, mock_save_config, mock_update, mock_context):
    """Тест: удаление существующего перерыва."""
    mock_update.message.text = "13:00-14:00"
    mock_context.user_data['day'] = "Вт"
    config = {"breaks": {"Вт": ["13:00-14:00", "15:00-16:00"]}}
    with patch('telegram_bot.load_config', return_value=config) as mock_load:
        result = setbreak_remove(mock_update, mock_context)

        assert result == ConversationHandler.END
        mock_load.assert_called_once()
        mock_save_config.assert_called_once_with({'breaks': {'Вт': ['15:00-16:00']}}, bot_module.CONFIG_PATH, bot_module.logger)
        mock_restart.assert_called_once()

@patch('telegram_bot.save_config')
@patch('telegram_bot.restart_auto_unlocker_and_notify')
def test_setbreak_add_invalid_format(mock_restart, mock_save_config, mock_update, mock_context):
    """Тест: некорректный формат перерыва."""
    mock_update.message.text = "invalid"
    result = setbreak_add(mock_update, mock_context)
    assert result == SETBREAK_ADD
    mock_update.message.reply_text.assert_called_with(
        "Некорректный формат перерыва. Используйте ЧЧ:ММ-ЧЧ:ММ (например, 12:00-13:00).", parse_mode='HTML'
    )

def test_setbreak_add_invalid_time_range(mock_update, mock_context):
    """Тест: некорректный диапазон времени перерыва (окончание раньше начала)."""
    mock_update.message.text = "14:00-13:00"
    result = setbreak_add(mock_update, mock_context)
    assert result == SETBREAK_ADD
    mock_update.message.reply_text.assert_called_with(
        "Время окончания перерыва должно быть позже времени начала.", parse_mode='HTML'
    )

@patch('telegram_bot.save_config')
@patch('telegram_bot.restart_auto_unlocker_and_notify')
def test_setbreak_remove_not_found(mock_restart, mock_save_config, mock_update, mock_context):
    """Тест: удаление несуществующего перерыва."""
    mock_update.message.text = "10:00-11:00"
    mock_context.user_data['day'] = "Пн"
    config_data = {"breaks": {"Пн": ["12:00-13:00"]}}
    with patch('telegram_bot.load_config', return_value=config_data):
        result = setbreak_remove(mock_update, mock_context)
        assert result == ConversationHandler.END
        mock_update.message.reply_text.assert_called_with("Такой перерыв не найден.", parse_mode='HTML')

# --- settimezone Conversation ---

def test_settimezone_starts_conversation(mock_update, mock_context):
    """Тест: /settimezone начинает диалог."""
    result = settimezone(mock_update, mock_context)
    assert result == SETTIMEZONE_VALUE
    mock_update.message.reply_text.assert_called_once_with(
        "Введите часовой пояс (например, Europe/Moscow):", parse_mode='HTML'
    )

@patch('pytz.timezone', return_value=True) # Просто чтобы пройти проверку
@patch('telegram_bot.save_config')
@patch('telegram_bot.restart_auto_unlocker_and_notify')
def test_settimezone_apply(mock_restart, mock_save_config, mock_pytz, mock_update, mock_context):
    """Тест: успешное применение часового пояса."""
    mock_update.message.text = "Europe/Moscow"
    with patch('telegram_bot.load_config', return_value={}) as mock_load:
        result = settimezone_apply(mock_update, mock_context)

        assert result == ConversationHandler.END
        mock_load.assert_called_once()
        mock_save_config.assert_called_once_with({'timezone': 'Europe/Moscow'}, bot_module.CONFIG_PATH, bot_module.logger)
        mock_restart.assert_called_once()

def test_settimezone_apply_invalid(mock_update, mock_context):
    """Тест: некорректный часовой пояс."""
    mock_update.message.text = 'Invalid/Timezone'
    with patch('pytz.timezone', side_effect=pytz.exceptions.UnknownTimeZoneError):
        result = settimezone_apply(mock_update, mock_context)
        assert result == SETTIMEZONE_VALUE
        mock_update.message.reply_text.assert_called_with(
            "Некорректный часовой пояс. Попробуйте ещё раз.", parse_mode='HTML'
        )

# --- setemail Conversation ---

@patch('builtins.open', new_callable=mock_open, read_data="EMAIL_TO=old@mail.com\n")
@patch('telegram_bot.restart_auto_unlocker_and_notify')
def test_setemail_value(mock_restart, mock_open_file, mock_update, mock_context):
    """Тест: установка email."""
    mock_update.message.text = "new@mail.com"
    result = setemail_value(mock_update, mock_context)
    
    handle = mock_open_file()
    handle.write.assert_any_call('EMAIL_TO=new@mail.com\n')
    mock_restart.assert_called_once()
    assert result == ConversationHandler.END

def test_setemail_value_invalid_format(mock_update, mock_context):
    """Тест: некорректный формат email."""
    mock_update.message.text = 'invalid-email'
    result = setemail_value(mock_update, mock_context)
    assert result == SETEMAIL_VALUE
    mock_update.message.reply_text.assert_called_with(
        "Некорректный формат email. Попробуйте еще раз.", parse_mode='HTML'
    )

@patch('telegram_bot.send_email_notification', return_value=True)
def test_test_email_success(mock_send_email, mock_update, mock_context):
    """Тест: успешная отправка тестового email."""
    do_test_email(mock_update, mock_context)
    mock_send_email.assert_called_once()
    mock_update.message.reply_text.assert_any_call("✅ Сообщение успешно отправлено!", parse_mode='HTML')

@patch('telegram_bot.send_email_notification', return_value=False)
def test_do_test_email_failure(mock_send_email, mock_update, mock_context):
    """Тест: неудачная отправка тестового email."""
    do_test_email(mock_update, mock_context)
    mock_send_email.assert_called_once()
    mock_update.message.reply_text.assert_any_call(
        "❌ Не удалось отправить сообщение. Проверьте настройки SMTP в .env и логи.",
        parse_mode='HTML'
    )

@patch('docker.from_env')
def test_restart_auto_unlocker_cmd(mock_docker, mock_update, mock_context):
    """Тест: команда /restart_auto_unlocker."""
    mock_container = MagicMock()
    mock_docker.return_value.containers.get.return_value = mock_container
    
    restart_auto_unlocker_cmd(mock_update, mock_context)
    
    mock_container.restart.assert_called_once()
    mock_update.message.reply_text.assert_any_call("Сервис автооткрытия перезапущен по команде.", parse_mode='HTML') 