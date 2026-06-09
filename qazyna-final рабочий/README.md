# QazynaDelivery Bot (простая версия)

Telegram-бот для доставки продуктов. Без Docker, без Redis, без Pydantic — минимум зависимостей, всё работает "из коробки".

## Что внутри

- **aiogram 3.13** + SQLite (MemoryStorage для FSM)
- 4 файла Python: `main.py`, `database.py`, `keyboards.py`, `locales.py` + `config.py`, `states.py`
- Только русский язык (казахский и английский убраны за ненадобностью)
- Демо-данные (6 категорий, 14 товаров) сидятся при первом запуске

## Запуск

### 1. Создай `.env`

```bash
cp .env.example .env
```

Открой `.env` и впиши:
```
BOT_TOKEN=сюда_токен_от_BotFather
ADMIN_ID=свой_telegram_id
```

### 2. Создай виртуальное окружение

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Поставь зависимости

```bash
pip install -r requirements.txt
```

### 4. Запусти

```bash
python main.py
```

Если всё ок, увидишь:
```
2025-01-01 12:00:00 - main - INFO - Database initialized
2025-01-01 12:00:00 - main - INFO - Bot started
```

### 5. Проверь в Telegram

1. Открой своего бота
2. `/start` — главное меню
3. `/admin` — админ-панель (доступна только тебе)
4. Добавь товар: 🛠 Управление товарами → ➕ Добавить товар

## Что исправлено относительно исходной версии

**Главный баг** — добавление товара не работало из-за того, что aiogram регистрирует хендлеры в порядке файла. Хендлер редактирования перехватывал ввод при добавлении.

Решено: 3 отдельных `StatesGroup`:
- `AdminAddProductState` — добавление
- `AdminEditProductState` — редактирование
- `AdminAddCategoryState` — добавление категории

**Дополнительные баги**:
- Функция `_` конфликтовала с `locale` модулем → переименована в `t`
- `edit_text` падал на фото-сообщениях с `BadRequest: no text` → используется `resend` (delete + answer) который надёжно работает
- В 3 языках (ru/kk/en) все 87 ключей одинаковые

## Структура

```
qazyna-simple/
├── main.py            # Все хендлеры + запуск
├── database.py        # БД + все запросы
├── keyboards.py       # Кнопки
├── locales.py         # Тексты
├── config.py          # .env + константы
├── states.py          # FSM состояния
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Что убрано (по сравнению с предыдущей версией)

- ❌ Docker / docker-compose
- ❌ Redis (используется MemoryStorage)
- ❌ Pydantic Settings (просто os.getenv)
- ❌ structlog (стандартный logging)
- ❌ Connection pool (aiosqlite сам справляется)
- ❌ Throttling middleware
- ❌ Health check
- ❌ Казахский и английский языки
- ❌ Categories cache
- ❌ Graceful shutdown
- ❌ Уведомления админу о критичных ошибках

Для тестового запуска всё это не нужно. Если захочешь в прод — лучше вернись к полной версии с Docker.
