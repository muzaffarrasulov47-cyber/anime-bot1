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
    genre = State()
    rating = State()
    total_episodes = State()
    cover = State()

class AddEpisode(StatesGroup):
    anime_id = State()
    episode_number = State()
    video = State()

# ── DB init ──────────────────────────────────────
async def init_db():
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
                genre TEXT,
                rating REAL DEFAULT 0,
                cover_file_id TEXT,
                total_episodes INTEGER DEFAULT 0,
                status TEXT DEFAULT 'ongoing'
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
        """)
        await db.commit()

def is_admin(uid): return uid == ADMIN_ID

# ── /start ───────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (id, username) VALUES (?,?)",
            (message.from_user.id, message.from_user.username or "")
        )
        await db.commit()

    text = (
        "🎌 *Anime Bot ga xush kelibsiz!*\n\n"
        "📋 /list — Barcha animalar\n"
        "🔍 /search <nom> — Qidirish\n"
        "❤️ /favorites — Sevimlilarim\n"
        "🕐 /history — Tarixim\n"
    )
    if is_admin(message.from_user.id):
        text += (
            "\n⚙️ *Admin paneli:*\n"
            "/addanime — Anime qo'shish\n"
            "/addepisode — Epizod yuklash\n"
            "/delanime <id> — O'chirish\n"
            "/stats — Statistika\n"
        )
    await message.answer(text, parse_mode="Markdown")

# ── /list ────────────────────────────────────────
@dp.message(Command("list"))
async def cmd_list(message: Message):
    await show_list(message, 0)

async def show_list(event, page):
    offset = page * PAGE_SIZE
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id,title,total_episodes,status FROM animes ORDER BY title LIMIT ? OFFSET ?",
            (PAGE_SIZE, offset)
        ) as cur:
            animes = await cur.fetchall()
        async with db.execute("SELECT COUNT(*) FROM animes") as cur:
            total = (await cur.fetchone())[0]

    if not animes:
        txt = "😔 Hozircha anime yo'q\n\nAdmin /addanime orqali qo'shishi mumkin"
        if isinstance(event, Message):
            await event.answer(txt)
        else:
            await event.message.edit_text(txt)
        return

    builder = InlineKeyboardBuilder()
    for a in animes:
        icon = "🟢" if a["status"] == "ongoing" else "✅"
        builder.button(
            text=f"🎬 {a['title']}  [{a['total_episodes']} qism] {icon}",
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
    page = int(call.data.split(":")[1])
    await show_list(call, page)
    await call.answer()

# ── Anime detail ─────────────────────────────────
@dp.callback_query(F.data.startswith("anime:"))
async def cb_anime(call: CallbackQuery):
    _, anime_id, back_page = call.data.split(":")
    anime_id, back_page = int(anime_id), int(back_page)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM animes WHERE id=?", (anime_id,)) as cur:
            anime = await cur.fetchone()
        async with db.execute(
            "SELECT id,episode_number FROM episodes WHERE anime_id=? ORDER BY episode_number",
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

    status_txt = "🟢 Davom etmoqda" if anime["status"] == "ongoing" else "✅ Tugallangan"
    desc = (anime["description"] or "")[:350]
    text = (
        f"🎬 *{anime['title']}*\n\n"
        f"⭐ Reyting: *{anime['rating']}*\n"
        f"📺 Jami: *{anime['total_episodes']}* qism\n"
        f"🎭 Janr: {anime['genre'] or 'Nomalum'}\n"
        f"📊 {status_txt}\n\n"
        f"📝 {desc}"
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
    _, ep_id, anime_id, back_page = call.data.split(":")
    ep_id, anime_id, back_page = int(ep_id), int(anime_id), int(back_page)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT e.*, a.title as anime_title, a.total_episodes
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
            "INSERT INTO watch_history (user_id,anime_id,episode_id) VALUES (?,?,?)",
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

    caption = (
        f"🎬 *{ep['anime_title']}*\n"
        f"▶️ *{ep['episode_number']}-qism* / {ep['total_episodes']}"
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
    _, anime_id, back_page = call.data.split(":")
    anime_id = int(anime_id)
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
            await db.execute("INSERT INTO favorites (user_id,anime_id) VALUES (?,?)",
                             (call.from_user.id, anime_id))
            msg = "❤️ Sevimliga qo'shildi!"
        await db.commit()
    await call.answer(msg, show_alert=True)
    # Sahifani yangilash
    call.data = f"anime:{anime_id}:{back_page}"
    await cb_anime(call)

@dp.message(Command("favorites"))
async def cmd_favs(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT a.id,a.title,a.total_episodes
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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT a.id,a.title,e.episode_number
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
    q = message.text.replace("/search", "").strip()
    if not q:
        await message.answer("🔍 Misol: /search Naruto")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id,title,total_episodes FROM animes WHERE title LIKE ? ORDER BY title LIMIT 10",
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

# ══════════════════════════════════════════
# ⚙️ ADMIN
# ══════════════════════════════════════════

@dp.message(Command("addanime"))
async def adm_addanime(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(AddAnime.title)
    await message.answer("➕ *Yangi anime*\n\nNomini kiriting:", parse_mode="Markdown")

@dp.message(AddAnime.title)
async def adm_an_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddAnime.description)
    await message.answer("📝 Tavsif (yoki /skip):")

@dp.message(AddAnime.description)
async def adm_an_desc(message: Message, state: FSMContext):
    await state.update_data(description="" if message.text=="/skip" else message.text)
    await state.set_state(AddAnime.genre)
    await message.answer("🎭 Janr (masalan: Action, Comedy) yoki /skip:")

@dp.message(AddAnime.genre)
async def adm_an_genre(message: Message, state: FSMContext):
    await state.update_data(genre="" if message.text=="/skip" else message.text)
    await state.set_state(AddAnime.rating)
    await message.answer("⭐ Reyting 0-10 (yoki /skip):")

@dp.message(AddAnime.rating)
async def adm_an_rating(message: Message, state: FSMContext):
    try:
        r = 0.0 if message.text=="/skip" else float(message.text)
    except:
        await message.answer("❌ Raqam kiriting!"); return
    await state.update_data(rating=r)
    await state.set_state(AddAnime.total_episodes)
    await message.answer("📺 Jami qismlar soni:")

@dp.message(AddAnime.total_episodes)
async def adm_an_eps(message: Message, state: FSMContext):
    try:
        t = int(message.text)
    except:
        await message.answer("❌ Butun son kiriting!"); return
    await state.update_data(total_episodes=t)
    await state.set_state(AddAnime.cover)
    await message.answer("🖼 Cover rasm yuboring (yoki /skip):")

@dp.message(AddAnime.cover)
async def adm_an_cover(message: Message, state: FSMContext):
    cover_id = None
    if message.photo:
        cover_id = message.photo[-1].file_id
    elif message.text != "/skip":
        await message.answer("🖼 Rasm yuboring yoki /skip!"); return

    d = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO animes (title,description,genre,rating,total_episodes,cover_file_id)
            VALUES (?,?,?,?,?,?)
        """, (d["title"],d["description"],d["genre"],d["rating"],d["total_episodes"],cover_id))
        anime_id = cur.lastrowid
        await db.commit()

    await state.clear()
    await message.answer(
        f"✅ *{d['title']}* qo'shildi!\n🆔 ID: `{anime_id}`\n\nEpizod yuklash: /addepisode",
        parse_mode="Markdown"
    )

