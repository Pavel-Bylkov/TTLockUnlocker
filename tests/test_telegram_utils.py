import pytest
from telegram_utils import is_authorized

class DummyUpdate:
    class Chat:
        def __init__(self, id):
            self.id = id
    def __init__(self, chat_id):
        self.effective_chat = self.Chat(chat_id)

def test_is_authorized_true():
    update = DummyUpdate(123)
    assert is_authorized(update, 123)

def test_is_authorized_false():
    update = DummyUpdate(123)
    assert not is_authorized(update, 456)

# send_telegram_message лучше тестировать с mock, пример:
def test_send_telegram_message(monkeypatch):
    from telegram_utils import send_telegram_message
    called = {}
    def fake_post(url, data, timeout):
        called['url'] = url
        called['data'] = data
        return type('Resp', (), {'status_code': 200})()
    monkeypatch.setattr('requests.post', fake_post)
    send_telegram_message('token', 123, 'test')
    assert called['url'].startswith('https://api.telegram.org/bot')
    assert called['data']['chat_id'] == 123
    assert called['data']['text'] == 'test' 