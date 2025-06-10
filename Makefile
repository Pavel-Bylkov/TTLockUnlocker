build:
	docker-compose build

up: fixperms
	docker-compose up -d

down:
	docker-compose down

test:
	pytest tests/

start: fixperms build up

fixperms:
	chown -R 1000:1000 logs || true
	chmod -R 755 logs || true
	chmod -R 755 env || true
	chmod 666 config.json || true 