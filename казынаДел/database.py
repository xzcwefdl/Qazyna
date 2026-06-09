import logging
import re
import sqlite3
from typing import Any, Dict, List, Optional

import aiosqlite
from config import REFERRAL_REWARD

logger = logging.getLogger(__name__)
DATABASE_PATH = "qazyna_delivery.db"
_db_pool = None  # connection pool (singleton)


# ==================== Валидация ====================

PHONE_RE = re.compile(r"^\+?[\d\s\-\(\)]{10,20}$")
PRICE_RE = re.compile(r"^\d+(?:[.,]\d{1,2})?$")


def validate_phone(phone: str) -> bool:
    """Валидация телефона"""
    return bool(PHONE_RE.match(phone.strip()))


def validate_price(price_str: str) -> Optional[float]:
    """Валидация цены. Возвращает float или None"""
    cleaned = price_str.strip().replace(" ", "").replace(",", ".")
    if not PRICE_RE.match(cleaned):
        return None
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


def validate_address(address: str) -> bool:
    """Валидация адреса — минимум 5 символов"""
    return len(address.strip()) >= 5


def mask_phone(phone: str) -> str:
    """Маскировка телефона для логов и админ-вывода"""
    if not phone:
        return "***"
    p = phone.strip()
    if len(p) >= 7:
        return p[:3] + "***" + p[-2:]
    return "***"


# ==================== Pool & Миграции ====================


async def _get_db() -> aiosqlite.Connection:
    """Получить соединение из пула (singleton)"""
    global _db_pool
    if _db_pool is None:
        _db_pool = await aiosqlite.connect(DATABASE_PATH, timeout=30)
        await _db_pool.execute("PRAGMA journal_mode=WAL")
        await _db_pool.execute("PRAGMA busy_timeout=30000")
        await _db_pool.execute("PRAGMA foreign_keys=ON")
    return _db_pool


async def close_db():
    """Закрыть соединение с БД"""
    global _db_pool
    if _db_pool:
        await _db_pool.close()
        _db_pool = None
        logger.info("База данных закрыта")


async def _column_exists(db: aiosqlite.Connection, table: str, column: str) -> bool:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    return any(row[1] == column for row in rows)


async def _run_migrations(db: aiosqlite.Connection):
    """Простая система миграций"""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL DEFAULT 0
        )
    """)
    await db.commit()

    cursor = await db.execute("SELECT version FROM schema_version WHERE id = 1")
    row = await cursor.fetchone()
    current = row[0] if row else 0

    migrations = [
        lambda db: _migration_v1(db),
        lambda db: _migration_v2(db),
        lambda db: _migration_v3(db),
    ]

    for i, mig in enumerate(migrations, start=1):
        if current < i:
            logger.info(f"Применяю миграцию {i}...")
            await mig(db)
            await db.execute(
                "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
                (i,),
            )
            await db.commit()
            logger.info(f"Миграция {i} применена")


async def _migration_v1(db: aiosqlite.Connection):
    """Базовая схема + индексы"""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            first_name TEXT,
            last_name TEXT,
            phone TEXT,
            address TEXT,
            language TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            emoji TEXT DEFAULT '📦',
            sort_order INTEGER DEFAULT 0
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            photo_file_id TEXT,
            is_active BOOLEAN DEFAULT 1,
            description TEXT,
            stock INTEGER DEFAULT 999,
            FOREIGN KEY (category_id) REFERENCES categories(id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS cart_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total_amount REAL NOT NULL,
            status TEXT DEFAULT 'new',
            delivery_time TEXT,
            payment_method TEXT,
            comment TEXT,
            address TEXT,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            price_at_moment REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)
    # Индексы
    await db.execute("CREATE INDEX IF NOT EXISTS idx_cart_user ON cart_items(user_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id)"
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_users_tg ON users(telegram_id)")
    # 🔧 FIX: индекс для быстрой фильтрации по дате (24ч архивация)
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_status_created ON orders(status, created_at)"
    )


async def _migration_v2(db: aiosqlite.Connection):
    """Дополнительные таблицы"""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            label TEXT DEFAULT 'Основной',
            address TEXT NOT NULL,
            is_default BOOLEAN DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id),
            UNIQUE(user_id, product_id)
        )
    """)
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_addresses_user ON addresses(user_id)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id)"
    )


