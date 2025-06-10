import pytest
import ttlock_api

class DummyLogger:
    def __init__(self):
        self.logs = []
    def info(self, msg):
        self.logs.append(('info', msg))
    def error(self, msg):
        self.logs.append(('error', msg))
    def debug(self, msg):
        self.logs.append(('debug', msg))

@pytest.fixture
def logger():
    return DummyLogger()

def test_get_token(monkeypatch, logger):
    def fake_post(url, data, timeout, verify):
        class Resp:
            def json(self):
                return {'access_token': 'token123'}
            text = '{"access_token": "token123"}'
        return Resp()
    monkeypatch.setattr('requests.post', fake_post)
    token = ttlock_api.get_token(logger)
    assert token == 'token123'

def test_unlock_lock_success(monkeypatch, logger):
    def fake_post(url, data, verify):
        class Resp:
            def json(self):
                return {'errcode': 0}
            text = '{"errcode": 0}'
        return Resp()
    monkeypatch.setattr('requests.post', fake_post)
    resp = ttlock_api.unlock_lock('token', 'lockid', logger)
    assert resp['errcode'] == 0

def test_unlock_lock_fail(monkeypatch, logger):
    def fake_post(url, data, verify):
        class Resp:
            def json(self):
                return {'errcode': 1, 'errmsg': 'fail'}
            text = '{"errcode": 1, "errmsg": "fail"}'
        return Resp()
    monkeypatch.setattr('requests.post', fake_post)
    resp = ttlock_api.unlock_lock('token', 'lockid', logger)
    assert resp['errcode'] == 1 