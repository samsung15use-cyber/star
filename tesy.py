"""
Telegram Shop Bot - Продажа Stars, Premium, TON
Пополнение через скриншоты (СБП / карта / Tinkoff)
Ручная выдача товаров админом
"""

import asyncio
import logging
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, Message
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8747412873:AAHOi8BeBMKVeC6WJi8eVN54TDcYTe9H9ms"
ADMIN_IDS = [1417003901]

# Реквизиты для оплаты
PAYMENT_DETAILS = {
    "sbp": {
        "name": "СБП",
        "details": "Номер телефона: +7 995 643 8349\nПолучатель: Александр Т\nБанк: Т-Банк",
        "instruction": "1. Откройте приложение банка\n2. Выберите перевод по номеру телефона\n3. Введите номер +7 995 643 8349\n4. Введите сумму пополнения\n5. Подтвердите перевод\n6. Сделайте скриншот подтверждения\n7. Отправьте скриншот в этот чат"
    },
    "card": {
        "name": "Банковская карта",
        "details": "Номер карты: 2200 7019 8515 1809\nПолучатель: Александр Т\nБанк: Т-Банк",
        "instruction": "1. Откройте приложение банка\n2. Выберите перевод по номеру карты\n3. Введите номер карты 2200 7019 8515 1809\n4. Введите сумму пополнения\n5. Подтвердите перевод\n6. Сделайте скриншот подтверждения\n7. Отправьте скриншот в этот чат"
    },
    "tinkoff": {
        "name": "Tinkoff",
        "details": "Для оплаты нажмите кнопку ниже",
        "link": "https://www.tinkoff.ru/rm/r_vBvYaUFKZx.CSDxKiuHrA/SAji761861",
        "instruction": "1. Нажмите кнопку Перейти к оплате\n2. Введите сумму пополнения\n3. Оплатите удобным способом\n4. После оплаты сделайте скриншот\n5. Отправьте скриншот в этот чат"
    }
}

# Товары
PRODUCTS = {
    "stars": {
        "name": "Stars",
        "items": {
            "100": {"price": 70, "description": "100 Stars"},
            "500": {"price": 300, "description": "500 Stars -10%"},
            "1000": {"price": 700, "description": "1000 Stars -20%"}
        }
    },
    "premium": {
        "name": "Premium",
        "items": {
            "1m": {"price": 250, "description": "1 месяц Premium"},
            "3m": {"price": 500, "description": "3 месяца Premium -11%"},
            "12m": {"price": 900, "description": "12 месяцев Premium -22%"}
        }
    },
    "ton": {
        "name": "TON",
        "items": {
            "1": {"price": 90, "description": "1 TON"},
            "5": {"price": 300, "description": "5 TON -4%"},
            "10": {"price": 700, "description": "10 TON -8%"}
        }
    }
}