async def _migration_v3(db: aiosqlite.Connection):
    """Реферальная программа, поддержка, статистика"""
    if not await _column_exists(db, "users", "referral_code"):
        await db.execute("ALTER TABLE users ADD COLUMN referral_code TEXT")
    if not await _column_exists(db, "users", "referred_by"):
        await db.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
    if not await _column_exists(db, "users", "referral_balance"):
        await db.execute("ALTER TABLE users ADD COLUMN referral_balance REAL DEFAULT 0")
    if not await _column_exists(db, "users", "referral_count"):
        await db.execute(
            "ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0"
        )

    await db.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL,
            reward_amount REAL DEFAULT 500,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (referrer_id) REFERENCES users(id),
            FOREIGN KEY (referred_id) REFERENCES users(id),
            UNIQUE(referred_id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            user_telegram_id INTEGER NOT NULL,
            user_message_id INTEGER,
            support_chat_id INTEGER,
            support_message_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_support_msg_support ON support_messages(support_message_id)"
    )


async def init_db():
    """Инициализация базы данных"""
    db = await _get_db()
    await _run_migrations(db)
    await _seed_demo_data(db)


async def _seed_demo_data(db: aiosqlite.Connection):
    """Заполнение демо-данными"""
    cursor = await db.execute("SELECT COUNT(*) FROM categories")
    count = await cursor.fetchone()

    if count[0] == 0:
        categories = [
            ("Молочное", "🥛", 1),
            ("Хлеб и выпечка", "🍞", 2),
            ("Овощи и фрукты", "🍎", 3),
            ("Мясо и птица", "🥩", 4),
            ("Бытовая химия", "🧼", 5),
            ("Напитки", "🥤", 6),
        ]
        await db.executemany(
            "INSERT INTO categories (name, emoji, sort_order) VALUES (?, ?, ?)",
            categories,
        )

        products = [
            (1, "Молоко 3.2% 1л", 89.0, "Свежее молоко высшего качества", None),
            (1, "Творог 9% 200г", 120.0, "Домашний творог", None),
            (1, "Сметана 20% 300г", 95.0, "Густая сметана", None),
            (1, "Масло сливочное 82%", 180.0, "Натуральное сливочное масло", None),
            (1, "Йогурт натуральный", 65.0, "Без добавок", None),
            (2, "Батон нарезной", 45.0, "Свежий батон", None),
            (2, "Хлеб Бородинский", 55.0, "Классический ржаной", None),
            (2, "Булочки с маком 4шт", 80.0, "Сдобные булочки", None),
            (2, "Лаваш армянский", 70.0, "Тонкий лаваш", None),
            (3, "Яблоки Гала 1кг", 120.0, "Сладкие и сочные", None),
            (3, "Бананы 1кг", 95.0, "Спелые бананы", None),
            (3, "Помидоры розовые 1кг", 150.0, "Мясистые помидоры", None),
            (3, "Огурцы свежие 1кг", 110.0, "Хрустящие огурцы", None),
            (3, "Картофель 1кг", 45.0, "Молодой картофель", None),
            (3, "Лук репчатый 1кг", 35.0, "Свежий лук", None),
            (4, "Куриное филе 1кг", 320.0, "Фермерское куриное филе", None),
            (4, "Фарш говяжий 500г", 280.0, "Свежий говяжий фарш", None),
            (4, "Свинина шея 1кг", 350.0, "Мраморная свинина", None),
            (4, "Колбаса докторская", 180.0, "Классическая докторская", None),
            (5, "Моющее средство 1л", 150.0, "Для посуды", None),
            (5, "Порошок стиральный 2кг", 280.0, "Универсальный", None),
            (5, "Зубная паста", 95.0, "Отбеливающая", None),
            (5, "Туалетная бумага 4шт", 120.0, "Двухслойная", None),
            (6, "Вода минеральная 1.5л", 55.0, "Газированная", None),
            (6, "Сок апельсиновый 1л", 110.0, "Натуральный", None),
            (6, "Кофе растворимый", 250.0, "Крепкий аромат", None),
        ]

        await db.executemany(
            """INSERT INTO products (category_id, name, price, description, photo_file_id)
               VALUES (?, ?, ?, ?, ?)""",
            products,
        )

        await db.commit()


