
```markdown
# Teacher Bot — Бот-педагог (aiogram 3 + SQLite)

Telegram-бот, который объясняет школьные темы ребёнку через его увлечения. Родитель выбирает ребёнка, указывает тему и уровень тревожности — бот генерирует понятное объяснение с помощью AI (polza.ai).

## Стек

- Python 3.12
- aiogram 3.x
- aiosqlite (SQLite, режим WAL, synchronous = FULL)
- OpenAI SDK (polza.ai)
- APScheduler
- aiohttp

## Структура проекта

```
teacher_bot/
├── bot.py              # точка входа
├── config.py           # загрузка .env
├── states.py           # FSM-состояния диалога
├── prompt.txt          # системный промпт для AI
├── .env                # секреты (не в Git)
├── database/
│   ├── db.py           # подключение к SQLite
│   ├── models.py       # создание таблиц
│   └── queries.py      # все запросы к БД
├── handlers/
│   ├── start.py        # /start, /help
│   ├── dialog.py       # диалог: ребёнок → возраст → хобби → тема → тревожность
│   ├── generate.py     # генерация и регенерация ответа
│   ├── cabinet.py      # /cabinet, /pay, /cancel_sub
│   └── admin.py        # админ-панель
├── keyboards/
│   ├── user_kb.py
│   └── admin_kb.py
├── services/
│   ├── ai_service.py   # запросы к polza.ai
│   └── scheduler.py    # фоновые задачи
└── utils/
    └── exports.py      # экспорт CSV
```

## Установка (локально, Windows)

```bash
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Заполните `.env` по образцу `.env.example`, затем:

```bash
.venv\Scripts\python bot.py
```

## Установка (сервер, Ubuntu)

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

Заполните `.env`, затем:

```bash
systemctl start teacher-bot.service
```

## Переменные окружения (.env)

| Переменная | Описание |
|---|---|
| BOT_TOKEN | Токен Telegram-бота |
| POLZA_API_KEY | API-ключ polza.ai |
| ADMIN_TG_ID | Telegram ID администратора |
| DB_PATH | Путь к базе данных |
| TZ | Часовой пояс (Asia/Novosibirsk) |
| BALANCE_THRESHOLD | Порог баланса для уведомления (руб.) |

## Команды бота

**Пользователь:** /start, /help, /cabinet, /pay, /cancel_sub

**Админ:** /admin, /change_model, /get_users, /get_children, /get_logs, /add_admin, /delete_admin
```
