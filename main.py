# v 3.3 — PostgreSQL + Shop

import telebot
import random
import time
import json
import os
import threading
import requests
import psycopg2
from psycopg2.extras import Json

# ====== ОТКЛЮЧЕНИЕ ПРОКСИ ======
for env_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(env_var, None)
telebot.apihelper.proxy = {}

TOKEN = "8683812027:AAHj3BWuLj7o5NqntF7l02STco_N2jL6Vvs"
ADMIN_ID = "6933588930"

# ====== НАСТРОЙКИ БОТА ======
bot = telebot.TeleBot(
    TOKEN,
    threaded=True,
    num_threads=8,
    parse_mode=None
)

# ====== ТРЕЙД-КОМНАТЫ ======
trade_rooms = {}
pending_qty = {}
card_menus = {}
photo_cache = {}

# ====== БЛОКИРОВКА ======
data_lock = threading.Lock()
_save_scheduled = False
shop_lock = threading.Lock()

# ====== МАГАЗИН ======
shop_items = {
    "luck_2x_5m": {
        "name": "⚡ 2x удача 5 минут",
        "price": 3000,
        "duration": 300,
        "multiplier": 2,
        "type": "luck",
        "spawn_chance": 0.8,
        "stock": 0,
        "emoji": "⚡"
    },
    "luck_2x_10m": {
        "name": "⚡ 2x удача 10 минут",
        "price": 6000,
        "duration": 600,
        "multiplier": 2,
        "type": "luck",
        "spawn_chance": 0.5,
        "stock": 0,
        "emoji": "⚡"
    },
    "coins_2x_5m": {
        "name": "💰 2x коины 5 минут",
        "price": 2000,
        "duration": 300,
        "multiplier": 2,
        "type": "coins",
        "spawn_chance": 0.8,
        "stock": 0,
        "emoji": "💰"
    },
    "coins_2x_10m": {
        "name": "💰 2x коины 10 минут",
        "price": 4000,
        "duration": 600,
        "multiplier": 2,
        "type": "coins",
        "spawn_chance": 0.5,
        "stock": 0,
        "emoji": "💰"
    },
    "nextbox_5x": {
        "name": "🎁 5x следующий бокс",
        "price": 1500,
        "duration": 0,
        "multiplier": 5,
        "type": "nextbox",
        "spawn_chance": 0.3,
        "stock": 0,
        "emoji": "🎁"
    },
    "nextbox_10x": {
        "name": "🎁 10x следующий бокс",
        "price": 3500,
        "duration": 0,
        "multiplier": 10,
        "type": "nextbox",
        "spawn_chance": 0.1,
        "stock": 0,
        "emoji": "🎁"
    }
}

def restock_shop():
    """Обновляет ассортимент магазина."""
    global shop_items
    with shop_lock:
        # Выбираем 2-4 случайных товара
        available_items = list(shop_items.keys())
        random.shuffle(available_items)
        
        # Обнуляем весь сток
        for item_id in shop_items:
            shop_items[item_id]["stock"] = 0
        
        # Добавляем товары с учетом вероятности
        num_items = random.randint(2, 4)
        restocked = []
        
        for item_id in available_items:
            if len(restocked) >= num_items:
                break
            
            item = shop_items[item_id]
            if random.random() < item["spawn_chance"]:
                stock = random.randint(1, 3)
                shop_items[item_id]["stock"] = stock
                restocked.append(f"{item['name']} x{stock}")
        
        print(f"[SHOP] Рестокнуто: {', '.join(restocked) if restocked else 'пусто'}")

def shop_restock_loop():
    """Фоновый поток для рестока магазина."""
    time.sleep(10)  # Задержка при старте
    restock_shop()  # Первый рестоковый
    
    while True:
        delay = random.randint(20 * 60, 40 * 60)  # 20-40 минут
        print(f"[SHOP] Следующий рестока через {delay//60} минут")
        time.sleep(delay)
        restock_shop()

# Запускаем поток рестока
threading.Thread(target=shop_restock_loop, daemon=True).start()

# ====== POSTGRESQL ======
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"[ERROR] Не удалось подключиться к БД: {e}")
        return None

