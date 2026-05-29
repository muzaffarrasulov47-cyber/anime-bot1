import asyncio
import os
import aiosqlite

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

TOKEN = "8242189843:AAGnSO5m2zJVHft_kmsAv3YGYrx3Miu-roo"
ADMIN_ID = 8419078274
DB_PATH = "/home/claude/anime_bot/anime.db"
PAGE_SIZE = 10

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ── FSM ──────────────────────────────────────────
class AddAnime(StatesGroup):
    title = State()
    description = State()
    cover = State()

class AddEpisode(StatesGroup):
    choose_anime = State()   # admin anime tanlaydi
    video = State()          # videolarni ketma-ket yuklaydi

class AddChannel(StatesGroup):
    channel_input = State()  # kanal ID/username yoki forward

# ── DB init ──────────────────────────────────────
async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS animes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                cover_file_id TEXT,
                total_episodes INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                anime_id INTEGER REFERENCES animes(id) ON DELETE CASCADE,
                episode_number INTEGER NOT NULL,
                video_file_id TEXT NOT NULL,
                UNIQUE(anime_id, episode_number)
            );
            CREATE TABLE IF NOT EXISTS favorites (
                user_id INTEGER,
                anime_id INTEGER REFERENCES animes(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, anime_id)
            );
            CREATE TABLE IF NOT EXISTS watch_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                anime_id INTEGER,
                episode_id INTEGER,
                watched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS required_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL UNIQUE,
                channel_title TEXT,
                invite_link TEXT
            );
        """)
        await db.commit()

def is_admin(uid): return uid == ADMIN_ID

# ── Obuna tekshirish ─────────────────────────────
async def check_subscriptions(user_id: int) -> list:
    """Foydalanuvchi obuna bo'lmagan kanallar ro'yxatini qaytaradi"""
    not_subscribed = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM required_channels") as cur:
            channels = await cur.fetchall()

    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch["channel_id"], user_id=user_id)
            if member.status in ("left", "kicked", "banned"):
                not_subscribed.append(ch)
        except Exception:
            not_subscribed.append(ch)
    return not_subscribed

async def send_subscribe_message(event, not_subscribed: list):
    """Obuna bo'lmagan kanallar tugmalarini yuboradi"""
    builder = InlineKeyboardBuilder()
    for ch in not_subscribed:
        title = ch["channel_title"] or ch["channel_id"]
        link = ch["invite_link"] or f"https://t.me/{ch['channel_id'].lstrip('@')}"
        builder.button(text=f"📢 {title}", url=link)
    builder.button(text="✅ Obuna bo'ldim", callback_data="check_sub")
    builder.adjust(1)

    text = (
        "⚠️ *Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:*\n\n"
        + "\n".join(f"• {ch['channel_title'] or ch['channel_id']}" for ch in not_subscribed)
        + "\n\nObuna bo'lgach ✅ *Obuna bo'ldim* tugmasini bosing."
    )
    if isinstance(event, Message):
        await event.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await event.message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call: CallbackQuery):
    not_sub = await check_subscriptions(call.from_user.id)
    if not_sub:
        await call.answer("❌ Hali ham obuna bo'lmadingiz!", show_alert=True)
        await send_subscribe_message(call, not_sub)
    else:
        await call.answer("✅ Rahmat! Endi botdan foydalanishingiz mumkin.", show_alert=True)
        try:
            await call.message.delete()
        except:
            pass
        await show_main_menu(call.message, call.from_user.id)

# ── /start ───────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (id, username) VALUES (?,?)",
            (message.from_user.id, message.from_user.username or "")
        )
        await db.commit()

    not_sub = await check_subscriptions(message.from_user.id)
    if not_sub and not is_admin(message.from_user.id):
        await send_subscribe_message(message, not_sub)
        return

    await show_main_menu(message, message.from_user.id)

