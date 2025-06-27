# TTLockUnlocker — автоматизация управления замками TTLock через облако

> ⚠️ Важно: используйте только `python-telegram-bot` (см. requirements.txt). Не добавляйте `telegram==0.0.1` — это приведёт к ошибкам импорта!

## О проекте

TTLockUnlocker — комплекс для автоматического и ручного управления замками TTLock через облачный API с уведомлениями в Telegram и Email. Включает:
- **auto_unlocker.py** — сервис для автоматического открытия замка по расписанию, отправки уведомлений о сбоях в Telegram и Email.
- **telegram_bot.py** — Telegram-бот для ручного управления замком, настройки расписания, email и других параметров.
- **unlocker.py** — CLI-утилита для ручной диагностики и тестирования работы с TTLock API.
- **config.json** — файл конфигурации расписания, часового пояса и перерывов (общий для сервисов).
- **.env** — все секретные параметры и настройки (пробрасывается в контейнеры).


## Структура файлов

```
TTLockUnlocker/
├── auto_unlocker.py          # Основной сервис автоматизации
├── telegram_bot.py           # Telegram-бот для управления
├── unlocker.py               # CLI-утилита для ручной диагностики
├── telegram_utils.py         # Утилиты для Telegram и Email
├── ttlock_api.py             # API для работы с TTLock
├── config.json               # Конфигурация расписания и настроек
├── docker-compose.yml        # Docker Compose
├── requirements.txt          # Зависимости Python
├── env/
│   └── .env                  # Переменные окружения
├── logs/
│   ├── auto_unlocker.log
│   └── telegram_bot.log
├── tests/                    # Тесты (pytest)
│   ├── test_auto_unlocker.py
│   ├── test_telegram_bot.py
│   ├── test_telegram_utils.py
│   ├── test_ttlock_api.py
│   └── test_unlocker.py
└── ...
```

## Быстрый старт

### 1. Обновление системы

```bash
sudo apt update && sudo apt upgrade -y
```

### 2. Установка Docker и Docker Compose

```bash
sudo apt install -y docker.io docker-compose
```

### 3. (Опционально) Добавьте пользователя в группу Docker

```bash
sudo usermod -aG docker $USER
```
Выйдите и войдите снова.

### 4. Клонирование проекта

```bash
sudo apt install -y git
git clone https://github.com/Pavel-Bylkov/TTLockUnlocker.git
cd TTLockUnlocker
```

### 5. Настройка проекта

- Отредактируйте `config.json` под своё расписание.
- Создайте и заполните файл окружения:

```bash
mkdir -p env
nano env/.env
```

- Пример `.env`:

```
# TTLock API
TTLOCK_CLIENT_ID=ваш_client_id_из_TTLock_Open_Platform
TTLOCK_CLIENT_SECRET=ваш_client_secret_из_TTLock_Open_Platform
TTLOCK_USERNAME=ваш_email_от_TTLock
TTLOCK_PASSWORD=ваш_пароль_от_TTLock
# TTLOCK_LOCK_ID=опционально

# Telegram
TELEGRAM_BOT_TOKEN=ваш_telegram_bot_token
TELEGRAM_CHAT_ID=ваш_telegram_chat_id
TELEGRAM_CODEWORD=secretword
AUTO_UNLOCKER_CONTAINER=auto_unlocker_1

# Email (для уведомлений о критических сбоях)
SMTP_SERVER=smtp.yandex.ru
SMTP_PORT=465
SMTP_USER=your_login@yandex.ru
SMTP_PASSWORD=your_app_password
EMAIL_TO=recipient@example.com
```

> **Важно!** TTLOCK_USERNAME и TTLOCK_PASSWORD должны быть именно от аккаунта владельца замка (того, кто регистрировал замок в мобильном приложении TTLock). Только этот аккаунт имеет полный доступ к API и может управлять замками через облако.

- Создайте папку для логов и выдайте права:

```bash
mkdir -p logs
chown -R 1000:1000 logs
chmod -R 755 logs
```

### 6. Запуск проекта

Для первого запуска (сборка и запуск контейнеров):

```bash
make start
```
или
```bash
./start.sh
```

Для последующих запусков:

```bash
make up
```

Для остановки:

```bash
make down
```

### 7. Проверка работы

```bash
docker ps
docker logs telegram_bot_1
docker logs auto_unlocker_1
```

## Возможности Telegram-бота

- 📊 **Статус** — состояние расписания, часовой пояс, статус замка, заряд батареи.
- ⏰ **Время** — настройка времени открытия по дням недели.
- ☕ **Перерыв** — добавление/удаление перерывов (замок не открывается в это время).
- 🔓 **Открыть** / 🔒 **Закрыть** — мгновенное управление замком.
- 👥 **Получатель** — смена получателя уведомлений (chat_id) через кодовое слово.
- 📧 **Email** — настройка email для критических уведомлений, тестирование SMTP.
- 📋 **Логи** — просмотр последних логов auto_unlocker.
- 🔄 **Перезапуск** — перезапуск auto_unlocker для применения изменений.

## Email-уведомления

- После 5 неудачных попыток открытия/закрытия замка auto_unlocker отправляет email на EMAIL_TO.
- Используйте "пароль для приложений" для SMTP.

## Логика повторных попыток

- До 10 попыток открытия/закрытия с увеличивающимися интервалами.
- После 5-й неудачи — email-уведомление.
- После всех неудач — критическое уведомление в Telegram и Email.

## config.json

Пример:

```json
{
  "timezone": "Europe/Moscow",
  "schedule_enabled": true,
  "open_times": {
    "Пн": "09:00",
    "Вт": "09:00",
    "Ср": "09:00",
    "Чт": "09:00",
    "Пт": "09:00",
    "Сб": "09:00",
    "Вс": "09:00"
  },
  "breaks": {
    "Пн": [],
    "Вт": [],
    "Ср": [],
    "Чт": [],
    "Пт": [],
    "Сб": [],
    "Вс": []
  }
}
```

## Быстрое ручное тестирование: unlocker.py

- Позволяет вручную проверить работу TTLock API (открытие/закрытие/статус/список замков).
- Используйте для диагностики, если основной сервис не запускается.
- Запуск:

```bash
python unlocker.py
```

## Запуск тестов

```bash
make test
# или
pytest
# Для покрытия:
pytest --cov=.
```

## Устранение неполадок

- **TTLock**: проверьте TTLOCK_CLIENT_ID, TTLOCK_CLIENT_SECRET, TTLOCK_USERNAME, TTLOCK_PASSWORD.
- **Telegram**: проверьте TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, права бота.
- **Email**: используйте пароль для приложений, проверьте SMTP-настройки.
- **Логи**: смотрите в папке logs/ и через docker logs.

## Безопасность

- Никогда не публикуйте .env и логи с секретами.
- Используйте пароли для приложений.
- Регулярно обновляйте систему и зависимости.

## Получение TTLock API Client ID, Secret и Lock ID

1. Зарегистрируйтесь на [TTLock Open Platform](https://open.ttlock.com/).
2. Создайте приложение, получите Client ID и Secret.
3. Lock ID — в мобильном приложении TTLock или в Open Platform (Lock List).


