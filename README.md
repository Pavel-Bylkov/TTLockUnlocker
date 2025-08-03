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

### Проблемы с TTLock API

**Ошибка: "Не удалось получить токен"**
- Проверьте TTLOCK_CLIENT_ID, TTLOCK_CLIENT_SECRET, TTLOCK_USERNAME, TTLOCK_PASSWORD
- Убедитесь, что TTLOCK_USERNAME и TTLOCK_PASSWORD от аккаунта владельца замка
- Проверьте подключение к интернету

**Ошибка: "Замки не найдены"**
- Убедитесь, что замок добавлен в мобильное приложение TTLock
- Проверьте, что используете аккаунт владельца замка
- Попробуйте перезапустить сервис: `docker-compose restart`

### Проблемы с Telegram-ботом

**Кнопки меню не работают**
- Перезапустите бота: `docker-compose restart telegram_bot_1`
- Проверьте логи: `docker logs telegram_bot_1`
- Убедитесь, что TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID корректны

**Команда /setemail не работает**
- Проверьте права на запись в папку env/
- Убедитесь, что файл .env существует и доступен для записи
- Проверьте логи бота на ошибки

**Команда /settime не работает**
- Проверьте права на запись в config.json
- Убедитесь, что файл config.json существует
- Проверьте логи бота на ошибки

**Бот не отвечает на команды**
- Проверьте TELEGRAM_CHAT_ID - должен совпадать с вашим chat_id
- Убедитесь, что бот добавлен в чат
- Проверьте, что бот не заблокирован

### Проблемы с Email

**Email не отправляется**
- Проверьте SMTP настройки в .env
- Используйте "пароль для приложений" для SMTP_PASSWORD
- Для Yandex: включите "Пароли для приложений" в настройках безопасности
- Проверьте логи: `docker logs auto_unlocker_1`

### Проблемы с Docker

**Контейнеры не запускаются**
```bash
# Проверьте статус
docker-compose ps

# Пересоберите образы
docker-compose build --no-cache

# Перезапустите с логами
docker-compose up
```

**Ошибка прав доступа**
```bash
# Исправьте права на папки
chmod -R 755 logs/
chmod -R 755 env/
chmod 666 config.json

# Для Docker на Linux
sudo chown -R 1000:1000 logs/
```

### Проблемы с расписанием

**Замок не открывается по расписанию**
- Проверьте часовой пояс в config.json
- Убедитесь, что schedule_enabled: true
- Проверьте время открытия в open_times
- Проверьте логи: `docker logs auto_unlocker_1`

**Неправильное время открытия**
- Проверьте timezone в config.json
- Убедитесь, что сервер в правильном часовом поясе
- Перезапустите сервис после изменения timezone

### Диагностика

**Проверка работы API**
```bash
# Запустите тестовую утилиту
python unlocker.py
```

**Проверка логов**
```bash
# Логи auto_unlocker
docker logs auto_unlocker_1

# Логи telegram_bot
docker logs telegram_bot_1

# Логи в файлах
tail -f logs/auto_unlocker.log
tail -f logs/telegram_bot.log
```

**Проверка конфигурации**
```bash
# Проверьте config.json
cat config.json

# Проверьте .env (безопасно)
grep -v PASSWORD env/.env

# Запустите диагностический скрипт
python test_bot_commands.py
```

### Частые ошибки

**"ModuleNotFoundError: No module named 'docker'"**
```bash
# Добавьте docker в requirements.txt
echo "docker==7.0.0" >> requirements.txt
docker-compose build
```

**"Permission denied" при записи файлов**
```bash
# Исправьте права
sudo chown -R $USER:$USER .
chmod -R 755 logs env
chmod 666 config.json
```

**"Connection refused" для Docker**
```bash
# Перезапустите Docker
sudo systemctl restart docker
# или
sudo service docker restart
```

## Безопасность

- Никогда не публикуйте .env и логи с секретами.
- Используйте пароли для приложений.
- Регулярно обновляйте систему и зависимости.

## Получение TTLock API Client ID, Secret и Lock ID

### 1. Регистрация на TTLock Open Platform

1. Перейдите на [TTLock Open Platform](https://open.ttlock.com/)
2. Нажмите "Register" или "Зарегистрироваться"
3. Заполните форму регистрации:
   - Email (будет использоваться как TTLOCK_USERNAME)
   - Пароль (будет использоваться как TTLOCK_PASSWORD)
   - Подтвердите пароль
4. Подтвердите email через письмо, которое придет на указанный адрес

### 2. Создание приложения и получение Client ID/Secret

1. Войдите в свой аккаунт на [TTLock Open Platform](https://open.ttlock.com/)
2. Перейдите в раздел "Applications" или "Приложения"
3. Нажмите "Create Application" или "Создать приложение"
4. Заполните форму:
   - **Application Name**: любое название (например, "TTLockUnlocker")
   - **Description**: описание проекта
   - **Platform**: выберите "Web" или "Server"
   - **Callback URL**: оставьте пустым или укажите `http://localhost`
5. Нажмите "Submit" или "Отправить"
6. После создания приложения вы получите:
   - **Client ID** (скопируйте в TTLOCK_CLIENT_ID)
   - **Client Secret** (скопируйте в TTLLOCK_CLIENT_SECRET)

### 3. Получение Lock ID

#### Способ 1: Через мобильное приложение TTLock

1. Установите приложение TTLock на телефон
2. Войдите в аккаунт (используйте тот же email, что и при регистрации на Open Platform)
3. Добавьте замок в приложение (если еще не добавлен)
4. Откройте замок в приложении
5. Нажмите на замок → "Settings" → "Advanced" → "Lock ID"
6. Скопируйте Lock ID (это будет TTLOCK_LOCK_ID)

#### Способ 2: Через TTLock Open Platform

1. Войдите в [TTLock Open Platform](https://open.ttlock.com/)
2. Перейдите в раздел "Lock List" или "Список замков"
3. Найдите ваш замок в списке
4. Скопируйте Lock ID из таблицы

#### Способ 3: Автоматическое определение (рекомендуется)

Если у вас только один замок, можно оставить TTLOCK_LOCK_ID пустым в .env файле. Система автоматически определит Lock ID при первом запуске.

### 4. Проверка параметров

После получения всех параметров проверьте их:

```bash
# Запустите тестовую утилиту
python unlocker.py
```

Если все параметры верны, вы увидите список замков и сможете протестировать открытие/закрытие.

### 5. Пример .env файла

```env
# TTLock API (получены с Open Platform)
TTLOCK_CLIENT_ID=your_client_id_here
TTLOCK_CLIENT_SECRET=your_client_secret_here
TTLOCK_USERNAME=your_email@example.com
TTLOCK_PASSWORD=your_password_here
# TTLOCK_LOCK_ID=optional_lock_id_here

# Telegram (получены от @BotFather)
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
TELEGRAM_CODEWORD=secretword

# Email (для критических уведомлений)
EMAIL_TO=your_email@example.com
SMTP_SERVER=smtp.yandex.ru
SMTP_PORT=465
SMTP_USER=your_email@yandex.ru
SMTP_PASSWORD=your_app_password_here
```

### Важные замечания

- **TTLOCK_USERNAME и TTLOCK_PASSWORD** должны быть от аккаунта владельца замка
- Используйте "пароль для приложений" для SMTP (не основной пароль от email)
- Lock ID можно оставить пустым - система определит его автоматически
- Все параметры чувствительны к регистру и пробелам