async def show_main_menu(message: Message, user_id: int):
    text = (
        "🎌 *Anime Bot ga xush kelibsiz!*\n\n"
        "📋 /list — Barcha animalar\n"
        "🔍 /search <nom> — Qidirish\n"
        "❤️ /favorites — Sevimlilarim\n"
        "🕐 /history — Tarixim\n"
    )
    if is_admin(user_id):
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ Anime qo'shish", callback_data="admin_addanime")
        builder.button(text="📤 Qism yuklash", callback_data="admin_addepisode")
        builder.button(text="📢 Majburiy obuna", callback_data="admin_channels")
        builder.button(text="🗑 Anime o'chirish", callback_data="admin_delanime")
        builder.button(text="📊 Statistika", callback_data="admin_stats")
        builder.adjust(2, 1, 2)
        text += "\n\n⚙️ *Admin paneli quyida:*"
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message.answer(text, parse_mode="Markdown")

# ── Admin panel callback ─────────────────────────
@dp.callback_query(F.data == "admin_addanime")
async def cb_admin_addanime(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await state.set_state(AddAnime.title)
    await call.message.answer("➕ *Yangi anime qo'shish*\n\nAnime nomini kiriting:", parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "admin_addepisode")
async def cb_admin_addepisode(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await show_anime_list_for_admin(call.message, state)
    await call.answer()

@dp.callback_query(F.data == "admin_channels")
async def cb_admin_channels(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await show_channels_panel(call.message)
    await call.answer()

@dp.callback_query(F.data == "admin_delanime")
async def cb_admin_delanime(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, title FROM animes ORDER BY title") as cur:
            animes = await cur.fetchall()
    if not animes:
        await call.message.answer("😔 Hozircha anime yo'q")
        await call.answer(); return
    builder = InlineKeyboardBuilder()
    for a in animes:
        builder.button(text=f"🗑 {a['title']}", callback_data=f"confirm_del:{a['id']}")
    builder.adjust(1)
    await call.message.answer("🗑 *Qaysi animeni o'chirmoqchisiz?*",
                              reply_markup=builder.as_markup(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data.startswith("confirm_del:"))
async def cb_confirm_del(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    aid = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT title FROM animes WHERE id=?", (aid,)) as cur:
            anime = await cur.fetchone()
        if not anime:
            await call.answer("Topilmadi!", show_alert=True); return
        await db.execute("DELETE FROM animes WHERE id=?", (aid,))
        await db.commit()
    await call.message.edit_text(f"✅ *{anime['title']}* o'chirildi!", parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c: users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM animes") as c: animes = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM episodes") as c: eps = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM watch_history") as c: views = (await c.fetchone())[0]
    await call.message.answer(
        f"📊 *Statistika:*\n\n"
        f"👥 Foydalanuvchilar: *{users}*\n"
        f"🎬 Animalar: *{animes}*\n"
        f"▶️ Epizodlar: *{eps}*\n"
        f"👁 Ko'rishlar: *{views}*",
        parse_mode="Markdown"
    )
    await call.answer()

# ── Anime qo'shish (soddalashtirilgan: nom, tavsif, rasm) ──
@dp.message(Command("addanime"))
async def adm_addanime(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(AddAnime.title)
    await message.answer("➕ *Yangi anime qo'shish*\n\nAnime nomini kiriting:", parse_mode="Markdown")

@dp.message(AddAnime.title)
async def adm_an_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddAnime.description)
    await message.answer("📝 Anime tavsifini kiriting (yoki /skip):")

@dp.message(AddAnime.description)
async def adm_an_desc(message: Message, state: FSMContext):
    desc = "" if message.text == "/skip" else message.text.strip()
    await state.update_data(description=desc)
    await state.set_state(AddAnime.cover)
    await message.answer("🖼 Anime uchun rasm yuboring (yoki /skip):")

@dp.message(AddAnime.cover)
async def adm_an_cover(message: Message, state: FSMContext):
    cover_id = None
    if message.photo:
        cover_id = message.photo[-1].file_id
    elif message.text != "/skip":
        await message.answer("🖼 Rasm yuboring yoki /skip ni yozing!"); return

    d = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO animes (title, description, cover_file_id) VALUES (?,?,?)",
            (d["title"], d["description"], cover_id)
        )
        anime_id = cur.lastrowid
        await db.commit()

    await state.clear()
    await message.answer(
        f"✅ *{d['title']}* muvaffaqiyatli qo'shildi!\n🆔 ID: `{anime_id}`\n\n"
        f"Endi qism yuklash uchun admin paneldan 📤 *Qism yuklash* tugmasini bosing.",
        parse_mode="Markdown"
    )

# ── Qism yuklash — anime ro'yxati ────────────────
async def show_anime_list_for_admin(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, title, total_episodes FROM animes ORDER BY title"
        ) as cur:
            animes = await cur.fetchall()

    if not animes:
        await message.answer(
            "😔 Hozircha anime yo'q.\n\nAvval anime qo'shing: admin paneldan ➕ *Anime qo'shish*",
            parse_mode="Markdown"
        )
        return

    builder = InlineKeyboardBuilder()
    for a in animes:
        builder.button(
            text=f"🎬 {a['title']} [{a['total_episodes']} qism]",
            callback_data=f"adm_ep_anime:{a['id']}"
        )
    builder.adjust(1)
    await state.set_state(AddEpisode.choose_anime)
    await message.answer(
        "📤 *Qism yuklash*\n\nQaysi animega qism qo'shmoqchisiz?",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

@dp.message(Command("addepisode"))
async def adm_addep_cmd(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await show_anime_list_for_admin(message, state)

@dp.callback_query(F.data.startswith("adm_ep_anime:"))
async def cb_adm_ep_anime(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    anime_id = int(call.data.split(":")[1])

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM animes WHERE id=?", (anime_id,)) as cur:
            anime = await cur.fetchone()
        async with db.execute(
            "SELECT MAX(episode_number) as last FROM episodes WHERE anime_id=?", (anime_id,)
        ) as cur:
            row = await cur.fetchone()
        last_ep = row["last"] or 0
        next_ep = last_ep + 1

    await state.update_data(anime_id=anime_id, anime_title=anime["title"], next_ep=next_ep)
    await state.set_state(AddEpisode.video)

    await call.message.edit_text(
        f"🎬 *{anime['title']}*\n\n"
        f"✅ Hozirga *{last_ep}* ta qism yuklangan.\n\n"
        f"▶️ Endi *{next_ep}-qism* videosini yuboring.\n"
        f"_(Videolarni ketma-ket yuboring, har biri avtomatik raqamlashadi)_\n\n"
        f"To'xtatish uchun: /done",
        parse_mode="Markdown"
    )
    await call.answer()

@dp.message(AddEpisode.video, F.video)
async def adm_ep_video(message: Message, state: FSMContext):
    d = await state.get_data()
    anime_id = d["anime_id"]
    anime_title = d["anime_title"]
    next_ep = d["next_ep"]
    fid = message.video.file_id

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO episodes (anime_id, episode_number, video_file_id)
            VALUES (?,?,?)
            ON CONFLICT(anime_id, episode_number)
            DO UPDATE SET video_file_id=excluded.video_file_id
        """, (anime_id, next_ep, fid))
        await db.execute(
            "UPDATE animes SET total_episodes = (SELECT COUNT(*) FROM episodes WHERE anime_id=?) WHERE id=?",
            (anime_id, anime_id)
        )
        await db.commit()

    new_next = next_ep + 1
    await state.update_data(next_ep=new_next)

    await message.answer(
        f"✅ *{anime_title}* — *{next_ep}-qism* saqlandi!\n\n"
        f"▶️ Endi *{new_next}-qism* videosini yuboring.\n"
        f"To'xtatish uchun: /done",
        parse_mode="Markdown"
    )

@dp.message(AddEpisode.video)
async def adm_ep_wrong(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/done"):
        d = await state.get_data()
        last = d.get("next_ep", 1) - 1
        await state.clear()
        await message.answer(
            f"✅ *{d.get('anime_title', 'Anime')}* uchun jami *{last}* qism yuklandi!",
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Video yuboring yoki /done ni yozing!")

@dp.message(Command("done"))
async def cmd_done(message: Message, state: FSMContext):
    current = await state.get_state()
    if current == AddEpisode.video:
        d = await state.get_data()
        last = d.get("next_ep", 1) - 1
        await state.clear()
        await message.answer(
            f"✅ *{d.get('anime_title', 'Anime')}* uchun jami *{last}* qism yuklandi!",
            parse_mode="Markdown"
        )
    else:
        await message.answer("Hozir yuklash jarayoni yo'q.")

# ── Majburiy obuna boshqaruvi ────────────────────
async def show_channels_panel(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM required_channels") as cur:
            channels = await cur.fetchall()

    builder = InlineKeyboardBuilder()
    text = "📢 *Majburiy obuna kanallari:*\n\n"

    if channels:
        for ch in channels:
            text += f"• {ch['channel_title'] or ch['channel_id']} (`{ch['channel_id']}`)\n"
            builder.button(
                text=f"🗑 {ch['channel_title'] or ch['channel_id']}ni o'chirish",
                callback_data=f"del_channel:{ch['id']}"
            )
        builder.adjust(1)
    else:
        text += "_(Hozircha kanal yo'q)_\n"

    builder.button(text="➕ Kanal qo'shish", callback_data="add_channel")
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "add_channel")
async def cb_add_channel(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await state.set_state(AddChannel.channel_input)
    await call.message.answer(
        "📢 *Kanal qo'shish*\n\n"
        "Quyidagilardan birini yuboring:\n"
        "1️⃣ Kanal username: `@kanalnom`\n"
        "2️⃣ Kanal ID: `-1001234567890`\n"
        "3️⃣ Kanaldan istalgan xabarni *forward* qiling\n\n"
        "⚠️ Bot kanalga admin bo'lishi kerak!",
        parse_mode="Markdown"
    )
    await call.answer()

@dp.message(AddChannel.channel_input)
async def adm_channel_input(message: Message, state: FSMContext):
    channel_id = None
    channel_title = None
    invite_link = None

    # Forward qilingan xabar
    if message.forward_from_chat:
        chat = message.forward_from_chat
        channel_id = str(chat.id)
        channel_title = chat.title
        try:
            invite = await bot.create_chat_invite_link(chat.id)
            invite_link = invite.invite_link
        except:
            invite_link = f"https://t.me/{chat.username}" if chat.username else None

    # Username yoki ID
    elif message.text:
        raw = message.text.strip()
        try:
            chat = await bot.get_chat(raw)
            channel_id = str(chat.id)
            channel_title = chat.title
            try:
                invite = await bot.create_chat_invite_link(chat.id)
                invite_link = invite.invite_link
            except:
                invite_link = f"https://t.me/{chat.username}" if chat.username else None
        except Exception as e:
            await message.answer(
                f"❌ Kanal topilmadi: `{raw}`\n\n"
                f"Bot kanalga admin qilinganmi?\nXato: {e}",
                parse_mode="Markdown"
            )
            return
    else:
        await message.answer("❌ Kanal username, ID yoki forward xabar yuboring!")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO required_channels (channel_id, channel_title, invite_link) VALUES (?,?,?)",
                (channel_id, channel_title, invite_link)
            )
            await db.commit()
        except Exception:
            await message.answer("⚠️ Bu kanal allaqachon qo'shilgan!")
            await state.clear()
            return

    await state.clear()
    await message.answer(
        f"✅ *{channel_title or channel_id}* kanali qo'shildi!\n\n"
        f"ID: `{channel_id}`\n"
        f"Havola: {invite_link or 'mavjud emas'}",
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("del_channel:"))
async def cb_del_channel(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    ch_id = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM required_channels WHERE id=?", (ch_id,)) as cur:
            ch = await cur.fetchone()
        if not ch:
            await call.answer("Topilmadi!", show_alert=True); return
        await db.execute("DELETE FROM required_channels WHERE id=?", (ch_id,))
        await db.commit()
    await call.answer(f"✅ {ch['channel_title'] or ch['channel_id']} o'chirildi", show_alert=True)
    await show_channels_panel(call.message)

# ── /list ────────────────────────────────────────
@dp.message(Command("list"))
async def cmd_list(message: Message):
    not_sub = await check_subscriptions(message.from_user.id)
    if not_sub and not is_admin(message.from_user.id):
        await send_subscribe_message(message, not_sub); return
    await show_list(message, 0)

async def show_list(event, page):
    offset = page * PAGE_SIZE
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, title, total_episodes FROM animes ORDER BY title LIMIT ? OFFSET ?",
            (PAGE_SIZE, offset)
        ) as cur:
            animes = await cur.fetchall()
        async with db.execute("SELECT COUNT(*) FROM animes") as cur:
            total = (await cur.fetchone())[0]

    if not animes:
        txt = "😔 Hozircha anime yo'q"
        if isinstance(event, Message):
            await event.answer(txt)
        else:
            await event.message.edit_text(txt)
        return

    builder = InlineKeyboardBuilder()
    for a in animes:
        builder.button(
            text=f"🎬 {a['title']}  [{a['total_episodes']} qism]",
            callback_data=f"anime:{a['id']}:{page}"
        )
    builder.adjust(1)

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    nav = []
    if page > 0:
        nav.append(("⬅️ Oldingi", f"page:{page-1}"))
    if offset + PAGE_SIZE < total:
        nav.append(("Keyingi ➡️", f"page:{page+1}"))
    for t, d in nav:
        builder.button(text=t, callback_data=d)
    if nav:
        builder.adjust(1, len(nav))

    header = f"📋 *Animalar* ({page+1}/{total_pages} sahifa • jami {total} ta)\n"
    if isinstance(event, Message):
        await event.answer(header, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await event.message.edit_text(header, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("page:"))
async def cb_page(call: CallbackQuery):
    not_sub = await check_subscriptions(call.from_user.id)
    if not_sub and not is_admin(call.from_user.id):
        await send_subscribe_message(call, not_sub)
        await call.answer(); return
    page = int(call.data.split(":")[1])
    await show_list(call, page)
    await call.answer()

# ── Anime detail ─────────────────────────────────
@dp.callback_query(F.data.startswith("anime:"))
async def cb_anime(call: CallbackQuery):
    not_sub = await check_subscriptions(call.from_user.id)
    if not_sub and not is_admin(call.from_user.id):
        await send_subscribe_message(call, not_sub)
        await call.answer(); return

    parts = call.data.split(":")
    anime_id, back_page = int(parts[1]), int(parts[2])

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM animes WHERE id=?", (anime_id,)) as cur:
            anime = await cur.fetchone()
        async with db.execute(
            "SELECT id, episode_number FROM episodes WHERE anime_id=? ORDER BY episode_number",
            (anime_id,)
        ) as cur:
            episodes = await cur.fetchall()
        async with db.execute(
            "SELECT 1 FROM favorites WHERE user_id=? AND anime_id=?",
            (call.from_user.id, anime_id)
        ) as cur:
            is_fav = await cur.fetchone()

    if not anime:
        await call.answer("Topilmadi!", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    # Barcha qismlar tugmalari
    for ep in episodes:
        builder.button(
            text=f"▶️ {ep['episode_number']}-qism",
            callback_data=f"ep:{ep['id']}:{anime_id}:{back_page}"
        )
    builder.adjust(3)

    fav_txt = "💔 Sevimlilardan olib tashlash" if is_fav else "❤️ Sevimliga qo'shish"
    builder.button(text=fav_txt, callback_data=f"fav:{anime_id}:{back_page}")
    builder.button(text="🔙 Ro'yxatga qaytish", callback_data=f"page:{back_page}")
    builder.adjust(3, 1, 1)

    desc = (anime["description"] or "Tavsif yo'q")[:400]
    ep_count = len(episodes)
    text = (
        f"🎬 *{anime['title']}*\n\n"
        f"📺 Yuklangan qismlar: *{ep_count}* ta\n\n"
        f"📝 *Tavsif:*\n{desc}"
    )

    if anime["cover_file_id"]:
        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer_photo(
            photo=anime["cover_file_id"],
            caption=text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    else:
        try:
            await call.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except:
            await call.message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await call.answer()

# ── Epizod ───────────────────────────────────────
@dp.callback_query(F.data.startswith("ep:"))
async def cb_episode(call: CallbackQuery):
    not_sub = await check_subscriptions(call.from_user.id)
    if not_sub and not is_admin(call.from_user.id):
        await send_subscribe_message(call, not_sub)
        await call.answer(); return

    parts = call.data.split(":")
    ep_id, anime_id, back_page = int(parts[1]), int(parts[2]), int(parts[3])

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT e.*, a.title AS anime_title, a.total_episodes
            FROM episodes e JOIN animes a ON e.anime_id=a.id
            WHERE e.id=?
        """, (ep_id,)) as cur:
            ep = await cur.fetchone()
        if not ep:
            await call.answer("Topilmadi!", show_alert=True)
            return
        async with db.execute(
            "SELECT id FROM episodes WHERE anime_id=? AND episode_number=?",
            (anime_id, ep["episode_number"] - 1)
        ) as cur:
            prev_ep = await cur.fetchone()
        async with db.execute(
            "SELECT id FROM episodes WHERE anime_id=? AND episode_number=?",
            (anime_id, ep["episode_number"] + 1)
        ) as cur:
            next_ep = await cur.fetchone()
        await db.execute(
            "INSERT INTO watch_history (user_id, anime_id, episode_id) VALUES (?,?,?)",
            (call.from_user.id, anime_id, ep_id)
        )
        await db.commit()

    builder = InlineKeyboardBuilder()
    if prev_ep:
        builder.button(text="⬅️ Oldingi", callback_data=f"ep:{prev_ep['id']}:{anime_id}:{back_page}")
    if next_ep:
        builder.button(text="Keyingi ➡️", callback_data=f"ep:{next_ep['id']}:{anime_id}:{back_page}")
    builder.button(text="🔙 Animega qaytish", callback_data=f"anime:{anime_id}:{back_page}")
    cols = 2 if (prev_ep and next_ep) else 1
    builder.adjust(cols, 1)

    # Anime nomi va qism raqami aniq ko'rsatiladi
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM episodes WHERE anime_id=?", (anime_id,)
        ) as cur:
            total_uploaded = (await cur.fetchone())[0]

    caption = (
        f"🎌 *{ep['anime_title']}*\n"
        f"▶️ *{ep['episode_number']}-qism*  /  {total_uploaded} qism"
    )
    await call.message.answer_video(
        video=ep["video_file_id"],
        caption=caption,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await call.answer()

# ── Sevimlilar ───────────────────────────────────
@dp.callback_query(F.data.startswith("fav:"))
async def cb_fav(call: CallbackQuery):
    parts = call.data.split(":")
    anime_id = int(parts[1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM favorites WHERE user_id=? AND anime_id=?",
            (call.from_user.id, anime_id)
        ) as cur:
            exists = await cur.fetchone()
        if exists:
            await db.execute("DELETE FROM favorites WHERE user_id=? AND anime_id=?",
                             (call.from_user.id, anime_id))
            msg = "💔 Sevimlilardan olib tashlandi"
        else:
            await db.execute("INSERT INTO favorites (user_id, anime_id) VALUES (?,?)",
                             (call.from_user.id, anime_id))
            msg = "❤️ Sevimliga qo'shildi!"
        await db.commit()
    await call.answer(msg, show_alert=True)
    call.data = f"anime:{anime_id}:{parts[2]}"
    await cb_anime(call)

@dp.message(Command("favorites"))
async def cmd_favs(message: Message):
    not_sub = await check_subscriptions(message.from_user.id)
    if not_sub and not is_admin(message.from_user.id):
        await send_subscribe_message(message, not_sub); return

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT a.id, a.title, a.total_episodes
            FROM favorites f JOIN animes a ON f.anime_id=a.id
            WHERE f.user_id=? ORDER BY a.title
        """, (message.from_user.id,)) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer("❤️ Sevimlilar bo'sh\n\n/list dan animani ochib ❤️ bosing!")
        return

    builder = InlineKeyboardBuilder()
    for a in rows:
        builder.button(
            text=f"🎬 {a['title']} [{a['total_episodes']} qism]",
            callback_data=f"anime:{a['id']}:0"
        )
    builder.adjust(1)
    await message.answer(
        f"❤️ *Sevimlilarim* ({len(rows)} ta):",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

# ── Tarix ────────────────────────────────────────
@dp.message(Command("history"))
async def cmd_history(message: Message):
    not_sub = await check_subscriptions(message.from_user.id)
    if not_sub and not is_admin(message.from_user.id):
        await send_subscribe_message(message, not_sub); return

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT a.id, a.title, e.episode_number
            FROM watch_history wh
            JOIN animes a ON wh.anime_id=a.id
            JOIN episodes e ON wh.episode_id=e.id
            WHERE wh.user_id=?
            GROUP BY a.id
            ORDER BY MAX(wh.watched_at) DESC
            LIMIT 10
        """, (message.from_user.id,)) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer("🕐 Tarix bo'sh")
        return

    builder = InlineKeyboardBuilder()
    for h in rows:
        builder.button(
            text=f"🎬 {h['title']} — {h['episode_number']}-qism",
            callback_data=f"anime:{h['id']}:0"
        )
    builder.adjust(1)
    await message.answer("🕐 *Oxirgi ko'rganlarim:*",
                         reply_markup=builder.as_markup(), parse_mode="Markdown")

# ── Qidirish ─────────────────────────────────────
@dp.message(Command("search"))
async def cmd_search(message: Message):
    not_sub = await check_subscriptions(message.from_user.id)
    if not_sub and not is_admin(message.from_user.id):
        await send_subscribe_message(message, not_sub); return

    q = message.text.replace("/search", "").strip()
    if not q:
        await message.answer("🔍 Misol: /search Naruto")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, title, total_episodes FROM animes WHERE title LIKE ? ORDER BY title LIMIT 10",
            (f"%{q}%",)
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer(f"😔 *{q}* topilmadi", parse_mode="Markdown")
        return

    builder = InlineKeyboardBuilder()
    for a in rows:
        builder.button(
            text=f"🎬 {a['title']} [{a['total_episodes']} qism]",
            callback_data=f"anime:{a['id']}:0"
        )
    builder.adjust(1)
    await message.answer(
        f"🔍 *'{q}'* — {len(rows)} ta natija:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

# ── Admin /stats va /delanime komandalar ─────────
@dp.message(Command("stats"))
async def adm_stats(message: Message):
    if not is_admin(message.from_user.id): return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c: users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM animes") as c: animes = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM episodes") as c: eps = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM watch_history") as c: views = (await c.fetchone())[0]
    await message.answer(
        f"📊 *Statistika:*\n\n"
        f"👥 Foydalanuvchilar: *{users}*\n"
        f"🎬 Animalar: *{animes}*\n"
        f"▶️ Epizodlar: *{eps}*\n"
        f"👁 Ko'rishlar: *{views}*",
        parse_mode="Markdown"
    )

@dp.message(Command("delanime"))
async def adm_del(message: Message):
    if not is_admin(message.from_user.id): return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Format: /delanime <id>"); return
    try:
        aid = int(parts[1])
    except:
        await message.answer("❌ Raqam kiriting!"); return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT title FROM animes WHERE id=?", (aid,)) as cur:
            anime = await cur.fetchone()
        if not anime:
            await message.answer(f"❌ ID={aid} topilmadi!"); return
        await db.execute("DELETE FROM animes WHERE id=?", (aid,))
        await db.commit()
    await message.answer(f"✅ *{anime['title']}* o'chirildi!", parse_mode="Markdown")

# ── Main ─────────────────────────────────────────
async def main():
    await init_db()
    print("✅ Bot ishga tushdi!")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
