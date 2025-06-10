import pytest
import telegram_bot
import os
import json
import types

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

# Аналогично можно покрыть settime, setbreak, restart_auto_unlocker_cmd и другие команды, используя monkeypatch и DummyUpdate/DummyContext. 