VENV = venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
ACTIVATE = . $(VENV)/bin/activate

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

venv: $(VENV)/bin/activate
	$(PIP) install -r requirements.txt
	$(PIP) install pytest pytest-cov

test: venv
	$(PYTHON) -m pytest tests/

test-bot: venv
	$(PYTHON) -m pytest tests/test_telegram_bot.py

test-unlocker: venv
	$(PYTHON) -m pytest tests/test_auto_unlocker.py

build:
	docker-compose build

up: fixperms
	docker-compose up -d

down:
	docker-compose down

start: fixperms build up

fixperms:
	chown -R 1000:1000 logs || true
	chmod -R 755 logs || true
	chmod -R 755 env || true
	chmod 666 config.json || true
	touch blocked_chat_ids.json
	chmod 666 blocked_chat_ids.json 