# ==================== Пользователи ====================


async def get_or_create_user(
    telegram_id: int, first_name: str = None, last_name: str = None
) -> Dict:
    """Получить или создать пользователя"""
    db = await _get_db()
    db.row_factory = aiosqlite.Row
    cursor = await db.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    )
    user = await cursor.fetchone()

    if user:
        user = dict(user)
        if not user.get("referral_code"):
            code = f"ref{telegram_id}"
            await db.execute(
                "UPDATE users SET referral_code = ? WHERE id = ?", (code, user["id"])
            )
            await db.commit()
            user["referral_code"] = code
        return user

    code = f"ref{telegram_id}"
    await db.execute(
        "INSERT INTO users (telegram_id, first_name, last_name, language, referral_code) VALUES (?, ?, ?, NULL, ?)",
        (telegram_id, first_name, last_name, code),
    )
    await db.commit()

    cursor = await db.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    )
    user = await cursor.fetchone()
    return dict(user)


async def update_user_profile(user_id: int, phone: str = None, address: str = None):
    """Обновить профиль пользователя"""
    db = await _get_db()
    if phone:
        await db.execute("UPDATE users SET phone = ? WHERE id = ?", (phone, user_id))
    if address:
        await db.execute(
            "UPDATE users SET address = ? WHERE id = ?", (address, user_id)
        )
    await db.commit()


async def get_user_by_telegram_id(telegram_id: int) -> Optional[Dict]:
    """Получить пользователя по Telegram ID"""
    db = await _get_db()
    db.row_factory = aiosqlite.Row
    cursor = await db.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    )
    user = await cursor.fetchone()
    return dict(user) if user else None