def init_db():
    if not DATABASE_URL:
        print("[INFO] DATABASE_URL не найден, используем локальный JSON")
        return
    conn = get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_data (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL DEFAULT '{}'
            )
        """)
        cur.execute("""
            INSERT INTO bot_data (key, value)
            VALUES ('users', '{}')
            ON CONFLICT (key) DO NOTHING
        """)
        conn.commit()
        print("[OK] База данных инициализирована")
    except Exception as e:
        print(f"[ERROR] Ошибка инициализации БД: {e}")
    finally:
        conn.close()

def load_data():
    if not DATABASE_URL:
        if os.path.exists("users.json"):
            try:
                with open("users.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    print(f"[OK] Загружено {len(data)} пользователей из users.json")
                    return data
            except Exception as e:
                print(f"[ERROR] Ошибка загрузки JSON: {e}")
        return {}

    conn = get_db_connection()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM bot_data WHERE key = 'users'")
        row = cur.fetchone()
        if row:
            data = row[0]
            print(f"[OK] Загружено {len(data)} пользователей из PostgreSQL")
            return data
        return {}
    except Exception as e:
        print(f"[ERROR] Ошибка загрузки из БД: {e}")
        return {}
    finally:
        conn.close()

def save_data():
    with data_lock:
        if not DATABASE_URL:
            try:
                tmp_file = "users.json.tmp"
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(users, f, indent=4, ensure_ascii=False)
                os.replace(tmp_file, "users.json")
            except IOError as e:
                print(f"[ERROR] Ошибка сохранения JSON: {e}")
            return

        conn = get_db_connection()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO bot_data (key, value)
                VALUES ('users', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (Json(users),))
            conn.commit()
        except Exception as e:
            print(f"[ERROR] Ошибка сохранения в БД: {e}")
        finally:
            conn.close()

def schedule_save():
    global _save_scheduled
    if not _save_scheduled:
        _save_scheduled = True
        def _do_save():
            global _save_scheduled
            time.sleep(3)
            save_data()
            _save_scheduled = False
        threading.Thread(target=_do_save, daemon=True).start()

# ====== ИНИЦИАЛИЗАЦИЯ ======
init_db()
users = load_data()

def fix_inventory(user):
    if isinstance(user["inventory"], list):
        new_inv = {}
        for item in user["inventory"]:
            new_inv[item] = new_inv.get(item, 0) + 1
        user["inventory"] = new_inv

def get_user(user_id, tg_user=None):
    user_id = str(user_id)
    changed = False

    if user_id not in users:
        users[user_id] = {
            "balance": 0,
            "inventory": {},
            "last_open": 0,
            "opens": 0,
            "captcha": False,
            "username": None,
            "first_name": None,
            "boosts": {
                "luck_multiplier": 1,
                "luck_expires": 0,
                "coins_multiplier": 1,
                "coins_expires": 0,
                "nextbox_multiplier": 1
            }
        }
        changed = True

    u = users[user_id]

    if tg_user is not None:
        new_username = tg_user.username or None
        new_first = tg_user.first_name or None
        if u.get("username") != new_username or u.get("first_name") != new_first:
            u["username"] = new_username
            u["first_name"] = new_first
            changed = True

    for field, default in [("username", None), ("first_name", None), ("opens", 0)]:
        if field not in u:
            u[field] = default
            changed = True

    # Добавляем бусты если нет
    if "boosts" not in u:
        u["boosts"] = {
            "luck_multiplier": 1,
            "luck_expires": 0,
            "coins_multiplier": 1,
            "coins_expires": 0,
            "nextbox_multiplier": 1
        }
        changed = True

    fix_inventory(u)

    if changed:
        schedule_save()

    return u

def get_active_boosts(user):
    """Проверяет активные бусты и очищает истекшие."""
    boosts = user.get("boosts", {})
    now = time.time()
    
    # Проверяем истечение бустов
    if boosts.get("luck_expires", 0) < now:
        boosts["luck_multiplier"] = 1
        boosts["luck_expires"] = 0
    
    if boosts.get("coins_expires", 0) < now:
        boosts["coins_multiplier"] = 1
        boosts["coins_expires"] = 0
    
    return boosts

def get_display_name(uid):
    u = users.get(str(uid), {})
    return u.get("first_name") or f"Игрок {uid}"

# ====== КАРТЫ ======
cards = [
    {"name": "ирина владимировна",    "rarity": "common",    "chance": 1/2},
    {"name": "елена олеговна",         "rarity": "common",    "chance": 1/3},
    {"name": "сергей коваленко",       "rarity": "common",    "chance": 1/4},
    {"name": "юрий николаевич",        "rarity": "common",    "chance": 1/6},
    {"name": "виталий андреевич",      "rarity": "common",    "chance": 1/8},
    {"name": "александр анатольевич",  "rarity": "rare",      "chance": 1/10},
    {"name": "анна николаевна",        "rarity": "rare",      "chance": 1/12},
    {"name": "богдашевская",           "rarity": "rare",      "chance": 1/15},
    {"name": "овсянников",             "rarity": "rare",      "chance": 1/17},
    {"name": "алена игоревна",         "rarity": "epic",      "chance": 1/20},
    {"name": "ольга виталиевна",       "rarity": "epic",      "chance": 1/24},
    {"name": "наталия валериевна",     "rarity": "epic",      "chance": 1/30},
    {"name": "оксана ивановна",        "rarity": "epic",      "chance": 1/34},
    {"name": "виктор викентиевич",     "rarity": "mythic",    "chance": 1/40},
    {"name": "вера федоровна",         "rarity": "mythic",    "chance": 1/55},
    {"name": "татьяна леонидовна",     "rarity": "mythic",    "chance": 1/75},
    {"name": "людмила",                "rarity": "legendary", "chance": 1/100},
    {"name": "мунтяну",                "rarity": "legendary", "chance": 1/150},
    {"name": "ирина григориевна",      "rarity": "legendary", "chance": 1/215},
    {"name": "наталия технолоджия",    "rarity": "exotic",    "chance": 1/350},
    {"name": "барабаш",                "rarity": "exotic",    "chance": 1/750},
    {"name": "дмитро",                 "rarity": "secret",    "chance": 1/5000},
    {"name": "брудин",                 "rarity": "secret",    "chance": 1/12500},
    {"name": "БudkО",                  "rarity": "glitch",    "chance": 1/50000},
]

CARD_GENDER = {
    "ирина владимировна":    "f",
    "елена олеговна":        "f",
    "сергей коваленко":      "m",
    "юрий николаевич":       "m",
    "виталий андреевич":     "m",
    "александр анатольевич": "m",
    "анна николаевна":       "f",
    "богдашевская":          "f",
    "овсянников":            "m",
    "алена игоревна":        "f",
    "ольга виталиевна":      "f",
    "наталия валериевна":    "f",
    "оксана ивановна":       "f",
    "виктор викентиевич":    "m",
    "вера федоровна":        "f",
    "татьяна леонидовна":    "f",
    "людмила":               "f",
    "мунтяну":               "f",
    "ирина григориевна":     "f",
    "наталия технолоджия":   "f",
    "барабаш":               "m",
    "дмитро":                "m",
    "брудин":                "m",
    "БudkО":                 "f",
}

RARITY_NAMES_GENDER = {
    "common":    {"m": "Обычный",       "f": "Обычная"},
    "rare":      {"m": "Редкий",        "f": "Редкая"},
    "epic":      {"m": "Эпический",     "f": "Эпическая"},
    "mythic":    {"m": "Мифический",    "f": "Мифическая"},
    "legendary": {"m": "Легендарный",   "f": "Легендарная"},
    "exotic":    {"m": "Экзотический",  "f": "Экзотическая"},
    "secret":    {"m": "Секретный",     "f": "Секретная"},
    "glitch":    {"m": "ГЛИТЧ",         "f": "ГЛИТЧ"},
}

RARITY_ORDER = {
    "common": 0, "rare": 1, "epic": 2, "mythic": 3,
    "legendary": 4, "exotic": 5, "secret": 6, "glitch": 7,
}

CARD_TYPE_ORDER = {"normal": 0, "gold": 1, "rainbow": 2}

RARITY_EMOJI = {
    "common":    "⚪",
    "rare":      "🔵",
    "epic":      "🟣",
    "mythic":    "🔴",
    "legendary": "🟡",
    "exotic":    "🟠",
    "secret":    "💎",
    "glitch":    "👾",
}

RARITY_NAMES = {
    "common":    "Обычная",
    "rare":      "Редкая",
    "epic":      "Эпик",
    "mythic":    "Мифик",
    "legendary": "Легендарная",
    "exotic":    "Экзотик",
    "secret":    "Секретная",
    "glitch":    "ГЛИТЧ",
}

COOLDOWN = 3

# ====== ПУЛ КАРТ ======
_card_pool = []
_pool_total = 0

def _build_card_pool():
    global _card_pool, _pool_total
    pool = []
    for card in cards:
        base_weight = card["chance"]
        base_x = int(1 / base_weight)
        base_name = f"{card['name']}-{card['rarity']}"
        pool.append({
            "name": base_name,
            "weight": base_weight,
            "min_reward": base_x,
            "max_reward": base_x * 7
        })
        pool.append({
            "name": f"{base_name}-gold",
            "weight": base_weight / 5,
            "min_reward": base_x * 2,
            "max_reward": base_x * 10
        })
        pool.append({
            "name": f"{base_name}-rainbow",
            "weight": base_weight / 10,
            "min_reward": base_x * 3,
            "max_reward": base_x * 15
        })
    _card_pool = pool
    _pool_total = sum(c["weight"] for c in pool)

_build_card_pool()

def parse_card(card_name):
    parts = card_name.split("-")
    rarity_type = parts[-1] if parts[-1] in ["gold", "rainbow"] else "normal"
    return parts[0], rarity_type

def get_card_rarity(card_key):
    parts = card_key.split("-")
    if parts[-1] in ["gold", "rainbow"]:
        return parts[-2] if len(parts) >= 3 else "common"
    return parts[-1] if len(parts) >= 2 else "common"

def get_card_type(card_key):
    parts = card_key.split("-")
    return parts[-1] if parts[-1] in ["gold", "rainbow"] else "normal"

def format_card_name(card_key, rarity_type):
    base = card_key.split("-")[0]
    gender = CARD_GENDER.get(base, "m")
    prefix = ""
    if rarity_type == "gold":
        prefix = "Золотая" if gender == "f" else "Золотой"
    elif rarity_type == "rainbow":
        prefix = "Радужная" if gender == "f" else "Радужный"
    return f"{prefix} {base}" if prefix else base.capitalize()

def get_random_card(luck_multiplier=1):
    """Генерирует карту с учетом бонуса удачи."""
    # Удача увеличивает шанс редких карт
    adjusted_pool = []
    for c in _card_pool:
        rarity = get_card_rarity(c["name"])
        boost = 1
        if luck_multiplier > 1:
            # Чем реже карта, тем сильнее буст
            rarity_boost = {
                "common": 1,
                "rare": 1.2,
                "epic": 1.5,
                "mythic": 2,
                "legendary": 3,
                "exotic": 4,
                "secret": 5,
                "glitch": 10
            }
            boost = rarity_boost.get(rarity, 1) * (luck_multiplier ** 0.5)
        
        adjusted_pool.append({
            "name": c["name"],
            "weight": c["weight"] * boost,
            "min_reward": c["min_reward"],
            "max_reward": c["max_reward"]
        })
    
    total = sum(x["weight"] for x in adjusted_pool)
    r = random.uniform(0, total)
    upto = 0.0
    for c in adjusted_pool:
        upto += c["weight"]
        if upto >= r:
            result = dict(c)
            result["reward"] = random.randint(int(c["min_reward"]), int(c["max_reward"]))
            return result
    
    c = adjusted_pool[-1]
    result = dict(c)
    result["reward"] = random.randint(int(c["min_reward"]), int(c["max_reward"]))
    return result

# ====== ИНВЕНТАРЬ ======

def sort_inventory(inventory, sort_by="rarity_desc"):
    items = list(inventory.items())
    if sort_by == "rarity_desc":
        items.sort(key=lambda x: (
            RARITY_ORDER.get(get_card_rarity(x[0]), 0),
            CARD_TYPE_ORDER.get(get_card_type(x[0]), 0)
        ), reverse=True)
    elif sort_by == "rarity_asc":
        items.sort(key=lambda x: (
            RARITY_ORDER.get(get_card_rarity(x[0]), 0),
            CARD_TYPE_ORDER.get(get_card_type(x[0]), 0)
        ))
    elif sort_by == "count_desc":
        items.sort(key=lambda x: x[1], reverse=True)
    elif sort_by == "name":
        items.sort(key=lambda x: x[0])
    return items

def inventory_text(inventory, sort_by="rarity_desc"):
    if not inventory:
        return "🎒 Инвентарь пуст"
    items = sort_inventory(inventory, sort_by)
    lines = ["🎒 <b>Твои карты:</b>\n"]
    for card, count in items:
        name, rarity_type = parse_card(card)
        display = format_card_name(card, rarity_type)
        rarity = get_card_rarity(card)
        emoji = RARITY_EMOJI.get(rarity, "⚪")
        rname = RARITY_NAMES.get(rarity, rarity)
        lines.append(f"{emoji} <b>{display}</b>  <i>{rname}</i>  ×{count}")
    return "\n".join(lines)

def inventory_keyboard(sort_by="rarity_desc"):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    sorts = [
        ("rarity_desc", "🏆 Редкость ↓"),
        ("rarity_asc",  "🏆 Редкость ↑"),
        ("count_desc",  "📊 Кол-во ↓"),
        ("name",        "🔤 По имени"),
    ]
    btns = [
        telebot.types.InlineKeyboardButton(
            f"✅ {label}" if sort_by == key else label,
            callback_data=f"invsort_{key}"
        )
        for key, label in sorts
    ]
    kb.add(*btns)
    return kb

# ====== ТАБЛИЦА ЛИДЕРОВ ======

def leaderboard_text(sort_by="balance"):
    if sort_by == "balance":
        ranked = sorted(users.items(), key=lambda x: x[1].get("balance", 0), reverse=True)
        title = "💰 Топ по шейк-коинам"
    else:
        ranked = sorted(users.items(), key=lambda x: x[1].get("opens", 0), reverse=True)
        title = "📦 Топ по открытым боксам"

    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏆 <b>{title}</b>\n"]

    for i, (uid, data) in enumerate(ranked[:10]):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = get_display_name(uid)
        value = (
            f"{data.get('balance', 0)} 💰"
            if sort_by == "balance"
            else f"{data.get('opens', 0)} 📦"
        )
        lines.append(f"{medal} {name} — {value}")

    if not ranked:
        lines.append("Пока никого нет...")
    return "\n".join(lines)

def leaderboard_keyboard(sort_by="balance"):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton(
            "✅ 💰 По коинам" if sort_by == "balance" else "💰 По коинам",
            callback_data="lb_balance"
        ),
        telebot.types.InlineKeyboardButton(
            "✅ 📦 По боксам" if sort_by == "boxes" else "📦 По боксам",
            callback_data="lb_boxes"
        )
    )
    return kb

# ====== МЕНЮ ======

def main_menu():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📦 Открыть бокс")
    markup.add("💰 Баланс", "🎒 Инвентарь")
    markup.add("🛒 Магазин", "🏠 Трейд")
    markup.add("🏆 Лидеры", "📊 Редкости")
    markup.add("📢 Канал")
    return markup

# ====== МАГАЗИН ======

@bot.message_handler(func=lambda m: m.text == "🛒 Магазин")
def show_shop(msg):
    user = get_user(msg.from_user.id, msg.from_user)
    boosts = get_active_boosts(user)
    
    lines = ["🛒 <b>МАГАЗИН БУСТОВ</b>\n"]
    
    # Активные бусты
    active = []
    now = time.time()
    
    if boosts.get("luck_multiplier", 1) > 1:
        expires = boosts.get("luck_expires", 0)
        remaining = int((expires - now) / 60)
        active.append(f"⚡ {boosts['luck_multiplier']}x удача ({remaining} мин)")
    
    if boosts.get("coins_multiplier", 1) > 1:
        expires = boosts.get("coins_expires", 0)
        remaining = int((expires - now) / 60)
        active.append(f"💰 {boosts['coins_multiplier']}x коины ({remaining} мин)")
    
    if boosts.get("nextbox_multiplier", 1) > 1:
        active.append(f"🎁 {boosts['nextbox_multiplier']}x следующий бокс")
    
    if active:
        lines.append("🔥 <b>Активные бусты:</b>")
        for a in active:
            lines.append(f"  {a}")
        lines.append("")
    
    # Товары в магазине
    with shop_lock:
        available = [(k, v) for k, v in shop_items.items() if v["stock"] > 0]
    
    if available:
        lines.append("📦 <b>В наличии:</b>\n")
        for item_id, item in available:
            lines.append(
                f"{item['emoji']} <b>{item['name']}</b>\n"
                f"  💰 {item['price']} SHK  |  В наличии: {item['stock']} шт.\n"
            )
    else:
        lines.append("❌ Магазин пуст. Ждём рестока...")
    
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    for item_id, item in available:
        kb.add(telebot.types.InlineKeyboardButton(
            f"{item['emoji']} Купить {item['name']}",
            callback_data=f"buy_{item_id}"
        ))
    
    kb.add(telebot.types.InlineKeyboardButton(
        "🔄 Обновить", callback_data="shop_refresh"
    ))
    
    bot.send_message(msg.chat.id, "\n".join(lines), reply_markup=kb, parse_mode="HTML")

@bot.callback_query_handler(func=lambda c: c.data == "shop_refresh")
def shop_refresh(call):
    user = get_user(call.from_user.id, call.from_user)
    boosts = get_active_boosts(user)
    
    lines = ["🛒 <b>МАГАЗИН БУСТОВ</b>\n"]
    
    active = []
    now = time.time()
    
    if boosts.get("luck_multiplier", 1) > 1:
        expires = boosts.get("luck_expires", 0)
        remaining = int((expires - now) / 60)
        active.append(f"⚡ {boosts['luck_multiplier']}x удача ({remaining} мин)")
    
    if boosts.get("coins_multiplier", 1) > 1:
        expires = boosts.get("coins_expires", 0)
        remaining = int((expires - now) / 60)
        active.append(f"💰 {boosts['coins_multiplier']}x коины ({remaining} мин)")
    
    if boosts.get("nextbox_multiplier", 1) > 1:
        active.append(f"🎁 {boosts['nextbox_multiplier']}x следующий бокс")
    
    if active:
        lines.append("🔥 <b>Активные бусты:</b>")
        for a in active:
            lines.append(f"  {a}")
        lines.append("")
    
    with shop_lock:
        available = [(k, v) for k, v in shop_items.items() if v["stock"] > 0]
    
    if available:
        lines.append("📦 <b>В наличии:</b>\n")
        for item_id, item in available:
            lines.append(
                f"{item['emoji']} <b>{item['name']}</b>\n"
                f"  💰 {item['price']} SHK  |  В наличии: {item['stock']} шт.\n"
            )
    else:
        lines.append("❌ Магазин пуст. Ждём рестока...")
    
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    for item_id, item in available:
        kb.add(telebot.types.InlineKeyboardButton(
            f"{item['emoji']} Купить {item['name']}",
            callback_data=f"buy_{item_id}"
        ))
    
    kb.add(telebot.types.InlineKeyboardButton(
        "🔄 Обновить", callback_data="shop_refresh"
    ))
    
    try:
        bot.edit_message_text(
            "\n".join(lines),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception:
        pass
    
    bot.answer_callback_query(call.id, "🔄 Обновлено")

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
def buy_item(call):
    item_id = call.data.split("_", 1)[1]
    uid = str(call.from_user.id)
    user = get_user(uid, call.from_user)
    
    with shop_lock:
        if item_id not in shop_items:
            bot.answer_callback_query(call.id, "❌ Товар не найден")
            return
        
        item = shop_items[item_id]
        
        if item["stock"] <= 0:
            bot.answer_callback_query(call.id, "❌ Нет в наличии")
            return
        
        if user["balance"] < item["price"]:
            bot.answer_callback_query(call.id, f"❌ Недостаточно коинов (нужно {item['price']})")
            return
        
        # Покупка
        user["balance"] -= item["price"]
        item["stock"] -= 1
        
        boosts = user["boosts"]
        boost_type = item["type"]
        
        if boost_type == "luck":
            boosts["luck_multiplier"] = item["multiplier"]
            boosts["luck_expires"] = time.time() + item["duration"]
        elif boost_type == "coins":
            boosts["coins_multiplier"] = item["multiplier"]
            boosts["coins_expires"] = time.time() + item["duration"]
        elif boost_type == "nextbox":
            boosts["nextbox_multiplier"] = item["multiplier"]
        
        schedule_save()
    
    bot.answer_callback_query(call.id, f"✅ Куплено: {item['name']}")
    shop_refresh(call)

# ====== ОБРАБОТЧИКИ ======

@bot.message_handler(commands=['start'])
def start(msg):
    get_user(msg.from_user.id, msg.from_user)
    bot.send_message(msg.chat.id, "Добро пожаловать в Тичер Боксы!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "💰 Баланс")
def balance(msg):
    user = get_user(msg.from_user.id, msg.from_user)
    boosts = get_active_boosts(user)
    
    text = f"💰 Баланс: {user['balance']}\n📦 Открыто боксов: {user.get('opens', 0)}"
    
    # Показываем активные бусты
    active = []
    now = time.time()
    
    if boosts.get("luck_multiplier", 1) > 1:
        expires = boosts.get("luck_expires", 0)
        remaining = int((expires - now) / 60)
        active.append(f"⚡ {boosts['luck_multiplier']}x удача ({remaining} мин)")
    
    if boosts.get("coins_multiplier", 1) > 1:
        expires = boosts.get("coins_expires", 0)
        remaining = int((expires - now) / 60)
        active.append(f"💰 {boosts['coins_multiplier']}x коины ({remaining} мин)")
    
    if boosts.get("nextbox_multiplier", 1) > 1:
        active.append(f"🎁 {boosts['nextbox_multiplier']}x следующий бокс")
    
    if active:
        text += "\n\n🔥 <b>Активные бусты:</b>\n" + "\n".join(active)
    
    bot.send_message(msg.chat.id, text, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "🎒 Инвентарь")
def inventory(msg):
    user = get_user(msg.from_user.id, msg.from_user)
    if not user["inventory"]:
        bot.send_message(msg.chat.id, "🎒 Инвентарь пуст")
        return
    sort_by = "rarity_desc"
    bot.send_message(
        msg.chat.id,
        inventory_text(user["inventory"], sort_by),
        reply_markup=inventory_keyboard(sort_by),
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("invsort_"))
def inv_sort_cb(call):
    sort_by = call.data.split("_", 1)[1]
    uid = str(call.from_user.id)
    user = get_user(uid, call.from_user)
    if not user["inventory"]:
        bot.answer_callback_query(call.id, "Инвентарь пуст")
        return
    text = inventory_text(user["inventory"], sort_by)
    kb = inventory_keyboard(sort_by)
    try:
        bot.edit_message_text(
            text, call.message.chat.id, call.message.message_id,
            reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        pass
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.text == "🏆 Лидеры")
def leaders(msg):
    get_user(msg.from_user.id, msg.from_user)
    sort_by = "balance"
    bot.send_message(
        msg.chat.id,
        leaderboard_text(sort_by),
        reply_markup=leaderboard_keyboard(sort_by),
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("lb_"))
def lb_switch_cb(call):
    sort_by = "balance" if call.data == "lb_balance" else "boxes"
    text = leaderboard_text(sort_by)
    kb = leaderboard_keyboard(sort_by)
    try:
        bot.edit_message_text(
            text, call.message.chat.id, call.message.message_id,
            reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        pass
    bot.answer_callback_query(call.id)

# ====== ОТКРЫТИЕ БОКСА ======

@bot.message_handler(func=lambda m: m.text == "📦 Открыть бокс")
def open_box(msg):
    user = get_user(msg.from_user.id, msg.from_user)

    if user["captcha"]:
        bot.send_message(msg.chat.id, "Напиши: Я не робот")
        return

    remaining = COOLDOWN - (time.time() - user["last_open"])
    if remaining > 0:
        bot.send_message(msg.chat.id, f"⏳ Подожди {remaining:.1f} секунды!")
        return

    user["last_open"] = time.time()
    user["opens"] = user.get("opens", 0) + 1

    if user["opens"] % random.randint(50, 100) == 0:
        user["captcha"] = True
        schedule_save()
        bot.send_message(msg.chat.id, "🤖 Напиши: Я не робот")
        return

    # Проверяем активные бусты
    boosts = get_active_boosts(user)
    luck_mult = max(boosts.get("luck_multiplier", 1), boosts.get("nextbox_multiplier", 1))
    coins_mult = boosts.get("coins_multiplier", 1)
    
    # Сбрасываем nextbox буст после использования
    if boosts.get("nextbox_multiplier", 1) > 1:
        boosts["nextbox_multiplier"] = 1

    card = get_random_card(luck_mult)
    user["inventory"][card["name"]] = user["inventory"].get(card["name"], 0) + 1
    
    # Применяем буст коинов
    reward = int(card["reward"] * coins_mult)
    user["balance"] += reward
    schedule_save()

    rarity_type = (
        "rainbow" if "-rainbow" in card["name"]
        else "gold" if "-gold" in card["name"]
        else "normal"
    )

    base_name = card["name"].split("-")[0]
    rarity = get_card_rarity(card["name"])
    gender = CARD_GENDER.get(base_name, "m")

    clean_name = format_card_name(card["name"], rarity_type)
    emoji = RARITY_EMOJI.get(rarity, "⚪")
    rname = RARITY_NAMES_GENDER.get(rarity, {}).get(gender, rarity)

    boost_text = ""
    if luck_mult > 1:
        boost_text += f"\n⚡ Буст удачи: {luck_mult}x"
    if coins_mult > 1:
        boost_text += f"\n💰 Буст коинов: {coins_mult}x"

    text = f"{emoji} <b>{clean_name}</b>\n<i>{rname}</i>{boost_text}\n\n+{reward} 💰"

    if card["name"] in photo_cache:
        try:
            bot.send_photo(
                msg.chat.id,
                photo_cache[card["name"]],
                caption=text,
                parse_mode="HTML"
            )
            return
        except Exception:
            del photo_cache[card["name"]]

    if rarity_type in ("gold", "rainbow"):
        img_paths = [
            f"cards/{base_name}-{rarity}-{rarity_type}.png",
            f"cards/{base_name}-{rarity}.png",
        ]
    else:
        img_paths = [f"cards/{base_name}-{rarity}.png"]

    for img_path in img_paths:
        if not os.path.exists(img_path):
            continue

        for attempt in range(3):
            try:
                with open(img_path, "rb") as img:
                    sent_msg = bot.send_photo(
                        msg.chat.id,
                        img,
                        caption=text,
                        parse_mode="HTML",
                        timeout=60
                    )
                
                if sent_msg.photo:
                    photo_cache[card["name"]] = sent_msg.photo[-1].file_id
                
                return
            
            except Exception as e:
                if attempt < 2:
                    time.sleep(1)
                continue

    bot.send_message(msg.chat.id, text, parse_mode="HTML")

@bot.message_handler(func=lambda m: users.get(str(m.from_user.id), {}).get("captcha") is True)
def captcha_check(msg):
    user = get_user(msg.from_user.id, msg.from_user)
    if msg.text and msg.text.lower() == "я не робот":
        user["captcha"] = False
        schedule_save()
        bot.send_message(msg.chat.id, "✅ Проверка пройдена!")
    else:
        bot.send_message(msg.chat.id, "❌ Напиши: Я не робот")

@bot.message_handler(func=lambda m: m.text == "📊 Редкости")
def show_rarities(msg):
    get_user(msg.from_user.id, msg.from_user)
    lines = ["🎴 <b>Редкости карт:</b>\n"]
    for rarity in ["common", "rare", "epic", "mythic", "legendary", "exotic", "secret", "glitch"]:
        emoji = RARITY_EMOJI[rarity]
        rname = RARITY_NAMES[rarity]
        lines.append(f"{emoji} <b>{rname}</b>")
    lines.append("\n🌕 <b>Золотая</b> — шанс в 5 раз меньше обычной")
    lines.append("🌈 <b>Радужная</b> — шанс в 10 раз меньше обычной")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "📢 Канал")
def show_channel(msg):
    get_user(msg.from_user.id, msg.from_user)
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton(
        "📢 Перейти в канал",
        url="https://t.me/+HltU54rHvwZmMjdi"
    ))
    bot.send_message(
        msg.chat.id,
        "📢 <b>Наш Telegram канал</b>\n\nПодписывайся, чтобы не пропустить новости и обновления!",
        reply_markup=kb,
        parse_mode="HTML"
    )

# Остальной код (трейд, команды /global, /give, /r, /reply) остается без изменений
# [Вставь сюда весь код торговли и админских команд из предыдущей версии]

# ====== ЗАПУСК ======
if __name__ == "__main__":
    print("Удаляем webhook...")
    bot.delete_webhook(drop_pending_updates=True)
    print("Webhook удалён. Бот запущен!")
    while True:
        try:
            bot.polling(
                none_stop=True,
                timeout=20,
                interval=0,
                long_polling_timeout=20
            )
        except requests.exceptions.RequestException as e:
            print(f"\n[!] Сетевая ошибка: {e}")
            time.sleep(15)
        except Exception as e:
            print(f"\n[!] Критическая ошибка: {e}")
            bot.delete_webhook(drop_pending_updates=True)
            time.sleep(15)
