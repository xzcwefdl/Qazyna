"""Автоматические тесты — без настоящего Telegram, чисто логика."""

import asyncio
import os
import sys
import tempfile
import unittest

TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_PATH"] = TMP_DB
os.environ["BOT_TOKEN"] = "TEST:TEST"
os.environ["ADMIN_ID"] = "12345"

sys.path.insert(0, os.path.dirname(__file__))

import config
config.DATABASE_PATH = TMP_DB
config.ADMIN_ID = 12345

import database
import locales
import keyboards
import states


class TestLocalization(unittest.TestCase):
    def test_all_languages_have_same_keys(self):
        ru = set(locales.TRANSLATIONS["ru"].keys())
        for lang in ("kk", "en"):
            keys = set(locales.TRANSLATIONS[lang].keys())
            self.assertEqual(ru, keys, f"{lang} missing: {ru - keys}, extra: {keys - ru}")

    def test_translate_function(self):
        self.assertIn("Добро пожаловать", locales.t("ru", "welcome"))
        self.assertIn("QazynaDelivery", locales.t("kk", "welcome"))
        self.assertIn("Welcome", locales.t("en", "welcome"))

    def test_format_kwargs(self):
        text = locales.t("ru", "product_detail", emoji="", name="Молоко", price=89)
        self.assertIn("Молоко", text)
        self.assertIn("89", text)

    def test_fallback_to_russian(self):
        text = locales.t("xx", "welcome")
        self.assertIn("Добро пожаловать", text)

    def test_unknown_key_returns_key(self):
        self.assertEqual(locales.t("ru", "nonexistent_key"), "nonexistent_key")


class TestValidation(unittest.TestCase):
    def test_phone(self):
        self.assertTrue(database.validate_phone("+7 707 123 45 67"))
        self.assertTrue(database.validate_phone("87071234567"))
        self.assertTrue(database.validate_phone("7071234567"))
        self.assertFalse(database.validate_phone("123"))
        self.assertFalse(database.validate_phone("abc"))

    def test_price(self):
        self.assertEqual(database.validate_price("89"), 89.0)
        self.assertEqual(database.validate_price("89.5"), 89.5)
        self.assertEqual(database.validate_price("89,5"), 89.5)
        self.assertEqual(database.validate_price("1000"), 1000.0)
        self.assertIsNone(database.validate_price("0"))
        self.assertIsNone(database.validate_price("-10"))
        self.assertIsNone(database.validate_price("abc"))
        self.assertIsNone(database.validate_price(""))

    def test_address(self):
        self.assertTrue(database.validate_address("ул. Абая 1"))
        self.assertTrue(database.validate_address("12345"))
        self.assertFalse(database.validate_address("аб"))
        self.assertFalse(database.validate_address(""))


class TestDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if os.path.exists(TMP_DB):
            os.remove(TMP_DB)
        await database.init_db()

    async def test_seed_data(self):
        cats = await database.get_categories()
        self.assertEqual(len(cats), 6)
        products = await database.get_products_by_category(1)
        self.assertGreater(len(products), 0)

    async def test_user_crud(self):
        user = await database.get_or_create_user(telegram_id=999, first_name="Test", last_name="User")
        self.assertEqual(user["telegram_id"], 999)
        self.assertIn("ref999", user["referral_code"])
        user2 = await database.get_or_create_user(telegram_id=999)
        self.assertEqual(user2["id"], user["id"])

    async def test_user_profile_update(self):
        user = await database.get_or_create_user(telegram_id=1000)
        await database.update_user_profile(user["id"], phone="+77001234567", address="ул. Тест 1")
        updated = await database.get_user_by_telegram_id(1000)
        self.assertEqual(updated["phone"], "+77001234567")
        self.assertEqual(updated["address"], "ул. Тест 1")

    async def test_cart(self):
        user = await database.get_or_create_user(telegram_id=2000)
        cats = await database.get_categories()
        products = await database.get_products_by_category(cats[0]["id"])
        pid = products[0]["id"]

        ok = await database.add_to_cart(user["id"], pid, 2)
        self.assertTrue(ok)
        items = await database.get_cart_items(user["id"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["quantity"], 2)

        total = await database.get_cart_total(user["id"])
        expected = products[0]["price"] * 2
        self.assertAlmostEqual(total, expected)

        await database.clear_cart(user["id"])
        self.assertEqual(len(await database.get_cart_items(user["id"])), 0)

    async def test_order_flow(self):
        user = await database.get_or_create_user(telegram_id=3000)
        cats = await database.get_categories()
        products = await database.get_products_by_category(cats[0]["id"])
        pid = products[0]["id"]
        await database.add_to_cart(user["id"], pid, 3)
        cart = await database.get_cart_items(user["id"])

        order_id = await database.create_order(
            user_id=user["id"], total_amount=cart[0]["price"] * 3,
            delivery_time="12:00–14:00", payment_method="kaspi",
            comment="", address="ул. Тест 5", phone="+77001234567",
        )
        self.assertIsInstance(order_id, int)

        await database.add_order_items(order_id, [
            {"product_id": cart[0]["product_id"], "quantity": 3, "price": cart[0]["price"]},
        ])

        order = await database.get_order(order_id)
        self.assertEqual(order["status"], "new")
        self.assertEqual(order["total_amount"], cart[0]["price"] * 3)

        items = await database.get_order_items(order_id)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["quantity"], 3)

    async def test_order_status_flow(self):
        user = await database.get_or_create_user(telegram_id=4000)
        oid = await database.create_order(
            user_id=user["id"], total_amount=1000,
            delivery_time="12:00–14:00", payment_method="kaspi",
            comment="", address="X", phone="+7",
        )
        await database.update_order_status(oid, "processing")
        order = await database.get_order(oid)
        self.assertEqual(order["status"], "processing")
        await database.update_order_status(oid, "sent")
        order = await database.get_order(oid)
        self.assertEqual(order["status"], "sent")

    async def test_admin_product_flow(self):
        cats = await database.get_categories()
        products = await database.get_products_by_category(cats[0]["id"])
        new_id = await database.add_product(
            category_id=cats[0]["id"], name="Тестовый товар",
            price=999, description="Описание",
        )
        self.assertIsInstance(new_id, int)
        prod = await database.get_product(new_id)
        self.assertEqual(prod["name"], "Тестовый товар")

        await database.update_product(new_id, name="Новое имя", price=1500)
        prod = await database.get_product(new_id)
        self.assertEqual(prod["name"], "Новое имя")
        self.assertEqual(prod["price"], 1500)

        await database.delete_product(new_id)
        prod = await database.get_product(new_id)
        self.assertEqual(prod["is_active"], 0)

    async def test_admin_category_flow(self):
        cat_id = await database.add_category("Тестовая категория", "🧪", sort_order=99)
        cats = await database.get_categories()
        self.assertTrue(any(c["id"] == cat_id for c in cats))

    async def test_referral(self):
        u1 = await database.get_or_create_user(telegram_id=5001)
        u2 = await database.get_or_create_user(telegram_id=5002)
        ok = await database.apply_referral(u2["id"], u1["referral_code"])
        self.assertTrue(ok)
        u1_after = await database.get_user_by_telegram_id(5001)
        u2_after = await database.get_user_by_telegram_id(5002)
        self.assertEqual(u1_after["referral_count"], 1)
        self.assertEqual(u1_after["referral_balance"], config.REFERRAL_REWARD)
        self.assertEqual(u2_after["referral_balance"], config.REFERRAL_REWARD)

    async def test_stats(self):
        day_stats = await database.get_stats_day()
        self.assertIn("orders", day_stats)
        self.assertIn("revenue", day_stats)
        week_stats = await database.get_stats_week()
        self.assertIn("orders", week_stats)
        self.assertIn("revenue", week_stats)


