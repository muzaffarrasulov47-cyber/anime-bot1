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

# ═══════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════
TOKEN      = "8242189843:AAGnSO5m2zJVHft_kmsAv3YGYrx3Miu-roo"
ADMIN_IDS  = [8419078274]
DB_PATH    = "anime.db"
PAGE_SIZE  = 8

bot = Bot(token=TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ═══════════════════════════════════════════════════════
# FSM
# ═══════════════════════════════════════════════════════
class AddAnime(StatesGroup):
    title       = State()
    description = State()
    cover       = State()

class AddEpisode(StatesGroup):
    select_anime = State()
    uploading    = State()

class AddChannel(StatesGroup):
    waiting = State()

class Broadcast(StatesGroup):
    message = State()

class Searching(StatesGroup):
    waiting = State()

# ═══════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS animes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
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

def is_admin(uid): return uid in ADMIN_IDS

# ═══════════════════════════════════════════════════════
# OBUNA TEKSHIRISH
# ═══════════════════════════════════════════════════════
async def get_not_subscribed(user_id: int) -> list:
    result = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM required_channels") as cur:
            channels = await cur.fetchall()
    for ch in channels:
        try:
            m = await bot.get_chat_member(ch["channel_id"], user_id)
            if m.status in ("left", "kicked", "banned"):
                result.append(dict(ch))
        except:
            result.append(dict(ch))
    return result

async def sub_wall(event, user_id: int) -> bool:
    if is_admin(user_id):
        return True
    not_sub = await get_not_subscribed(user_id)
    if not not_sub:
        return True
    builder = InlineKeyboardBuilder()
    for ch in not_sub:
        title = ch["channel_title"] or ch["channel_id"]
        link  = ch["invite_link"] or f"https://t.me/{ch['channel_id'].lstrip('@')}"
        builder.button(text=f"📢 {title}", url=link)
    builder.button(text="✅ Obuna bo'ldim, tekshir", callback_data="check_sub")
    builder.adjust(1)
    text = (
        "⚠️ *Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:*\n\n"
        + "\n".join(f"• {ch['channel_title'] or ch['channel_id']}" for ch in not_sub)
        + "\n\nObuna bo'lgach ✅ tugmasini bosing."
    )
    if isinstance(event, Message):
        await event.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        try:
            await event.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except:
            await event.message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        await event.answer()
    return False

@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(call: CallbackQuery):
    not_sub = await get_not_subscribed(call.from_user.id)
    if not_sub:
        await call.answer("❌ Hali ham obuna bo'lmadingiz!", show_alert=True)
        return
    await call.answer("✅ Rahmat! Botdan foydalanishingiz mumkin.", show_alert=True)
    try:
        await call.message.delete()
    except:
        pass
    await send_main_menu(call.message, call.from_user.id,
                         call.from_user.full_name or call.from_user.first_name or "Foydalanuvchi")

# ═══════════════════════════════════════════════════════
# BOSH MENYU
# ═══════════════════════════════════════════════════════
async def send_main_menu(message: Message, user_id: int, name: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🎬 Animalar",      callback_data="menu_list")
    builder.button(text="🔍 Qidirish",      callback_data="menu_search")
    builder.button(text="❤️ Sevimlilar",    callback_data="menu_favs")
    builder.button(text="🕐 Ko'rish tarixi",callback_data="menu_history")
    builder.adjust(2, 2)

    if is_admin(user_id):
        builder.button(text="⚙️ Admin panel", callback_data="admin_panel")
        builder.adjust(2, 2, 1)

    await message.answer(
        f"🎌 Salom, *{name}*!\n\n"
        "Anime botga xush kelibsiz!\n"
        "Quyidagi bo'limlardan birini tanlang:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════════════
# /start
# ═══════════════════════════════════════════════════════
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid  = message.from_user.id
    name = message.from_user.full_name or message.from_user.first_name or "Foydalanuvchi"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (id, username, full_name) VALUES (?,?,?)",
            (uid, message.from_user.username or "", name)
        )
        await db.commit()
    if not await sub_wall(message, uid):
        return
    await send_main_menu(message, uid, name)

@dp.callback_query(F.data == "back_main")
async def cb_back_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    uid  = call.from_user.id
    name = call.from_user.full_name or call.from_user.first_name or "Foydalanuvchi"
    try:
        await call.message.delete()
    except:
        pass
    await send_main_menu(call.message, uid, name)
    await call.answer()

# ═══════════════════════════════════════════════════════
# ADMIN PANEL
# ═══════════════════════════════════════════════════════
@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Anime qo'shish",  callback_data="adm_add_anime")
    builder.button(text="📤 Qism yuklash",    callback_data="adm_add_ep")
    builder.button(text="🗑 Anime o'chirish", callback_data="adm_del_anime")
    builder.button(text="📢 Majburiy obuna",  callback_data="adm_channels")
    builder.button(text="📊 Statistika",      callback_data="adm_stats")
    builder.button(text="📣 Xabar yuborish",  callback_data="adm_broadcast")
    builder.button(text="🔙 Bosh menyu",      callback_data="back_main")
    builder.adjust(2, 2, 2, 1)
    try:
        await call.message.edit_text(
            "⚙️ *Admin panel*\n\nNimani qilmoqchisiz?",
            reply_markup=builder.as_markup(), parse_mode="Markdown"
        )
    except:
        await call.message.answer(
            "⚙️ *Admin panel*\n\nNimani qilmoqchisiz?",
            reply_markup=builder.as_markup(), parse_mode="Markdown"
        )
    await call.answer()

# ═══════════════════════════════════════════════════════
# ANIME QO'SHISH
# ═══════════════════════════════════════════════════════
@dp.callback_query(F.data == "adm_add_anime")
async def cb_adm_add_anime(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await state.set_state(AddAnime.title)
    await call.message.edit_text(
        "➕ *Yangi anime qo'shish*\n\n"
        "1️⃣ Anime nomini yozing:\n\n"
        "_Bekor qilish uchun /cancel_",
        parse_mode="Markdown"
    )
    await call.answer()

@dp.message(AddAnime.title)
async def st_anime_title(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/cancel"):
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(AddAnime.description)
    await message.answer(
        "2️⃣ *Tavsif* yozing (o'tkazish: /skip):\n\n_Bekor: /cancel_",
        parse_mode="Markdown"
    )

@dp.message(AddAnime.description)
async def st_anime_desc(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/cancel"):
        await state.clear(); await message.answer("❌ Bekor qilindi."); return
    desc = "" if (message.text and message.text == "/skip") else (message.text or "").strip()
    await state.update_data(description=desc)
    await state.set_state(AddAnime.cover)
    await message.answer(
        "3️⃣ *Muqova rasm* yuboring (o'tkazish: /skip):\n\n_Bekor: /cancel_",
        parse_mode="Markdown"
    )

@dp.message(AddAnime.cover)
async def st_anime_cover(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/cancel"):
        await state.clear(); await message.answer("❌ Bekor qilindi."); return
    cover_id = None
    if message.photo:
        cover_id = message.photo[-1].file_id
    elif message.text and message.text != "/skip":
        await message.answer("🖼 Rasm yuboring yoki /skip yozing!"); return
    d = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO animes (title, description, cover_file_id) VALUES (?,?,?)",
            (d["title"], d["description"], cover_id)
        )
        anime_id = cur.lastrowid
        await db.commit()
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Hoziroq qism yuklash", callback_data=f"ep_pick:{anime_id}")
    builder.button(text="🔙 Admin panel",          callback_data="admin_panel")
    builder.adjust(1)
    await message.answer(
        f"✅ *{d['title']}* qo'shildi! (ID: `{anime_id}`)",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════════════
# QISM YUKLASH
# ═══════════════════════════════════════════════════════
@dp.callback_query(F.data == "adm_add_ep")
async def cb_adm_add_ep(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await show_anime_picker(call, state)
    await call.answer()

async def show_anime_picker(call: CallbackQuery, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, title, total_episodes FROM animes ORDER BY title") as cur:
            animes = await cur.fetchall()
    if not animes:
        try:
            await call.message.edit_text(
                "😔 Hozircha anime yo'q.\nAvval anime qo'shing!",
            )
        except:
            await call.message.answer("😔 Hozircha anime yo'q.")
        return
    builder = InlineKeyboardBuilder()
    for a in animes:
        builder.button(
            text=f"🎬 {a['title']}  [{a['total_episodes']} qism]",
            callback_data=f"ep_pick:{a['id']}"
        )
    builder.button(text="🔙 Admin panel", callback_data="admin_panel")
    builder.adjust(1)
    await state.set_state(AddEpisode.select_anime)
    try:
        await call.message.edit_text(
            "📤 *Qism yuklash*\n\nQaysi animega qism qo'shmoqchisiz?",
            reply_markup=builder.as_markup(), parse_mode="Markdown"
        )
    except:
        await call.message.answer(
            "📤 *Qism yuklash*\n\nQaysi animega qism qo'shmoqchisiz?",
            reply_markup=builder.as_markup(), parse_mode="Markdown"
        )

@dp.callback_query(F.data.startswith("ep_pick:"))
async def cb_ep_pick(call: CallbackQuery, state: FSMContext):
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
    await state.set_state(AddEpisode.uploading)
    await state.update_data(anime_id=anime_id, anime_title=anime["title"], next_ep=next_ep)
    try:
        await call.message.edit_text(
            f"🎬 *{anime['title']}*\n\n"
            f"✅ Hozirga *{last_ep}* ta qism yuklangan\n\n"
            f"▶️ *{next_ep}-qism* videosini yuboring.\n"
            f"_(Ketma-ket yuboring, avtomatik raqamlashadi)_\n\n"
            f"Tugatish: /done",
            parse_mode="Markdown"
        )
    except:
        await call.message.answer(
            f"🎬 *{anime['title']}*\n\n"
            f"▶️ *{next_ep}-qism* videosini yuboring.\nTugatish: /done",
            parse_mode="Markdown"
        )
    await call.answer()

@dp.message(AddEpisode.uploading, F.video)
async def st_upload_video(message: Message, state: FSMContext):
    d = await state.get_data()
    anime_id, anime_title, next_ep = d["anime_id"], d["anime_title"], d["next_ep"]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO episodes (anime_id, episode_number, video_file_id)
            VALUES (?,?,?)
            ON CONFLICT(anime_id,episode_number)
            DO UPDATE SET video_file_id=excluded.video_file_id
        """, (anime_id, next_ep, message.video.file_id))
        await db.execute(
            "UPDATE animes SET total_episodes=(SELECT COUNT(*) FROM episodes WHERE anime_id=?) WHERE id=?",
            (anime_id, anime_id)
        )
        await db.commit()
    new_next = next_ep + 1
    await state.update_data(next_ep=new_next)
    await message.answer(
        f"✅ *{anime_title}* — *{next_ep}-qism* saqlandi!\n"
        f"▶️ Endi *{new_next}-qism* videosini yuboring.\n"
        f"Tugatish: /done",
        parse_mode="Markdown"
    )

@dp.message(AddEpisode.uploading)
async def st_upload_wrong(message: Message, state: FSMContext):
    if message.text and (message.text.startswith("/done") or message.text.startswith("/cancel")):
        d = await state.get_data()
        last = d.get("next_ep", 1) - 1
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Admin panel", callback_data="admin_panel")
        await message.answer(
            f"✅ *{d.get('anime_title','Anime')}* uchun jami *{last}* qism yuklandi!",
            reply_markup=builder.as_markup(), parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Faqat video yuboring!\nTugatish uchun: /done")

@dp.message(Command("done"))
async def cmd_done(message: Message, state: FSMContext):
    if await state.get_state() == AddEpisode.uploading:
        d = await state.get_data()
        last = d.get("next_ep", 1) - 1
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Admin panel", callback_data="admin_panel")
        await message.answer(
            f"✅ *{d.get('anime_title','Anime')}* uchun jami *{last}* qism yuklandi!",
            reply_markup=builder.as_markup(), parse_mode="Markdown"
        )
    else:
        await message.answer("Hozir yuklash jarayoni yo'q.")

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Bekor qilindi.")

# ═══════════════════════════════════════════════════════
# ANIME O'CHIRISH
# ═══════════════════════════════════════════════════════
@dp.callback_query(F.data == "adm_del_anime")
async def cb_adm_del_anime(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, title FROM animes ORDER BY title") as cur:
            animes = await cur.fetchall()
    if not animes:
        await call.message.edit_text("😔 Hozircha anime yo'q.")
        await call.answer(); return
    builder = InlineKeyboardBuilder()
    for a in animes:
        builder.button(text=f"🗑 {a['title']}", callback_data=f"del_yes:{a['id']}")
    builder.button(text="🔙 Admin panel", callback_data="admin_panel")
    builder.adjust(1)
    await call.message.edit_text(
        "🗑 *Qaysi animeni o'chirmoqchisiz?*\n_(Barcha qismlari ham o'chadi)_",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("del_yes:"))
async def cb_del_yes(call: CallbackQuery):
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
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Admin panel", callback_data="admin_panel")
    await call.message.edit_text(
        f"✅ *{anime['title']}* o'chirildi!",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )
    await call.answer()

# ═══════════════════════════════════════════════════════
# MAJBURIY OBUNA
# ═══════════════════════════════════════════════════════
@dp.callback_query(F.data == "adm_channels")
async def cb_adm_channels(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await show_ch_panel(call.message, edit=True)
    await call.answer()

async def show_ch_panel(message: Message, edit=False):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM required_channels") as cur:
            channels = await cur.fetchall()
    builder = InlineKeyboardBuilder()
    text = "📢 *Majburiy obuna kanallari:*\n\n"
    if channels:
        for ch in channels:
            text += f"• {ch['channel_title'] or ch['channel_id']}\n"
            builder.button(
                text=f"🗑 {ch['channel_title'] or ch['channel_id']}",
                callback_data=f"del_ch:{ch['id']}"
            )
    else:
        text += "_(Hozircha kanal yo'q)_\n"
    builder.button(text="➕ Kanal qo'shish", callback_data="add_ch")
    builder.button(text="🔙 Admin panel",    callback_data="admin_panel")
    builder.adjust(1)
    if edit:
        try:
            await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
            return
        except:
            pass
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "add_ch")
async def cb_add_ch(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await state.set_state(AddChannel.waiting)
    await call.message.edit_text(
        "📢 *Kanal qo'shish*\n\n"
        "Quyidagilardan birini yuboring:\n"
        "1️⃣ `@username` — kanal username\n"
        "2️⃣ `-100xxxxxxxxxx` — kanal ID\n"
        "3️⃣ Kanaldan xabar *forward* qiling\n\n"
        "⚠️ Bot kanalda *admin* bo'lishi shart!\n\n"
        "Bekor: /cancel",
        parse_mode="Markdown"
    )
    await call.answer()

@dp.message(AddChannel.waiting)
async def st_channel_add(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/cancel"):
        await state.clear(); await message.answer("❌ Bekor qilindi."); return
    channel_id, channel_title, invite_link = None, None, None
    if message.forward_from_chat:
        chat = message.forward_from_chat
        channel_id, channel_title = str(chat.id), chat.title
        try:
            inv = await bot.create_chat_invite_link(chat.id)
            invite_link = inv.invite_link
        except:
            invite_link = f"https://t.me/{chat.username}" if chat.username else None
    elif message.text:
        try:
            chat = await bot.get_chat(message.text.strip())
            channel_id, channel_title = str(chat.id), chat.title
            try:
                inv = await bot.create_chat_invite_link(chat.id)
                invite_link = inv.invite_link
            except:
                invite_link = f"https://t.me/{chat.username}" if chat.username else None
        except Exception as e:
            await message.answer(f"❌ Kanal topilmadi!\nBot admin qilinganmi?\n`{e}`", parse_mode="Markdown")
            return
    else:
        await message.answer("❌ Username, ID yoki forward xabar yuboring!"); return

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO required_channels (channel_id, channel_title, invite_link) VALUES (?,?,?)",
                (channel_id, channel_title, invite_link)
            )
            await db.commit()
        except:
            await message.answer("⚠️ Bu kanal allaqachon qo'shilgan!")
            await state.clear(); return
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Kanallar paneli", callback_data="adm_channels")
    await message.answer(
        f"✅ *{channel_title or channel_id}* kanali qo'shildi!\nHavola: {invite_link or 'Mavjud emas'}",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("del_ch:"))
async def cb_del_ch(call: CallbackQuery):
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
    await show_ch_panel(call.message, edit=True)

# ═══════════════════════════════════════════════════════
# STATISTIKA
# ═══════════════════════════════════════════════════════
@dp.callback_query(F.data == "adm_stats")
async def cb_adm_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:             users  = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM animes") as c:            animes = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM episodes") as c:          eps    = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM watch_history") as c:     views  = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM required_channels") as c: chs    = (await c.fetchone())[0]
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Admin panel", callback_data="admin_panel")
    await call.message.edit_text(
        f"📊 *Statistika*\n\n"
        f"👥 Foydalanuvchilar: *{users}*\n"
        f"🎬 Animalar: *{animes}*\n"
        f"▶️ Jami qismlar: *{eps}*\n"
        f"👁 Ko'rishlar: *{views}*\n"
        f"📢 Obuna kanallari: *{chs}*",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )
    await call.answer()

# ═══════════════════════════════════════════════════════
# BROADCAST
# ═══════════════════════════════════════════════════════
@dp.callback_query(F.data == "adm_broadcast")
async def cb_adm_broadcast(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await state.set_state(Broadcast.message)
    await call.message.edit_text(
        "📣 *Barcha foydalanuvchilarga xabar yuborish*\n\n"
        "Xabarni kiriting (matn, rasm, video — istalgan format):\n\n"
        "Bekor: /cancel",
        parse_mode="Markdown"
    )
    await call.answer()

@dp.message(Broadcast.message)
async def st_broadcast(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/cancel"):
        await state.clear(); await message.answer("❌ Bekor qilindi."); return
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM users") as cur:
            users = await cur.fetchall()
    sent = fail = 0
    prog = await message.answer(f"📣 Yuborilmoqda... 0/{len(users)}")
    for i, (uid,) in enumerate(users):
        try:
            await message.copy_to(uid)
            sent += 1
        except:
            fail += 1
        if (i + 1) % 20 == 0:
            try: await prog.edit_text(f"📣 Yuborilmoqda... {i+1}/{len(users)}")
            except: pass
        await asyncio.sleep(0.05)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Admin panel", callback_data="admin_panel")
    await prog.edit_text(
        f"✅ *Xabar yuborildi!*\n\n✔️ Muvaffaqiyatli: *{sent}*\n❌ Bloklaganlar: *{fail}*",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════════════
# ANIMALAR RO'YXATI (foydalanuvchi)
# ═══════════════════════════════════════════════════════
@dp.callback_query(F.data == "menu_list")
async def cb_menu_list(call: CallbackQuery):
    if not await sub_wall(call, call.from_user.id): return
    await show_anime_list(call.message, 0, edit=True)
    await call.answer()

@dp.callback_query(F.data.startswith("alist:"))
async def cb_alist_page(call: CallbackQuery):
    if not await sub_wall(call, call.from_user.id): return
    page = int(call.data.split(":")[1])
    await show_anime_list(call.message, page, edit=True)
    await call.answer()

async def show_anime_list(message: Message, page: int, edit=False):
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

    builder = InlineKeyboardBuilder()
    if not animes:
        builder.button(text="🔙 Bosh menyu", callback_data="back_main")
        txt = "😔 Hozircha anime yo'q"
        if edit:
            try: await message.edit_text(txt, reply_markup=builder.as_markup()); return
            except: pass
        await message.answer(txt, reply_markup=builder.as_markup()); return

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    for a in animes:
        builder.button(
            text=f"🎬 {a['title']}  [{a['total_episodes']} qism]",
            callback_data=f"anime:{a['id']}:{page}"
        )
    builder.adjust(1)
    # Navigatsiya
    nav = []
    if page > 0:           nav.append(("⬅️ Oldingi", f"alist:{page-1}"))
    if offset+PAGE_SIZE < total: nav.append(("Keyingi ➡️", f"alist:{page+1}"))
    for t, d in nav:
        builder.button(text=t, callback_data=d)
    if len(nav) == 2: builder.adjust(*([1]*len(animes)), 2, 1)
    elif len(nav) == 1: builder.adjust(*([1]*len(animes)), 1, 1)
    builder.button(text="🔙 Bosh menyu", callback_data="back_main")

    header = f"📋 *Animalar ro'yxati*\n({page+1}/{total_pages} sahifa • jami {total} ta)\n"
    if edit:
        try:
            await message.edit_text(header, reply_markup=builder.as_markup(), parse_mode="Markdown")
            return
        except: pass
    await message.answer(header, reply_markup=builder.as_markup(), parse_mode="Markdown")

# ═══════════════════════════════════════════════════════
# ANIME DETAIL
# ═══════════════════════════════════════════════════════
@dp.callback_query(F.data.startswith("anime:"))
async def cb_anime_detail(call: CallbackQuery):
    if not await sub_wall(call, call.from_user.id): return
    parts    = call.data.split(":")
    anime_id = int(parts[1])
    back_pg  = int(parts[2])

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
        await call.answer("Topilmadi!", show_alert=True); return

    builder = InlineKeyboardBuilder()
    for ep in episodes:
        builder.button(
            text=f"▶️ {ep['episode_number']}-qism",
            callback_data=f"ep:{ep['id']}:{anime_id}:{back_pg}"
        )
    if episodes: builder.adjust(3)

    fav_txt = "💔 Sevimlilardan chiqarish" if is_fav else "❤️ Sevimliga qo'shish"
    builder.button(text=fav_txt,                 callback_data=f"fav:{anime_id}:{back_pg}")
    builder.button(text="🔙 Ro'yxatga qaytish",  callback_data=f"alist:{back_pg}")
    builder.adjust(1) if not episodes else None

    ep_count = len(episodes)
    desc = (anime["description"] or "Tavsif yo'q")[:500]
    text = (
        f"🎬 *{anime['title']}*\n\n"
        f"📺 Yuklangan qismlar: *{ep_count}* ta\n\n"
        f"📝 {desc}"
    )

    if anime["cover_file_id"]:
        try: await call.message.delete()
        except: pass
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

# ═══════════════════════════════════════════════════════
# QISM KO'RISH
# ═══════════════════════════════════════════════════════
@dp.callback_query(F.data.startswith("ep:"))
async def cb_watch_episode(call: CallbackQuery):
    if not await sub_wall(call, call.from_user.id): return
    parts    = call.data.split(":")
    ep_id    = int(parts[1])
    anime_id = int(parts[2])
    back_pg  = int(parts[3])

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT e.*, a.title AS anime_title
            FROM episodes e JOIN animes a ON e.anime_id=a.id
            WHERE e.id=?
        """, (ep_id,)) as cur:
            ep = await cur.fetchone()
        if not ep:
            await call.answer("Topilmadi!", show_alert=True); return
        async with db.execute(
            "SELECT id FROM episodes WHERE anime_id=? AND episode_number=?",
            (anime_id, ep["episode_number"] - 1)
        ) as cur: prev_ep = await cur.fetchone()
        async with db.execute(
            "SELECT id FROM episodes WHERE anime_id=? AND episode_number=?",
            (anime_id, ep["episode_number"] + 1)
        ) as cur: next_ep = await cur.fetchone()
        async with db.execute(
            "SELECT COUNT(*) FROM episodes WHERE anime_id=?", (anime_id,)
        ) as cur: total_eps = (await cur.fetchone())[0]
        await db.execute(
            "INSERT INTO watch_history (user_id, anime_id, episode_id) VALUES (?,?,?)",
            (call.from_user.id, anime_id, ep_id)
        )
        await db.commit()

    builder = InlineKeyboardBuilder()
    if prev_ep:
        builder.button(text="⬅️ Oldingi", callback_data=f"ep:{prev_ep['id']}:{anime_id}:{back_pg}")
    if next_ep:
        builder.button(text="Keyingi ➡️", callback_data=f"ep:{next_ep['id']}:{anime_id}:{back_pg}")
    builder.button(text="🔙 Animega qaytish", callback_data=f"anime:{anime_id}:{back_pg}")
    cols = 2 if (prev_ep and next_ep) else 1
    builder.adjust(cols, 1)

    caption = (
        f"🎌 *{ep['anime_title']}*\n"
        f"▶️ *{ep['episode_number']}-qism*  /  {total_eps} ta qism"
    )
    await call.message.answer_video(
        video=ep["video_file_id"],
        caption=caption,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await call.answer()

# ═══════════════════════════════════════════════════════
# SEVIMLILAR
# ═══════════════════════════════════════════════════════
@dp.callback_query(F.data == "menu_favs")
async def cb_menu_favs(call: CallbackQuery):
    if not await sub_wall(call, call.from_user.id): return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT a.id, a.title, a.total_episodes
            FROM favorites f JOIN animes a ON f.anime_id=a.id
            WHERE f.user_id=? ORDER BY a.title
        """, (call.from_user.id,)) as cur:
            rows = await cur.fetchall()
    builder = InlineKeyboardBuilder()
    if not rows:
        builder.button(text="🎬 Animalar ro'yxati", callback_data="menu_list")
        builder.button(text="🔙 Bosh menyu",        callback_data="back_main")
        builder.adjust(1)
        await call.message.edit_text(
            "❤️ Sevimlilar bo'sh\n\nAnimani ochib ❤️ tugmasini bosing!",
            reply_markup=builder.as_markup()
        )
        await call.answer(); return
    for a in rows:
        builder.button(
            text=f"🎬 {a['title']} [{a['total_episodes']} qism]",
            callback_data=f"anime:{a['id']}:0"
        )
    builder.button(text="🔙 Bosh menyu", callback_data="back_main")
    builder.adjust(1)
    await call.message.edit_text(
        f"❤️ *Sevimlilarim* ({len(rows)} ta):",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("fav:"))
async def cb_fav_toggle(call: CallbackQuery):
    parts    = call.data.split(":")
    anime_id = int(parts[1])
    back_pg  = int(parts[2])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM favorites WHERE user_id=? AND anime_id=?",
            (call.from_user.id, anime_id)
        ) as cur: exists = await cur.fetchone()
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
    call.data = f"anime:{anime_id}:{back_pg}"
    await cb_anime_detail(call)

# ═══════════════════════════════════════════════════════
# KO'RISH TARIXI
# ═══════════════════════════════════════════════════════
@dp.callback_query(F.data == "menu_history")
async def cb_menu_history(call: CallbackQuery):
    if not await sub_wall(call, call.from_user.id): return
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
        """, (call.from_user.id,)) as cur:
            rows = await cur.fetchall()
    builder = InlineKeyboardBuilder()
    if not rows:
        builder.button(text="🎬 Animalar ro'yxati", callback_data="menu_list")
        builder.button(text="🔙 Bosh menyu",        callback_data="back_main")
        builder.adjust(1)
        await call.message.edit_text("🕐 Ko'rish tarixi bo'sh", reply_markup=builder.as_markup())
        await call.answer(); return
    for h in rows:
        builder.button(
            text=f"🎬 {h['title']} — {h['episode_number']}-qism",
            callback_data=f"anime:{h['id']}:0"
        )
    builder.button(text="🔙 Bosh menyu", callback_data="back_main")
    builder.adjust(1)
    await call.message.edit_text(
        "🕐 *Oxirgi ko'rganlarim:*",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )
    await call.answer()

# ═══════════════════════════════════════════════════════
# QIDIRISH
# ═══════════════════════════════════════════════════════
@dp.callback_query(F.data == "menu_search")
async def cb_menu_search(call: CallbackQuery, state: FSMContext):
    if not await sub_wall(call, call.from_user.id): return
    await state.set_state(Searching.waiting)
    await call.message.edit_text(
        "🔍 *Qidirish*\n\nAnime nomini yozing:",
        parse_mode="Markdown"
    )
    await call.answer()

@dp.message(Searching.waiting)
async def st_search(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        await state.clear(); return
    if not await sub_wall(message, message.from_user.id): return
    await state.clear()
    q = (message.text or "").strip()
    if not q:
        await message.answer("❌ Nom kiriting!"); return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, title, total_episodes FROM animes WHERE title LIKE ? ORDER BY title LIMIT 10",
            (f"%{q}%",)
        ) as cur:
            rows = await cur.fetchall()
    builder = InlineKeyboardBuilder()
    if not rows:
        builder.button(text="🔍 Qayta qidirish", callback_data="menu_search")
        builder.button(text="🔙 Bosh menyu",     callback_data="back_main")
        builder.adjust(1)
        await message.answer(
            f"😔 *'{q}'* topilmadi",
            reply_markup=builder.as_markup(), parse_mode="Markdown"
        ); return
    for a in rows:
        builder.button(
            text=f"🎬 {a['title']} [{a['total_episodes']} qism]",
            callback_data=f"anime:{a['id']}:0"
        )
    builder.button(text="🔍 Qayta qidirish", callback_data="menu_search")
    builder.button(text="🔙 Bosh menyu",     callback_data="back_main")
    builder.adjust(1)
    await message.answer(
        f"🔍 *'{q}'* — {len(rows)} ta natija:",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════
async def main():
    await init_db()
    print("✅ Anime Bot ishga tushdi!")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
