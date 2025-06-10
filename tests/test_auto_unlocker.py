import pytest
import auto_unlocker
import os
import json

def test_load_config(tmp_path):
    # Создаём временный config.json
    config = {"timezone": "Europe/Moscow", "schedule_enabled": False}
    config_path = tmp_path / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f)
    # Переопределяем CONFIG_PATH
    old = getattr(auto_unlocker, 'CONFIG_PATH', None)
    auto_unlocker.CONFIG_PATH = str(config_path)
    loaded = auto_unlocker.load_config()
    assert loaded["timezone"] == "Europe/Moscow"
    assert loaded["schedule_enabled"] is False
    if old:
        auto_unlocker.CONFIG_PATH = old

def test_send_telegram_message(monkeypatch):
    called = {}
    def fake_post(url, data, timeout):
        called['url'] = url
        called['data'] = data
        return type('Resp', (), {'status_code': 200})()
    monkeypatch.setattr('requests.post', fake_post)
    auto_unlocker.telegram_token = 'token'
    auto_unlocker.telegram_chat_id = '123'
    auto_unlocker.send_telegram_message('test')
    assert called['url'].startswith('https://api.telegram.org/bot')
    assert called['data']['chat_id'] == '123'
    assert called['data']['text'] == 'test' 