@dp.message(Command("addepisode"))
async def adm_addep(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(AddEpisode.anime_id)
    await message.answer("📺 Anime ID sini kiriting:\n(/list dan topishingiz mumkin)")

@dp.message(AddEpisode.anime_id)
async def adm_ep_id(message: Message, state: FSMContext):
    try:
        aid = int(message.text)
    except:
        await message.answer("❌ Raqam kiriting!"); return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id,title FROM animes WHERE id=?", (aid,)) as cur:
            anime = await cur.fetchone()
    if not anime:
        await message.answer(f"❌ ID={aid} topilmadi!"); return
    await state.update_data(anime_id=aid)
    await state.set_state(AddEpisode.episode_number)
    await message.answer(f"✅ *{anime['title']}*\n\nQism raqamini kiriting:", parse_mode="Markdown")

@dp.message(AddEpisode.episode_number)
async def adm_ep_num(message: Message, state: FSMContext):
    try:
        n = int(message.text)
    except:
        await message.answer("❌ Raqam kiriting!"); return
    await state.update_data(episode_number=n)
    await state.set_state(AddEpisode.video)
    await message.answer(f"▶️ *{n}-qism* videosini yuboring:", parse_mode="Markdown")

@dp.message(AddEpisode.video, F.video)
async def adm_ep_video(message: Message, state: FSMContext):
    d = await state.get_data()
    fid = message.video.file_id
    msg = await message.answer("⏳ Saqlanmoqda...")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO episodes (anime_id,episode_number,video_file_id)
            VALUES (?,?,?)
            ON CONFLICT(anime_id,episode_number) DO UPDATE SET video_file_id=excluded.video_file_id
        """, (d["anime_id"], d["episode_number"], fid))
        await db.commit()
    await state.clear()
    await msg.edit_text(
        f"✅ *{d['episode_number']}-qism* saqlandi!\n\nYana yuklash: /addepisode",
        parse_mode="Markdown"
    )

@dp.message(AddEpisode.video)
async def adm_ep_wrong(message: Message):
    await message.answer("❌ Video yuboring!")

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

# ── Main ─────────────────────────────────────────
async def main():
    await init_db()
    print("✅ Bot ishga tushdi!")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