async def get_user_by_id(user_id: int) -> Optional[Dict]:
    """Получить пользователя по ID"""
    db = await _get_db()
    db.row_factory = aiosqlite.Row
    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_user_by_referral_code(code: str) -> Optional[Dict]:
    """Получить пользователя по реферальному коду"""
    db = await _get_db()
    db.row_factory = aiosqlite.Row
    cursor = await db.execute("SELECT * FROM users WHERE referral_code = ?", (code,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def apply_referral(referred_id: int, referrer_code: str) -> bool:
    """Применить реферальный код. Начисляет бонусы рефереру и приглашенному."""
    db = await _get_db()
    cursor = await db.execute(
        "SELECT id FROM users WHERE referral_code = ?", (referrer_code,)
    )
    referrer = await cursor.fetchone()
    if not referrer:
        return False
    referrer_id = referrer[0]
    if referrer_id == referred_id:
        return False
    cursor = await db.execute(
        "SELECT referred_by FROM users WHERE id = ?", (referred_id,)
    )
    row = await cursor.fetchone()
    if row and row[0]:
        return False
    # update referred
    await db.execute(
        "UPDATE users SET referred_by = ? WHERE id = ?", (referrer_id, referred_id)
    )
    # record
    await db.execute(
        "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, reward_amount) VALUES (?, ?, ?)",
        (referrer_id, referred_id, REFERRAL_REWARD),
    )
    # reward referrer
    await db.execute(
        "UPDATE users SET referral_balance = referral_balance + ?, referral_count = referral_count + 1 WHERE id = ?",
        (REFERRAL_REWARD, referrer_id),
    )
    # reward referred too
    await db.execute(
        "UPDATE users SET referral_balance = referral_balance + ? WHERE id = ?",
        (REFERRAL_REWARD, referred_id),
    )
    await db.commit()
    return True


async def use_referral_balance(user_id: int, amount: float) -> bool:
    """Списать бонусный баланс"""
    db = await _get_db()
    cursor = await db.execute(
        "UPDATE users SET referral_balance = referral_balance - ? WHERE id = ? AND referral_balance >= ?",
        (amount, user_id, amount),
    )
    await db.commit()
    return cursor.rowcount > 0


# ==================== Язык ====================


async def get_user_language(telegram_id: int) -> str:
    """Получить язык пользователя"""
    db = await _get_db()
    cursor = await db.execute(
        "SELECT language FROM users WHERE telegram_id = ?", (telegram_id,)
    )
    result = await cursor.fetchone()
    return result[0] if result and result[0] else "ru"


async def update_user_language(telegram_id: int, language: str):
    """Обновить язык пользователя"""
    db = await _get_db()
    await db.execute(
        "UPDATE users SET language = ? WHERE telegram_id = ?", (language, telegram_id)
    )
    await db.commit()


# ==================== Категории и товары ====================


async def get_categories() -> List[Dict]:
    """Получить все категории"""
    db = await _get_db()
    db.row_factory = aiosqlite.Row
    cursor = await db.execute("SELECT * FROM categories ORDER BY sort_order")
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_products_by_category(category_id: int) -> List[Dict]:
    """Получить товары по категории"""
    db = await _get_db()
    db.row_factory = aiosqlite.Row
    cursor = await db.execute(
        """SELECT * FROM products
           WHERE category_id = ? AND is_active = 1
           ORDER BY name""",
        (category_id,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_product(product_id: int) -> Optional[Dict]:
    """Получить товар по ID"""
    db = await _get_db()
    db.row_factory = aiosqlite.Row
    cursor = await db.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def check_stock(product_id: int, quantity: int) -> bool:
    """Проверить достаточно ли товара на складе"""
    db = await _get_db()
    cursor = await db.execute("SELECT stock FROM products WHERE id = ?", (product_id,))
    result = await cursor.fetchone()
    if not result:
        return False
    return result[0] >= quantity


async def decrease_stock(product_id: int, quantity: int):
    """Уменьшить остаток товара"""
    db = await _get_db()
    await db.execute(
        "UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product_id)
    )
    await db.commit()


# ==================== Корзина ====================


async def get_cart_items(user_id: int) -> List[Dict]:
    """Получить товары в корзине"""
    db = await _get_db()
    db.row_factory = aiosqlite.Row
    cursor = await db.execute(
        """SELECT c.*, p.name, p.price, p.photo_file_id
           FROM cart_items c
           JOIN products p ON c.product_id = p.id
           WHERE c.user_id = ?""",
        (user_id,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_cart_total(user_id: int) -> float:
    """Получить сумму корзины"""
    db = await _get_db()
    cursor = await db.execute(
        """SELECT SUM(c.quantity * p.price) as total
           FROM cart_items c
           JOIN products p ON c.product_id = p.id
           WHERE c.user_id = ?""",
        (user_id,),
    )
    result = await cursor.fetchone()
    return result[0] or 0.0


async def add_to_cart(user_id: int, product_id: int, quantity: int = 1) -> bool:
    """Добавить товар в корзину. Возвращает False если недостаточно на складе"""
    if not await check_stock(product_id, quantity):
        return False

    db = await _get_db()
    cursor = await db.execute(
        "SELECT id, quantity FROM cart_items WHERE user_id = ? AND product_id = ?",
        (user_id, product_id),
    )
    existing = await cursor.fetchone()

    if existing:
        new_qty = existing[1] + quantity
        if not await check_stock(product_id, new_qty):
            return False
        await db.execute(
            "UPDATE cart_items SET quantity = ? WHERE id = ?", (new_qty, existing[0])
        )
    else:
        await db.execute(
            "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, ?)",
            (user_id, product_id, quantity),
        )
    await db.commit()
    return True


async def update_cart_quantity(cart_item_id: int, quantity: int):
    """Обновить количество товара в корзине"""
    db = await _get_db()
    if quantity <= 0:
        await db.execute("DELETE FROM cart_items WHERE id = ?", (cart_item_id,))
    else:
        await db.execute(
            "UPDATE cart_items SET quantity = ? WHERE id = ?", (quantity, cart_item_id)
        )
    await db.commit()


async def remove_from_cart(cart_item_id: int):
    """Удалить товар из корзины"""
    db = await _get_db()
    await db.execute("DELETE FROM cart_items WHERE id = ?", (cart_item_id,))
    await db.commit()


async def clear_cart(user_id: int):
    """Очистить корзину"""
    db = await _get_db()
    await db.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
    await db.commit()


# ==================== Заказы ====================


async def create_order(
    user_id: int,
    total_amount: float,
    delivery_time: str,
    payment_method: str,
    comment: str,
    address: str,
    phone: str,
) -> int:
    """Создать заказ"""
    db = await _get_db()
    cursor = await db.execute(
        """INSERT INTO orders (user_id, total_amount, delivery_time, payment_method,
            comment, address, phone, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'new')""",
        (user_id, total_amount, delivery_time, payment_method, comment, address, phone),
    )
    await db.commit()
    return cursor.lastrowid


async def add_order_items(order_id: int, items: List[Dict]):
    """Добавить позиции в заказ"""
    db = await _get_db()
    for item in items:
        await db.execute(
            """INSERT INTO order_items (order_id, product_id, quantity, price_at_moment)
               VALUES (?, ?, ?, ?)""",
            (order_id, item["product_id"], item["quantity"], item["price"]),
        )
        await decrease_stock(item["product_id"], item["quantity"])
    await db.commit()


async def get_order(order_id: int) -> Optional[Dict]:
    """Получить заказ по ID"""
    db = await _get_db()
    db.row_factory = aiosqlite.Row
    cursor = await db.execute(
        """SELECT o.*, u.telegram_id, u.first_name, u.last_name
           FROM orders o
           JOIN users u ON o.user_id = u.id
           WHERE o.id = ?""",
        (order_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_order_items(order_id: int) -> List[Dict]:
    """Получить позиции заказа"""
    db = await _get_db()
    db.row_factory = aiosqlite.Row
    cursor = await db.execute(
        """SELECT oi.*, p.name
           FROM order_items oi
           JOIN products p ON oi.product_id = p.id
           WHERE oi.order_id = ?""",
        (order_id,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def update_order_status(order_id: int, status: str):
    """Обновить статус заказа"""
    db = await _get_db()
    await db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    await db.commit()


async def get_user_orders(user_id: int, limit: int = 5) -> List[Dict]:
    """Получить заказы пользователя"""
    db = await _get_db()
    db.row_factory = aiosqlite.Row
    cursor = await db.execute(
        """SELECT * FROM orders
           WHERE user_id = ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (user_id, limit),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_all_orders(
    status: str = None, limit: int = 50, include_archived: bool = False
) -> List[Dict]:
    """Получить все заказы (для админа)."""
    db = await _get_db()
    db.row_factory = aiosqlite.Row

    base_query = """SELECT o.*, u.telegram_id, u.first_name, u.last_name
                    FROM orders o
                    JOIN users u ON o.user_id = u.id"""

    conditions = []
    params = []

    if status:
        conditions.append("o.status = ?")
        params.append(status)

    if not include_archived:
        conditions.append(
            "NOT (o.status IN ('sent', 'delivered') "
            "AND o.created_at < datetime('now', '-24 hours'))"
        )

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    query = base_query + where_clause + " ORDER BY o.created_at DESC LIMIT ?"
    params.append(limit)

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def cancel_order_user(order_id: int, user_id: int) -> bool:
    """Отменить заказ пользователем (только если статус 'new')"""
    db = await _get_db()
    cursor = await db.execute(
        """SELECT status, user_id FROM orders WHERE id = ?""", (order_id,)
    )
    row = await cursor.fetchone()
    if not row or row[0] != "new" or row[1] != user_id:
        return False

    items = await get_order_items(order_id)
    for item in items:
        await db.execute(
            "UPDATE products SET stock = stock + ? WHERE id = ?",
            (item["quantity"], item["product_id"]),
        )

    await db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
    await db.commit()
    return True


async def reorder(order_id: int, user_id: int) -> bool:
    """Повторить заказ — добавить товары в корзину"""
    db = await _get_db()
    cursor = await db.execute(
        """SELECT user_id FROM orders WHERE id = ?""", (order_id,)
    )
    row = await cursor.fetchone()
    if not row or row[0] != user_id:
        return False

    items = await get_order_items(order_id)
    for item in items:
        await add_to_cart(user_id, item["product_id"], item["quantity"])
    return True


# ==================== Админ: управление товарами ====================


async def add_product(
    category_id: int,
    name: str,
    price: float,
    description: str = None,
    photo_file_id: str = None,
) -> int:
    """Добавить новый товар"""
    db = await _get_db()
    cursor = await db.execute(
        """INSERT INTO products (category_id, name, price, description, photo_file_id, is_active)
           VALUES (?, ?, ?, ?, ?, 1)""",
        (category_id, name, price, description, photo_file_id),
    )
    await db.commit()
    return cursor.lastrowid


async def update_product(
    product_id: int,
    name: str = None,
    price: float = None,
    description: str = None,
    photo_file_id: str = None,
    is_active: bool = None,
):
    """Обновить товар"""
    db = await _get_db()
    updates = []
    params = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if price is not None:
        updates.append("price = ?")
        params.append(price)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if photo_file_id is not None:
        updates.append("photo_file_id = ?")
        params.append(photo_file_id)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(is_active)

    if updates:
        params.append(product_id)
        await db.execute(
            f"UPDATE products SET {', '.join(updates)} WHERE id = ?", params
        )
        await db.commit()


async def delete_product(product_id: int):
    """Удалить товар (деактивировать)"""
    db = await _get_db()
    await db.execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))
    await db.commit()


async def add_category(name: str, emoji: str = "📦", sort_order: int = 0) -> int:
    """Добавить новую категорию"""
    db = await _get_db()
    cursor = await db.execute(
        "INSERT INTO categories (name, emoji, sort_order) VALUES (?, ?, ?)",
        (name, emoji, sort_order),
    )
    await db.commit()
    return cursor.lastrowid


# ==================== Поддержка ====================


async def save_support_message(
    user_id: int,
    user_telegram_id: int,
    user_message_id: int,
    support_chat_id: int,
    support_message_id: int,
):
    """Сохранить связь сообщения поддержки"""
    db = await _get_db()
    await db.execute(
        "INSERT INTO support_messages (user_id, user_telegram_id, user_message_id, support_chat_id, support_message_id) VALUES (?, ?, ?, ?, ?)",
        (
            user_id,
            user_telegram_id,
            user_message_id,
            support_chat_id,
            support_message_id,
        ),
    )
    await db.commit()


async def get_support_message_by_support_id(support_message_id: int) -> Optional[Dict]:
    """Найти сообщение по ID в чате поддержки"""
    db = await _get_db()
    db.row_factory = aiosqlite.Row
    cursor = await db.execute(
        "SELECT * FROM support_messages WHERE support_message_id = ?",
        (support_message_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


# ==================== Статистика ====================


async def get_stats_day() -> dict:
    """Статистика за сегодня"""
    db = await _get_db()
    cursor = await db.execute("""
        SELECT COUNT(*), COALESCE(SUM(total_amount), 0), COALESCE(AVG(total_amount), 0)
        FROM orders
        WHERE date(created_at) = date('now') AND status != 'cancelled'
    """)
    row = await cursor.fetchone()
    cursor = await db.execute("""
        SELECT COUNT(*) FROM orders WHERE date(created_at) = date('now') AND status = 'cancelled'
    """)
    cancelled = await cursor.fetchone()
    return {
        "orders": row[0] or 0,
        "revenue": row[1] or 0,
        "avg_check": row[2] or 0,
        "cancelled": cancelled[0] or 0,
    }


async def get_stats_week() -> dict:
    """Статистика за неделю"""
    db = await _get_db()
    cursor = await db.execute("""
        SELECT COUNT(*), COALESCE(SUM(total_amount), 0), COALESCE(AVG(total_amount), 0)
        FROM orders
        WHERE created_at >= date('now', '-7 days') AND status != 'cancelled'
    """)
    row = await cursor.fetchone()
    cursor = await db.execute("""
        SELECT COUNT(*) FROM orders WHERE created_at >= date('now', '-7 days') AND status = 'cancelled'
    """)
    cancelled = await cursor.fetchone()
    return {
        "orders": row[0] or 0,
        "revenue": row[1] or 0,
        "avg_check": row[2] or 0,
        "cancelled": cancelled[0] or 0,
    }


async def get_top_products(period: str = "day", limit: int = 3) -> List[Dict]:
    """Топ товаров за период"""
    db = await _get_db()
    db.row_factory = aiosqlite.Row
    if period == "day":
        date_filter = "date(o.created_at) = date('now')"
    else:
        date_filter = "o.created_at >= date('now', '-7 days')"
    cursor = await db.execute(
        f"""
        SELECT p.name, SUM(oi.quantity) as qty, SUM(oi.quantity * oi.price_at_moment) as revenue
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        JOIN products p ON oi.product_id = p.id
        WHERE {date_filter} AND o.status != 'cancelled'
        GROUP BY oi.product_id
        ORDER BY qty DESC
        LIMIT ?
    """,
        (limit,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]
