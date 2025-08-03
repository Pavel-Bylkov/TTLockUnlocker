# Changelog - Исправления и улучшения TTLockUnlocker

## Версия 2.0 - Исправления команд бота

### Исправленные проблемы

#### 1. Проблемы с командами Telegram-бота
- **Исправлено**: Кнопки меню не работали из-за неправильного порядка регистрации обработчиков
- **Исправлено**: Команда `/setemail` не работала из-за проблем с обработкой ошибок
- **Исправлено**: Команда `/settime` не работала из-за отсутствия проверки существования файлов
- **Добавлено**: Функция `cancel_conversation` для отмены диалогов
- **Улучшено**: Обработка ошибок в функции `send_message`

#### 2. Улучшения обработки ошибок
- **Добавлено**: Подробное логирование в `setemail_value` и `settime_value`
- **Исправлено**: Функция `restart_auto_unlocker_and_notify` теперь корректно обрабатывает ошибки Docker
- **Улучшено**: Функция `load_config` теперь возвращает значения по умолчанию при ошибках
- **Добавлено**: Проверка существования файлов перед их чтением/записью

#### 3. Улучшения документации
- **Добавлено**: Подробная инструкция по получению TTLock API параметров
- **Добавлено**: Расширенный раздел "Устранение неполадок" с конкретными решениями
- **Добавлено**: Примеры команд для диагностики
- **Улучшено**: Описание процесса развертывания

#### 4. Новые инструменты
- **Добавлено**: Диагностический скрипт `test_bot_commands.py`
- **Добавлено**: Команда `/cancel` для отмены диалогов
- **Улучшено**: Обработка fallback в ConversationHandler

### Технические изменения

#### telegram_bot.py
```python
# Исправлена функция send_message
def send_message(update, text: str, parse_mode: str = "HTML", **kwargs: Any) -> None:
    # Добавлена проверка типа объекта update
    if hasattr(update, 'message') and update.message:
        update.message.reply_text(text, parse_mode=parse_mode, **kwargs)
    elif hasattr(update, 'callback_query') and update.callback_query:
        update.callback_query.message.reply_text(text, parse_mode=parse_mode, **kwargs)

# Улучшена функция setemail_value
def setemail_value(update, context) -> int:
    # Добавлена проверка существования файла
    if not os.path.exists(ENV_PATH):
        send_message(update, f"Файл {ENV_PATH} не найден.")
        return ConversationHandler.END
    
    # Добавлено подробное логирование
    logger.info(f"Попытка установки email: {email}")

# Улучшена функция settime_value  
def settime_value(update, context):
    # Добавлена проверка существования файла конфигурации
    if not os.path.exists(CONFIG_PATH):
        send_message(update, f"Файл конфигурации {CONFIG_PATH} не найден.")
        return ConversationHandler.END
    
    # Добавлена проверка дня недели в контексте
    day = context.user_data.get("day")
    if not day:
        logger.error("День недели не найден в контексте пользователя")
        send_message(update, "Ошибка: день недели не найден. Попробуйте еще раз.")
        return ConversationHandler.END
```

#### telegram_utils.py
```python
# Улучшена функция load_config
def load_config(config_path, logger=None, default=None):
    # Добавлены значения по умолчанию
    if default is None:
        default = {
            "timezone": "Asia/Novosibirsk",
            "schedule_enabled": True,
            "open_times": {"Пн": "09:00", "Вт": "09:00", ...},
            "breaks": {"Пн": [], "Вт": [], ...}
        }
    
    # Добавлена проверка существования файла
    if not os.path.exists(config_path):
        return default
    
    # Добавлена проверка обязательных полей
    if "timezone" not in config:
        config["timezone"] = default["timezone"]
    # ... и т.д.
```

### Новые файлы

#### test_bot_commands.py
- Диагностический скрипт для проверки настроек
- Проверяет переменные окружения, файлы конфигурации, права доступа
- Выводит подробный отчет о состоянии системы

### Обновленная документация

#### README.md
- Добавлена подробная инструкция по получению TTLock API параметров
- Расширен раздел "Устранение неполадок"
- Добавлены примеры команд для диагностики
- Улучшены инструкции по развертыванию

### Рекомендации для заказчика

1. **Перед запуском**: Выполните `python test_bot_commands.py` для диагностики
2. **При проблемах с ботом**: Перезапустите контейнер `docker-compose restart telegram_bot_1`
3. **Для отладки**: Проверьте логи `docker logs telegram_bot_1`
4. **При смене настроек**: Используйте команду `/cancel` для отмены диалогов

### Известные ограничения

- Бот работает только с одним авторизованным пользователем (TELEGRAM_CHAT_ID)
- Для смены получателя уведомлений требуется кодовое слово
- Email настройки требуют SMTP с поддержкой SSL/TLS

### Совместимость

- Python 3.8+
- Docker 20.10+
- python-telegram-bot 13.15
- Все остальные зависимости остались без изменений 