# Предустановленные суммы для пополнения
PRESET_DEPOSITS = [100, 300, 800, 1500, 3000]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, db_name="shop.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()

    def init_db(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                balance REAL DEFAULT 0,
                total_spent REAL DEFAULT 0,
                registered_at TIMESTAMP,
                is_admin BOOLEAN DEFAULT 0
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product_type TEXT,
                product_item TEXT,
                amount REAL,
                quantity INTEGER DEFAULT 1,
                status TEXT DEFAULT 'pending',
                payment_method TEXT,
                created_at TIMESTAMP,
                completed_at TIMESTAMP,
                admin_note TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                deposit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                payment_method TEXT,
                screenshot_file_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP,
                completed_at TIMESTAMP,
                admin_note TEXT
            )
        """)
        self.conn.commit()

    def add_user(self, user_id, username=None, full_name=None):
        self.cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, username, full_name, registered_at, is_admin)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, full_name, datetime.now(), user_id in ADMIN_IDS))
        self.conn.commit()

    def get_user(self, user_id):
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()

    def update_balance(self, user_id, amount, operation="add"):
        current = self.get_user(user_id)[3] if self.get_user(user_id) else 0
        if operation == "add":
            new_balance = current + amount
        else:
            new_balance = current - amount
            self.cursor.execute("UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?", (amount, user_id))
        self.cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        self.conn.commit()
        return new_balance

    def create_order(self, user_id, product_type, product_item, amount, quantity=1, payment_method="balance"):
        self.cursor.execute("""
            INSERT INTO orders (user_id, product_type, product_item, amount, quantity, payment_method, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, product_type, product_item, amount, quantity, payment_method, datetime.now(), "pending"))
        order_id = self.cursor.lastrowid
        self.conn.commit()
        return order_id

    def create_deposit(self, user_id, amount, payment_method, screenshot_file_id):
        self.cursor.execute("""
            INSERT INTO deposits (user_id, amount, payment_method, screenshot_file_id, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, amount, payment_method, screenshot_file_id, datetime.now(), "pending"))
        deposit_id = self.cursor.lastrowid
        self.conn.commit()
        return deposit_id

    def get_pending_orders(self):
        self.cursor.execute("""
            SELECT o.*, u.username, u.full_name
            FROM orders o
            JOIN users u ON o.user_id = u.user_id
            WHERE o.status = 'pending'
            ORDER BY o.created_at DESC
        """)
        return self.cursor.fetchall()

    def get_pending_deposits(self):
        self.cursor.execute("""
            SELECT d.*, u.username, u.full_name
            FROM deposits d
            JOIN users u ON d.user_id = u.user_id
            WHERE d.status = 'pending'
            ORDER BY d.created_at DESC
        """)
        return self.cursor.fetchall()

    def get_user_orders(self, user_id):
        self.cursor.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        return self.cursor.fetchall()

    def get_user_deposits(self, user_id):
        self.cursor.execute("SELECT * FROM deposits WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        return self.cursor.fetchall()

    def update_order_status(self, order_id, status, admin_note=None):
        if admin_note:
            self.cursor.execute("""
                UPDATE orders SET status = ?, completed_at = ?, admin_note = ? WHERE order_id = ?
            """, (status, datetime.now() if status == "completed" else None, admin_note, order_id))
        else:
            self.cursor.execute("""
                UPDATE orders SET status = ?, completed_at = ? WHERE order_id = ?
            """, (status, datetime.now() if status == "completed" else None, order_id))
        self.conn.commit()

    def update_deposit_status(self, deposit_id, status, admin_note=None):
        if admin_note:
            self.cursor.execute("""
                UPDATE deposits SET status = ?, completed_at = ?, admin_note = ? WHERE deposit_id = ?
            """, (status, datetime.now() if status == "completed" else None, admin_note, deposit_id))
        else:
            self.cursor.execute("""
                UPDATE deposits SET status = ?, completed_at = ? WHERE deposit_id = ?
            """, (status, datetime.now() if status == "completed" else None, deposit_id))
        self.conn.commit()

    def get_deposit(self, deposit_id):
        self.cursor.execute("""
            SELECT d.*, u.username, u.full_name
            FROM deposits d
            JOIN users u ON d.user_id = u.user_id
            WHERE d.deposit_id = ?
        """, (deposit_id,))
        return self.cursor.fetchone()

    def get_all_users(self):
        self.cursor.execute("SELECT user_id FROM users")
        return self.cursor.fetchall()


# ========== FSM СОСТОЯНИЯ ==========
class OrderStates(StatesGroup):
    selecting_product = State()
    selecting_item = State()
    confirming_order = State()


class DepositStates(StatesGroup):
    entering_amount = State()
    selecting_payment_method = State()
    waiting_screenshot = State()


class MailingStates(StatesGroup):
    waiting_for_message = State()


class AdminBalanceStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()


# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard(is_admin=False):
    builder = InlineKeyboardBuilder()
    builder.button(text="Магазин", callback_data="shop")
    builder.button(text="Пополнить баланс", callback_data="deposit")
    builder.button(text="Мой профиль", callback_data="profile")
    builder.button(text="Мои заказы", callback_data="my_orders")
    if is_admin:
        builder.button(text="Админ-панель", callback_data="admin_panel")
    builder.adjust(2)
    return builder.as_markup()


def get_products_keyboard():
    builder = InlineKeyboardBuilder()
    for key, product in PRODUCTS.items():
        builder.button(text=product["name"], callback_data=f"product_{key}")
    builder.button(text="Назад", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()


def get_product_items_keyboard(product_key):
    builder = InlineKeyboardBuilder()
    product = PRODUCTS[product_key]
    for item_key, item in product["items"].items():
        builder.button(text=f"{item['description']} - {item['price']}₽", callback_data=f"item_{product_key}_{item_key}")
    builder.button(text="Назад", callback_data="back_to_products")
    builder.adjust(1)
    return builder.as_markup()


def get_order_confirmation_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить", callback_data="confirm_order")
    builder.button(text="Отмена", callback_data="cancel_order")
    return builder.as_markup()


def get_deposit_amount_keyboard():
    builder = InlineKeyboardBuilder()
    for amount in PRESET_DEPOSITS:
        builder.button(text=f"{amount}₽", callback_data=f"deposit_amount_{amount}")
    builder.button(text="Своя сумма", callback_data="deposit_amount_custom")
    builder.button(text="Назад", callback_data="back_to_main")
    builder.adjust(2)
    return builder.as_markup()


def get_payment_methods_keyboard():
    builder = InlineKeyboardBuilder()
    for key, method in PAYMENT_DETAILS.items():
        builder.button(text=method["name"], callback_data=f"pay_{key}")
    builder.button(text="Назад", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Заказы", callback_data="admin_orders")
    builder.button(text="Заявки на пополнение", callback_data="admin_deposits")
    builder.button(text="Изменить баланс", callback_data="admin_balance")
    builder.button(text="Статистика", callback_data="admin_stats")
    builder.button(text="Пользователи", callback_data="admin_users")
    builder.button(text="Рассылка", callback_data="admin_mailing")
    builder.button(text="В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_orders_keyboard(orders):
    builder = InlineKeyboardBuilder()
    for order in orders[:10]:
        order_id = order[0]
        user_id = order[1]
        amount = order[4]
        username = order[11] if len(order) > 11 else None
        builder.button(text=f"#{order_id} | {username or user_id} | {amount}₽", callback_data=f"admin_order_{order_id}")
    builder.button(text="Обновить", callback_data="admin_refresh_orders")
    builder.button(text="В админку", callback_data="back_to_admin")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_deposits_keyboard(deposits):
    builder = InlineKeyboardBuilder()
    for deposit in deposits[:10]:
        deposit_id = deposit[0]
        user_id = deposit[1]
        amount = deposit[2]
        payment_method = deposit[3]
        username = deposit[10] if len(deposit) > 10 else None
        builder.button(text=f"#{deposit_id} | {username or user_id} | {amount}₽ | {payment_method}", callback_data=f"admin_deposit_{deposit_id}")
    builder.button(text="Обновить", callback_data="admin_refresh_deposits")
    builder.button(text="В админку", callback_data="back_to_admin")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_deposit_actions_keyboard(deposit_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить и пополнить", callback_data=f"approve_deposit_{deposit_id}")
    builder.button(text="Отклонить", callback_data=f"reject_deposit_{deposit_id}")
    builder.button(text="К списку", callback_data="admin_deposits")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_order_actions_keyboard(order_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="Выдать товар", callback_data=f"complete_order_{order_id}")
    builder.button(text="Отклонить", callback_data=f"reject_order_{order_id}")
    builder.button(text="К списку", callback_data="admin_orders")
    builder.adjust(1)
    return builder.as_markup()


# ========== ОСНОВНОЙ БОТ ==========
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=None))
dp = Dispatcher(storage=MemoryStorage())
db = Database()


@dp.message(Command("start"))
async def cmd_start(message, state):
    user_id = message.from_user.id
    db.add_user(user_id, message.from_user.username, message.from_user.full_name)
    await state.clear()
    user = db.get_user(user_id)
    balance = user[3] if user else 0
    
    await message.answer(
        f"Привет, {message.from_user.full_name}!\n\n"
        f"У нас самые дешевые цены😎!\n\n"
        f"Покупай Звёзды,Premium по лучшей цене!\n\n"
        f"Выберите действие:",
        reply_markup=get_main_keyboard(user_id in ADMIN_IDS)
    )


@dp.message(Command("admin"))
async def admin_command(message, state):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Доступ запрещен!")
        return
    pending_orders = db.get_pending_orders()
    pending_deposits = db.get_pending_deposits()
    await message.answer(
        f"АДМИН-ПАНЕЛЬ\n\n"
        f"Ожидающих заказов: {len(pending_orders)}\n"
        f"Ожидающих пополнений: {len(pending_deposits)}\n\n"
        f"Выберите действие:",
        reply_markup=get_admin_main_keyboard()
    )
    await state.clear()


@dp.message(Command("cancel"))
async def cancel_command(message, state):
    await state.clear()
    await message.answer("Действие отменено!", reply_markup=get_main_keyboard(message.from_user.id in ADMIN_IDS))


@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback, state):
    await state.clear()
    user = db.get_user(callback.from_user.id)
    balance = user[3] if user else 0
    await callback.message.edit_text(
        f"Главное меню\n\nБаланс: {balance}₽",
        reply_markup=get_main_keyboard(callback.from_user.id in ADMIN_IDS)
    )
    await callback.answer()


@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback):
    await callback.message.edit_text(
        "Админ-панель\n\nВыберите раздел:",
        reply_markup=get_admin_main_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "shop")
async def show_shop(callback):
    await callback.message.edit_text("Выберите категорию:", reply_markup=get_products_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "back_to_products")
async def back_to_products(callback):
    await callback.message.edit_text("Выберите категорию:", reply_markup=get_products_keyboard())
    await callback.answer()


@dp.callback_query(F.data.startswith("product_"))
async def show_product_items(callback, state):
    product_key = callback.data.split("_")[1]
    await state.update_data(product_key=product_key)
    await callback.message.edit_text(
        f"{PRODUCTS[product_key]['name']}\n\nВыберите товар:",
        reply_markup=get_product_items_keyboard(product_key)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("item_"))
async def process_item_selection(callback, state):
    _, product_key, item_key = callback.data.split("_")
    product = PRODUCTS[product_key]
    item = product["items"][item_key]
    await state.update_data(product_key=product_key, item_key=item_key, amount=item["price"], description=item["description"])
    user = db.get_user(callback.from_user.id)
    balance = user[3] if user else 0
    await callback.message.edit_text(
        f"Вы выбрали: {item['description']}\n"
        f"Цена: {item['price']}₽\n\n"
        f"Ваш баланс: {balance}₽\n\n"
        f"Подтвердить заказ?",
        reply_markup=get_order_confirmation_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "confirm_order")
async def confirm_order(callback, state):
    data = await state.get_data()
    if not data:
        await callback.answer("Ошибка")
        await back_to_main(callback, state)
        return
    user_id = callback.from_user.id
    product_key = data.get("product_key")
    item_key = data.get("item_key")
    amount = data.get("amount")
    description = data.get("description")
    user = db.get_user(user_id)
    if user[3] < amount:
        await callback.message.edit_text(
            f"Недостаточно средств!\nБаланс: {user[3]}₽\nНужно: {amount}₽",
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS)
        )
        await callback.answer()
        return
    order_id = db.create_order(user_id, product_key, item_key, amount)
    db.update_balance(user_id, amount, "subtract")
    await callback.message.edit_text(
        f"Заказ #{order_id} создан!\n\n"
        f"Товар: {description}\n"
        f"Сумма: {amount}₽\n\n"
        f"Ожидает подтверждения"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"НОВЫЙ ЗАКАЗ #{order_id}!\n\nПользователь: {callback.from_user.full_name}\nТовар: {description}\nСумма: {amount}₽")
        except:
            pass
    await callback.answer()
    await state.clear()


@dp.callback_query(F.data == "cancel_order")
async def cancel_order(callback, state):
    await state.clear()
    await callback.message.edit_text("Заказ отменен.", reply_markup=get_main_keyboard(callback.from_user.id in ADMIN_IDS))
    await callback.answer()


@dp.callback_query(F.data == "deposit")
async def deposit_start(callback, state):
    await state.set_state(DepositStates.entering_amount)
    await callback.message.edit_text(
        "Пополнение баланса\n\nВыберите сумму или введите свою:",
        reply_markup=get_deposit_amount_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("deposit_amount_"))
async def deposit_preset_amount(callback, state):
    amount_str = callback.data.split("_")[2]
    if amount_str == "custom":
        await state.set_state(DepositStates.entering_amount)
        await callback.message.edit_text(
            "Введите сумму (от 100 до 100000):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="deposit")]])
        )
    else:
        amount = float(amount_str)
        await state.update_data(amount=amount)
        await state.set_state(DepositStates.selecting_payment_method)
        await callback.message.edit_text(
            f"Сумма: {amount}₽\n\nВыберите способ оплаты:",
            reply_markup=get_payment_methods_keyboard()
        )
    await callback.answer()


@dp.message(DepositStates.entering_amount)
async def deposit_amount(message, state):
    try:
        amount = float(message.text.strip())
        if amount < 100 or amount > 100000:
            await message.answer("Сумма от 100 до 100000 рублей.\nВведите сумму еще раз:")
            return
    except ValueError:
        await message.answer("Введите число.\nСумма от 100 до 100000 рублей:")
        return
    await state.update_data(amount=amount)
    await state.set_state(DepositStates.selecting_payment_method)
    await message.answer(f"Сумма: {amount}₽\n\nВыберите способ оплаты:", reply_markup=get_payment_methods_keyboard())


@dp.callback_query(F.data.startswith("pay_"), DepositStates.selecting_payment_method)
async def deposit_payment_method(callback, state):
    payment_key = callback.data.split("_")[1]
    payment_info = PAYMENT_DETAILS[payment_key]
    data = await state.get_data()
    amount = data.get("amount")
    await state.update_data(payment_method=payment_key)
    await state.set_state(DepositStates.waiting_screenshot)
    
    if payment_key == "tinkoff":
        text = f"Пополнение баланса\n\nСумма: {amount}₽\nСпособ: {payment_info['name']}\n\n{payment_info['details']}\n\nИнструкция:\n{payment_info['instruction']}\n\nПосле оплаты отправьте скриншот"
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Перейти к оплате", url=payment_info["link"])],
                [InlineKeyboardButton(text="Отмена", callback_data="back_to_main")]
            ])
        )
    else:
        text = f"Пополнение баланса\n\nСумма: {amount}₽\nСпособ: {payment_info['name']}\n\nРеквизиты для оплаты:\n{payment_info['details']}\n\nИнструкция:\n{payment_info['instruction']}\n\nПосле оплаты отправьте скриншот"
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="back_to_main")]
            ])
        )
    await callback.answer()


@dp.message(DepositStates.waiting_screenshot, F.photo)
async def deposit_screenshot(message, state):
    data = await state.get_data()
    amount = data.get("amount")
    payment_method = data.get("payment_method")
    photo = message.photo[-1]
    deposit_id = db.create_deposit(message.from_user.id, amount, payment_method, photo.file_id)
    
    await message.answer(
        f"Заявка #{deposit_id} создана!\n\nСумма: {amount}₽\n\nОжидает проверки", 
        reply_markup=get_main_keyboard(message.from_user.id in ADMIN_IDS)
    )
    
    payment_name = PAYMENT_DETAILS[payment_method]['name']
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                admin_id, 
                photo.file_id, 
                caption=f"Заявка #{deposit_id}\n\nПользователь: {message.from_user.full_name}\nСумма: {amount}₽\nСпособ: {payment_name}"
            )
        except:
            pass
    await state.clear()


@dp.message(DepositStates.waiting_screenshot)
async def deposit_wrong_input(message):
    await message.answer("Отправьте скриншот оплаты.")


@dp.callback_query(F.data == "profile")
async def show_profile(callback):
    user = db.get_user(callback.from_user.id)
    orders = db.get_user_orders(callback.from_user.id)
    deposits = db.get_user_deposits(callback.from_user.id)
    total_orders = len(orders)
    completed_orders = len([o for o in orders if o[6] == "completed"])
    total_spent = sum([o[4] for o in orders if o[6] == "completed"])
    total_deposits = sum([d[2] for d in deposits if d[6] == "completed"])
    await callback.message.edit_text(
        f"ПРОФИЛЬ\n\n"
        f"Баланс: {user[3]}₽\n"
        f"Пополнено: {total_deposits}₽\n"
        f"Потрачено: {total_spent}₽\n"
        f"Заказов: {total_orders}",
        reply_markup=get_main_keyboard(callback.from_user.id in ADMIN_IDS)
    )
    await callback.answer()


@dp.callback_query(F.data == "my_orders")
async def show_orders(callback):
    orders = db.get_user_orders(callback.from_user.id)
    if not orders:
        await callback.message.edit_text("У вас нет заказов.", reply_markup=get_main_keyboard(callback.from_user.id in ADMIN_IDS))
        await callback.answer()
        return
    text = "ВАШИ ЗАКАЗЫ:\n\n"
    for order in orders[:10]:
        order_id = order[0]
        product_type = order[2]
        product_item = order[3]
        amount = order[4]
        status = order[6]
        created_at = order[8]
        product_name = PRODUCTS[product_type]["items"][product_item]["description"]
        status_text = "Ожидает" if status == "pending" else "Выполнен" if status == "completed" else "Отклонен"
        text += f"#{order_id} - {product_name}\n"
        text += f"{amount}₽ | {created_at[:16]} | {status_text}\n\n"
    await callback.message.edit_text(text, reply_markup=get_main_keyboard(callback.from_user.id in ADMIN_IDS))
    await callback.answer()


@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен")
        return
    pending_orders = db.get_pending_orders()
    pending_deposits = db.get_pending_deposits()
    await callback.message.edit_text(
        f"АДМИН-ПАНЕЛЬ\n\n"
        f"Заказов: {len(pending_orders)}\n"
        f"Пополнений: {len(pending_deposits)}\n\n"
        f"Выберите раздел:",
        reply_markup=get_admin_main_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_orders")
async def admin_orders_list(callback):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен")
        return
    pending_orders = db.get_pending_orders()
    if not pending_orders:
        await callback.message.edit_text(
            "Нет заказов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Назад", callback_data="back_to_admin")]
            ])
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        "Выберите заказ:",
        reply_markup=get_admin_orders_keyboard(pending_orders)
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_deposits")
async def admin_deposits_list(callback):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен")
        return
    pending_deposits = db.get_pending_deposits()
    if not pending_deposits:
        await callback.message.edit_text(
            "Нет заявок на пополнение.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Назад", callback_data="back_to_admin")]
            ])
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        "Выберите заявку на пополнение:",
        reply_markup=get_admin_deposits_keyboard(pending_deposits)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_order_"))
async def admin_order_detail(callback):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен")
        return
    order_id = int(callback.data.split("_")[2])
    db.cursor.execute("SELECT o.*, u.username, u.full_name FROM orders o JOIN users u ON o.user_id = u.user_id WHERE o.order_id = ?", (order_id,))
    order = db.cursor.fetchone()
    if not order:
        await callback.answer("Не найден")
        return
    order_id = order[0]
    user_id = order[1]
    product_type = order[2]
    product_item = order[3]
    amount = order[4]
    status = order[6]
    full_name = order[12] if len(order) > 12 else None
    product_name = PRODUCTS[product_type]["items"][product_item]["description"]
    await callback.message.edit_text(
        f"ЗАКАЗ #{order_id}\n\n"
        f"Пользователь: {full_name}\n"
        f"Товар: {product_name}\n"
        f"Сумма: {amount}₽\n"
        f"Статус: {status}",
        reply_markup=get_admin_order_actions_keyboard(order_id)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_deposit_"))
async def admin_deposit_detail(callback):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен")
        return
    deposit_id = int(callback.data.split("_")[2])
    deposit = db.get_deposit(deposit_id)
    if not deposit:
        await callback.answer("Не найдена")
        return
    deposit_id = deposit[0]
    user_id = deposit[1]
    amount = deposit[2]
    payment_method = deposit[3]
    screenshot_file_id = deposit[4]
    full_name = deposit[11] if len(deposit) > 11 else None
    await callback.message.delete()
    await callback.message.answer_photo(
        screenshot_file_id,
        caption=f"ЗАЯВКА #{deposit_id}\n\nПользователь: {full_name}\nСумма: {amount}₽\nСпособ: {PAYMENT_DETAILS[payment_method]['name']}",
        reply_markup=get_admin_deposit_actions_keyboard(deposit_id)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("complete_order_"))
async def complete_order(callback):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен")
        return
    order_id = int(callback.data.split("_")[2])
    db.update_order_status(order_id, "completed", "Товар выдан")
    db.cursor.execute("SELECT o.*, u.user_id FROM orders o JOIN users u ON o.user_id = u.user_id WHERE o.order_id = ?", (order_id,))
    order = db.cursor.fetchone()
    product_name = PRODUCTS[order[2]]["items"][order[3]]["description"]
    try:
        await bot.send_message(order[1], f"ЗАКАЗ #{order_id} ВЫПОЛНЕН!\n\nТовар: {product_name}\nСумма: {order[4]}₽")
    except:
        pass
    await callback.message.edit_text(
        "Заказ выполнен!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="К списку", callback_data="admin_orders")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("approve_deposit_"))
async def approve_deposit(callback):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен")
        return
    deposit_id = int(callback.data.split("_")[2])
    deposit = db.get_deposit(deposit_id)
    if not deposit:
        await callback.answer("Не найдена")
        return
    deposit_id = deposit[0]
    user_id = deposit[1]
    amount = deposit[2]
    full_name = deposit[11] if len(deposit) > 11 else None
    db.update_balance(user_id, amount, "add")
    db.update_deposit_status(deposit_id, "completed", "Баланс пополнен")
    try:
        await bot.send_message(user_id, f"БАЛАНС ПОПОЛНЕН!\n\nСумма: {amount}₽\nНовый баланс: {db.get_user(user_id)[3]}₽")
    except:
        pass
    await callback.message.edit_caption(caption=f"ЗАЯВКА #{deposit_id} ПОДТВЕРЖДЕНА!\n\nПользователь: {full_name}\nСумма: {amount}₽")
    await callback.answer()


@dp.callback_query(F.data.startswith("reject_order_"))
async def reject_order(callback):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен")
        return
    order_id = int(callback.data.split("_")[2])
    db.cursor.execute("SELECT o.*, u.user_id FROM orders o JOIN users u ON o.user_id = u.user_id WHERE o.order_id = ?", (order_id,))
    order = db.cursor.fetchone()
    db.update_balance(order[1], order[4], "add")
    db.update_order_status(order_id, "rejected", "Отклонен")
    try:
        await bot.send_message(order[1], f"ЗАКАЗ #{order_id} ОТКЛОНЕН\n\nСредства возвращены")
    except:
        pass
    await callback.message.edit_text(
        "Заказ отклонен!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="К списку", callback_data="admin_orders")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("reject_deposit_"))
async def reject_deposit(callback):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен")
        return
    deposit_id = int(callback.data.split("_")[2])
    deposit = db.get_deposit(deposit_id)
    db.update_deposit_status(deposit_id, "rejected", "Отклонена")
    try:
        await bot.send_message(deposit[1], f"ЗАЯВКА #{deposit_id} ОТКЛОНЕНА\n\nОтправьте новую заявку")
    except:
        pass
    await callback.message.edit_caption(caption=f"ЗАЯВКА #{deposit_id} ОТКЛОНЕНА")
    await callback.answer()


@dp.callback_query(F.data == "admin_refresh_orders")
async def refresh_orders(callback):
    await admin_orders_list(callback)


@dp.callback_query(F.data == "admin_refresh_deposits")
async def refresh_deposits(callback):
    await admin_deposits_list(callback)


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен")
        return
    db.cursor.execute("SELECT COUNT(*) FROM users")
    total_users = db.cursor.fetchone()[0]
    db.cursor.execute("SELECT SUM(amount) FROM orders WHERE status = 'completed'")
    total_sales = db.cursor.fetchone()[0] or 0
    db.cursor.execute("SELECT SUM(amount) FROM deposits WHERE status = 'completed'")
    total_deposits = db.cursor.fetchone()[0] or 0
    db.cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'")
    pending_orders = db.cursor.fetchone()[0]
    db.cursor.execute("SELECT COUNT(*) FROM deposits WHERE status = 'pending'")
    pending_deposits = db.cursor.fetchone()[0]
    await callback.message.edit_text(
        f"СТАТИСТИКА\n\n"
        f"Пользователей: {total_users}\n"
        f"Выручка: {total_sales}₽\n"
        f"Пополнений: {total_deposits}₽\n"
        f"Ожидает заказов: {pending_orders}\n"
        f"Ожидает пополнений: {pending_deposits}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="back_to_admin")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_users")
async def admin_users(callback):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен")
        return
    db.cursor.execute("SELECT user_id, username, full_name, balance, total_spent, registered_at FROM users ORDER BY total_spent DESC LIMIT 20")
    users = db.cursor.fetchall()
    text = "ТОП-20 ПОКУПАТЕЛЕЙ:\n\n"
    for i, user in enumerate(users, 1):
        text += f"{i}. {user[2]} (@{user[1] or 'нет'})\n"
        text += f"Баланс: {user[3]}₽ | Потрачено: {user[4]}₽\n\n"
    await callback.message.edit_text(
        text[:4000],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="back_to_admin")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_mailing")
async def admin_mailing(callback, state):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен")
        return
    await state.set_state(MailingStates.waiting_for_message)
    await callback.message.edit_text(
        "РАССЫЛКА\n\nОтправьте сообщение для рассылки",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="back_to_admin")]
        ])
    )
    await callback.answer()


@dp.message(MailingStates.waiting_for_message)
async def send_mailing(message, state):
    if message.from_user.id not in ADMIN_IDS:
        return
    users = db.get_all_users()
    success = 0
    fail = 0
    for user in users:
        try:
            if message.text:
                await bot.send_message(user[0], message.text)
            elif message.photo:
                await bot.send_photo(user[0], message.photo[-1].file_id, caption=message.caption)
            success += 1
        except:
            fail += 1
    await message.answer(
        f"РАССЫЛКА ЗАВЕРШЕНА\n\nОтправлено: {success}\nНе доставлено: {fail}",
        reply_markup=get_admin_main_keyboard()
    )
    await state.clear()


@dp.callback_query(F.data == "admin_balance")
async def admin_balance_start(callback, state):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен")
        return
    await state.set_state(AdminBalanceStates.waiting_for_user_id)
    await callback.message.edit_text(
        "ИЗМЕНЕНИЕ БАЛАНСА\n\nВведите ID пользователя:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="back_to_admin")]
        ])
    )
    await callback.answer()


@dp.message(AdminBalanceStates.waiting_for_user_id)
async def admin_balance_get_user(message, state):
    try:
        user_id = int(message.text.strip())
        user = db.get_user(user_id)
        if not user:
            await message.answer("Пользователь не найден!")
            return
        await state.update_data(target_user_id=user_id)
        await state.set_state(AdminBalanceStates.waiting_for_amount)
        await message.answer(f"Пользователь: {user[2]}\nБаланс: {user[3]}₽\n\nВведите сумму (+100, -50, 200):")
    except ValueError:
        await message.answer("Введите числовой ID")


@dp.message(AdminBalanceStates.waiting_for_amount)
async def admin_balance_change(message, state):
    data = await state.get_data()
    user_id = data.get("target_user_id")
    try:
        amount_input = message.text.strip()
        if amount_input.startswith('+'):
            amount = float(amount_input[1:])
            db.update_balance(user_id, amount, "add")
            operation = f"добавлено {amount}₽"
        elif amount_input.startswith('-'):
            amount = float(amount_input[1:])
            db.update_balance(user_id, amount, "subtract")
            operation = f"списано {amount}₽"
        else:
            amount = float(amount_input)
            user = db.get_user(user_id)
            current = user[3]
            diff = amount - current
            if diff > 0:
                db.update_balance(user_id, diff, "add")
            elif diff < 0:
                db.update_balance(user_id, abs(diff), "subtract")
            operation = f"установлен баланс {amount}₽"
        user = db.get_user(user_id)
        try:
            await bot.send_message(user_id, f"БАЛАНС ИЗМЕНЕН\n\n{operation}\nНовый баланс: {user[3]}₽")
        except:
            pass
        await message.answer(
            f"Баланс изменен!\n\nПользователь: {user[2]}\n{operation}\nНовый баланс: {user[3]}₽",
            reply_markup=get_admin_main_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("Введите корректную сумму")


async def main():
    logger.info("Бот запускается...")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())