class TestStates(unittest.TestCase):
    """Главный тест — проверяем что нет коллизий стейтов (фикс исходного бага)."""

    def test_admin_states_are_separate(self):
        # В aiogram 3 стейты — это атрибуты класса StatesGroup.
        # Главное: waiting_name в AddProduct и в EditProduct — это РАЗНЫЕ State объекты.
        self.assertIsNot(
            states.AdminAddProductState.waiting_name,
            states.AdminEditProductState.waiting_name,
            "waiting_name должен быть разным State в Add и Edit (фикс коллизии)",
        )
        self.assertIsNot(
            states.AdminAddProductState.waiting_price,
            states.AdminEditProductState.waiting_price,
        )
        self.assertIsNot(
            states.AdminAddProductState.waiting_description,
            states.AdminEditProductState.waiting_description,
        )
        self.assertIsNot(
            states.AdminAddProductState.waiting_image,
            states.AdminEditProductState.waiting_image,
        )
        self.assertTrue(hasattr(states.AdminAddProductState, "waiting_category"))
        self.assertIsNot(
            states.AdminAddProductState.waiting_name,
            states.AdminAddCategoryState.waiting_name,
        )

    def test_admin_states_count(self):
        add_attrs = [x for x in dir(states.AdminAddProductState) if not x.startswith("_") and x != "get_root"]
        self.assertEqual(len(add_attrs), 6, f"ожидали 6 стейтов в AddProduct, получили {add_attrs}")
        edit_attrs = [x for x in dir(states.AdminEditProductState) if not x.startswith("_") and x != "get_root"]
        self.assertEqual(len(edit_attrs), 4, f"ожидали 4 стейта в EditProduct, получили {edit_attrs}")
        cat_attrs = [x for x in dir(states.AdminAddCategoryState) if not x.startswith("_") and x != "get_root"]
        self.assertEqual(len(cat_attrs), 1, f"ожидали 1 стейт в AddCategory, получили {cat_attrs}")


class TestKeyboards(unittest.IsolatedAsyncioTestCase):
    async def test_main_menu_builds(self):
        for lang in ("ru", "kk", "en"):
            kb = keyboards.main_menu_keyboard(lang)
            self.assertIsNotNone(kb)

    async def test_categories_keyboard(self):
        cats = await database.get_categories()
        for lang in ("ru", "kk", "en"):
            kb = keyboards.categories_keyboard(cats, lang)
            self.assertIsNotNone(kb)

    async def test_products_keyboard(self):
        cats = await database.get_categories()
        products = await database.get_products_by_category(cats[0]["id"])
        kb = keyboards.products_keyboard(products, cats[0]["id"], "ru")
        self.assertIsNotNone(kb)

    async def test_admin_keyboards(self):
        self.assertIsNotNone(keyboards.admin_main_keyboard())
        self.assertIsNotNone(keyboards.admin_products_keyboard())
        self.assertIsNotNone(keyboards.admin_confirm_product_keyboard())
        self.assertIsNotNone(keyboards.admin_skip_photo_keyboard())
        self.assertIsNotNone(keyboards.admin_cancel_kb())
        self.assertIsNotNone(keyboards.admin_skip_desc_kb())


if __name__ == "__main__":
    if os.path.exists(TMP_DB):
        os.remove(TMP_DB)
    unittest.main(verbosity=2, exit=False)
