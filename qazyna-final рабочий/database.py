"""БД. Без пула, без миграций с версионированием — просто CREATE IF NOT EXISTS."""

import re
import sqlite3
from typing import Optional
import aiosqlite

from config import DATABASE_PATH, REFERRAL_REWARD

PHONE_RE = re.compile(r"^\+?[\d\s\-\(\)]{10,20}$")
PRICE_RE = re.compile(r"^\d+(?:[.,]\d{1,2})?$")


def validate_phone(p: str) -> bool:
    return bool(PHONE_RE.match(p.strip()))


def validate_price(s: str) -> Optional[float]:
    s = s.strip().replace(" ", "").replace(",", ".")
    if not PRICE_RE.match(s):
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def validate_address(a: str) -> bool:
    return len(a.strip()) >= 5


async def _db():
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await _db()
    try:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            first_name TEXT, last_name TEXT,
            phone TEXT, address TEXT, language TEXT,
            referral_code TEXT, referred_by INTEGER,
            referral_balance REAL DEFAULT 0,
            referral_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, emoji TEXT DEFAULT '📦',
            sort_order INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL, price REAL NOT NULL,
            photo_file_id TEXT, is_active BOOLEAN DEFAULT 1,
            description TEXT, stock INTEGER DEFAULT 999,
            FOREIGN KEY (category_id) REFERENCES categories(id)
        );
        CREATE TABLE IF NOT EXISTS cart_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total_amount REAL NOT NULL,
            status TEXT DEFAULT 'new',
            delivery_time TEXT, payment_method TEXT,
            comment TEXT, address TEXT, phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            price_at_moment REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        CREATE TABLE IF NOT EXISTS addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, label TEXT DEFAULT 'Основной',
            address TEXT NOT NULL, is_default BOOLEAN DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            user_telegram_id INTEGER NOT NULL,
            user_message_id INTEGER, support_chat_id INTEGER,
            support_message_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL,
            reward_amount REAL DEFAULT 500,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(referred_id)
        );
        CREATE INDEX IF NOT EXISTS idx_cart_user ON cart_items(user_id);
        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
        CREATE INDEX IF NOT EXISTS idx_users_tg ON users(telegram_id);
        """)
        await db.commit()

        # Демо-данные
        cur = await db.execute("SELECT COUNT(*) FROM categories")
        if (await cur.fetchone())[0] == 0:
            await db.executemany(
                "INSERT INTO categories (name, emoji, sort_order) VALUES (?, ?, ?)",
                [("Молочное","🥛",1),("Хлеб и выпечка","🍞",2),
                 ("Овощи и фрукты","🍎",3),("Мясо и птица","🥩",4),
                 ("Бытовая химия","🧼",5),("Напитки","🥤",6)],
            )
            await db.executemany(
                """INSERT INTO products (category_id, name, price, description)
                   VALUES (?, ?, ?, ?)""",
                [(1,"Молоко 3.2% 1л",89,"Свежее молоко"),
                 (1,"Творог 9% 200г",120,"Домашний"),
                 (1,"Сметана 20% 300г",95,"Густая"),
                 (2,"Батон нарезной",45,"Свежий"),
                 (2,"Хлеб Бородинский",55,"Ржаной"),
                 (3,"Яблоки Гала 1кг",120,"Сочные"),
                 (3,"Бананы 1кг",95,"Спелые"),
                 (4,"Куриное филе 1кг",320,"Фермерское"),
                 (4,"Фарш говяжий 500г",280,"Свежий"),
                 (5,"Моющее средство 1л",150,"Для посуды"),
                 (5,"Порошок 2кг",280,"Универсальный"),
                 (6,"Вода 1.5л",55,"Минеральная"),
                 (6,"Сок апельсиновый 1л",110,"Натуральный"),
                 (6,"Сок яблочный 1л",95,"Без сахара")],
            )
            await db.commit()
    finally:
        await db.close()


# ==================== Пользователи ====================


async def get_or_create_user(telegram_id, first_name=None, last_name=None):
    db = await _db()
    try:
        cur = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = await cur.fetchone()
        if user:
            user = dict(user)
            if not user.get("referral_code"):
                code = f"ref{telegram_id}"
                await db.execute("UPDATE users SET referral_code = ? WHERE id = ?", (code, user["id"]))
                await db.commit()
                user["referral_code"] = code
            return user
        code = f"ref{telegram_id}"
        await db.execute(
            "INSERT INTO users (telegram_id, first_name, last_name, referral_code) VALUES (?, ?, ?, ?)",
            (telegram_id, first_name, last_name, code),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return dict(await cur.fetchone())
    finally:
        await db.close()


async def update_user_profile(user_id, phone=None, address=None):
    db = await _db()
    try:
        if phone:
            await db.execute("UPDATE users SET phone = ? WHERE id = ?", (phone, user_id))
        if address:
            await db.execute("UPDATE users SET address = ? WHERE id = ?", (address, user_id))
        await db.commit()
    finally:
        await db.close()


async def get_user_by_telegram_id(telegram_id):
    db = await _db()
    try:
        cur = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_user_by_referral_code(code):
    db = await _db()
    try:
        cur = await db.execute("SELECT * FROM users WHERE referral_code = ?", (code,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def apply_referral(referred_id, referrer_code):
    db = await _db()
    try:
        cur = await db.execute("SELECT id FROM users WHERE referral_code = ?", (referrer_code,))
        r = await cur.fetchone()
        if not r:
            return False
        rid = r[0]
        if rid == referred_id:
            return False
        cur = await db.execute("SELECT referred_by FROM users WHERE id = ?", (referred_id,))
        row = await cur.fetchone()
        if row and row[0]:
            return False
        await db.execute("UPDATE users SET referred_by = ? WHERE id = ?", (rid, referred_id))
        await db.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, reward_amount) VALUES (?, ?, ?)",
            (rid, referred_id, REFERRAL_REWARD),
        )
        await db.execute(
            "UPDATE users SET referral_balance = referral_balance + ?, referral_count = referral_count + 1 WHERE id = ?",
            (REFERRAL_REWARD, rid),
        )
        await db.execute(
            "UPDATE users SET referral_balance = referral_balance + ? WHERE id = ?",
            (REFERRAL_REWARD, referred_id),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def use_referral_balance(user_id, amount):
    db = await _db()
    try:
        cur = await db.execute(
            "UPDATE users SET referral_balance = referral_balance - ? WHERE id = ? AND referral_balance >= ?",
            (amount, user_id, amount),
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


# ==================== Язык ====================


async def get_user_language(telegram_id):
    db = await _db()
    try:
        cur = await db.execute("SELECT language FROM users WHERE telegram_id = ?", (telegram_id,))
        r = await cur.fetchone()
        return r[0] if r and r[0] else "ru"
    finally:
        await db.close()


async def update_user_language(telegram_id, language):
    db = await _db()
    try:
        await db.execute("UPDATE users SET language = ? WHERE telegram_id = ?", (language, telegram_id))
        await db.commit()
    finally:
        await db.close()


# ==================== Категории и товары ====================


async def get_categories():
    db = await _db()
    try:
        cur = await db.execute("SELECT * FROM categories ORDER BY sort_order")
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_products_by_category(category_id):
    db = await _db()
    try:
        cur = await db.execute(
            "SELECT * FROM products WHERE category_id = ? AND is_active = 1 ORDER BY name",
            (category_id,),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_product(product_id):
    db = await _db()
    try:
        cur = await db.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def add_product(category_id, name, price, description=None, photo_file_id=None):
    db = await _db()
    try:
        cur = await db.execute(
            "INSERT INTO products (category_id, name, price, description, photo_file_id, is_active) VALUES (?, ?, ?, ?, ?, 1)",
            (category_id, name, price, description, photo_file_id),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def update_product(product_id, name=None, price=None, description=None, photo_file_id=None):
    db = await _db()
    try:
        fields, vals = [], []
        if name is not None: fields.append("name = ?"); vals.append(name)
        if price is not None: fields.append("price = ?"); vals.append(price)
        if description is not None: fields.append("description = ?"); vals.append(description)
        if photo_file_id is not None: fields.append("photo_file_id = ?"); vals.append(photo_file_id)
        if fields:
            vals.append(product_id)
            await db.execute(f"UPDATE products SET {', '.join(fields)} WHERE id = ?", vals)
            await db.commit()
    finally:
        await db.close()


async def delete_product(product_id):
    db = await _db()
    try:
        await db.execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))
        await db.commit()
    finally:
        await db.close()


async def add_category(name, emoji="📦", sort_order=0):
    db = await _db()
    try:
        cur = await db.execute(
            "INSERT INTO categories (name, emoji, sort_order) VALUES (?, ?, ?)",
            (name, emoji, sort_order),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


# ==================== Корзина ====================


async def get_cart_items(user_id):
    db = await _db()
    try:
        cur = await db.execute(
            """SELECT c.id, c.product_id, c.quantity, p.name, p.price, p.photo_file_id
               FROM cart_items c JOIN products p ON c.product_id = p.id
               WHERE c.user_id = ?""",
            (user_id,),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_cart_total(user_id):
    db = await _db()
    try:
        cur = await db.execute(
            """SELECT COALESCE(SUM(c.quantity * p.price), 0) FROM cart_items c
               JOIN products p ON c.product_id = p.id WHERE c.user_id = ?""",
            (user_id,),
        )
        r = await cur.fetchone()
        return r[0] or 0.0
    finally:
        await db.close()


async def add_to_cart(user_id, product_id, quantity=1):
    db = await _db()
    try:
        cur = await db.execute(
            "SELECT id, quantity FROM cart_items WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        )
        existing = await cur.fetchone()
        if existing:
            await db.execute(
                "UPDATE cart_items SET quantity = ? WHERE id = ?",
                (existing[1] + quantity, existing[0]),
            )
        else:
            await db.execute(
                "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, ?)",
                (user_id, product_id, quantity),
            )
        await db.commit()
        return True
    finally:
        await db.close()


async def update_cart_quantity(cart_item_id, quantity):
    db = await _db()
    try:
        if quantity <= 0:
            await db.execute("DELETE FROM cart_items WHERE id = ?", (cart_item_id,))
        else:
            await db.execute("UPDATE cart_items SET quantity = ? WHERE id = ?", (quantity, cart_item_id))
        await db.commit()
    finally:
        await db.close()


async def clear_cart(user_id):
    db = await _db()
    try:
        await db.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
        await db.commit()
    finally:
        await db.close()


# ==================== Заказы ====================


async def create_order(user_id, total_amount, delivery_time, payment_method, comment, address, phone):
    db = await _db()
    try:
        cur = await db.execute(
            """INSERT INTO orders (user_id, total_amount, delivery_time, payment_method,
               comment, address, phone, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'new')""",
            (user_id, total_amount, delivery_time, payment_method, comment, address, phone),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def add_order_items(order_id, items):
    db = await _db()
    try:
        for item in items:
            await db.execute(
                """INSERT INTO order_items (order_id, product_id, quantity, price_at_moment)
                   VALUES (?, ?, ?, ?)""",
                (order_id, item["product_id"], item["quantity"], item["price"]),
            )
            await db.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ?",
                (item["quantity"], item["product_id"]),
            )
        await db.commit()
    finally:
        await db.close()


async def get_order(order_id):
    db = await _db()
    try:
        cur = await db.execute(
            """SELECT o.*, u.telegram_id, u.first_name, u.last_name
               FROM orders o JOIN users u ON o.user_id = u.id WHERE o.id = ?""",
            (order_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_order_items(order_id):
    db = await _db()
    try:
        cur = await db.execute(
            """SELECT oi.*, p.name FROM order_items oi
               JOIN products p ON oi.product_id = p.id WHERE oi.order_id = ?""",
            (order_id,),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def update_order_status(order_id, status):
    db = await _db()
    try:
        await db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        await db.commit()
    finally:
        await db.close()


async def get_user_orders(user_id, limit=5):
    db = await _db()
    try:
        cur = await db.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_all_orders(status=None, limit=50):
    db = await _db()
    try:
        if status:
            cur = await db.execute(
                """SELECT o.*, u.telegram_id, u.first_name, u.last_name
                   FROM orders o JOIN users u ON o.user_id = u.id
                   WHERE o.status = ?
                   ORDER BY o.created_at DESC LIMIT ?""",
                (status, limit),
            )
        else:
            cur = await db.execute(
                """SELECT o.*, u.telegram_id, u.first_name, u.last_name
                   FROM orders o JOIN users u ON o.user_id = u.id
                   ORDER BY o.created_at DESC LIMIT ?""",
                (limit,),
            )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def cancel_order_user(order_id, user_id):
    db = await _db()
    try:
        cur = await db.execute("SELECT status, user_id FROM orders WHERE id = ?", (order_id,))
        row = await cur.fetchone()
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
    finally:
        await db.close()


async def reorder(order_id, user_id):
    db = await _db()
    try:
        cur = await db.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,))
        row = await cur.fetchone()
        if not row or row[0] != user_id:
            return False
        items = await get_order_items(order_id)
        for item in items:
            await add_to_cart(user_id, item["product_id"], item["quantity"])
        return True
    finally:
        await db.close()


# ==================== Поддержка ====================


async def save_support_message(user_id, user_telegram_id, user_message_id, support_chat_id, support_message_id):
    db = await _db()
    try:
        await db.execute(
            """INSERT INTO support_messages
               (user_id, user_telegram_id, user_message_id, support_chat_id, support_message_id)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, user_telegram_id, user_message_id, support_chat_id, support_message_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_support_message_by_support_id(support_message_id):
    db = await _db()
    try:
        cur = await db.execute(
            "SELECT * FROM support_messages WHERE support_message_id = ?", (support_message_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


# ==================== Статистика ====================


async def get_stats_day():
    db = await _db()
    try:
        cur = await db.execute("""
            SELECT COUNT(*), COALESCE(SUM(total_amount), 0), COALESCE(AVG(total_amount), 0)
            FROM orders WHERE date(created_at) = date('now') AND status != 'cancelled'
        """)
        row = await cur.fetchone()
        cur = await db.execute("""
            SELECT COUNT(*) FROM orders WHERE date(created_at) = date('now') AND status = 'cancelled'
        """)
        c = await cur.fetchone()
        return {"orders": row[0] or 0, "revenue": row[1] or 0, "avg_check": row[2] or 0, "cancelled": c[0] or 0}
    finally:
        await db.close()


async def get_stats_week():
    db = await _db()
    try:
        cur = await db.execute("""
            SELECT COUNT(*), COALESCE(SUM(total_amount), 0), COALESCE(AVG(total_amount), 0)
            FROM orders WHERE created_at >= date('now', '-7 days') AND status != 'cancelled'
        """)
        row = await cur.fetchone()
        cur = await db.execute("""
            SELECT COUNT(*) FROM orders WHERE created_at >= date('now', '-7 days') AND status = 'cancelled'
        """)
        c = await cur.fetchone()
        return {"orders": row[0] or 0, "revenue": row[1] or 0, "avg_check": row[2] or 0, "cancelled": c[0] or 0}
    finally:
        await db.close()


async def get_top_products(period="day", limit=3):
    db = await _db()
    try:
        if period == "day":
            df = "date(o.created_at) = date('now')"
        else:
            df = "o.created_at >= date('now', '-7 days')"
        cur = await db.execute(f"""
            SELECT p.name, SUM(oi.quantity) as qty,
                   SUM(oi.quantity * oi.price_at_moment) as revenue
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            JOIN products p ON oi.product_id = p.id
            WHERE {df} AND o.status != 'cancelled'
            GROUP BY oi.product_id ORDER BY qty DESC LIMIT ?
        """, (limit,))
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
