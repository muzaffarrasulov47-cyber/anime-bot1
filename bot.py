import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import asyncpg
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
DB_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PAGE_SIZE = 10  # Bir sahifada nechta anime

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ═══════════════════════════════════════════
# FSM States (Admin uchun)
# ═══════════════════════════════════════════
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

# ═══════════════════════════════════════════
# DB ulanish pool
# ═══════════════════════════════════════════
pool = None

async def create_pool():
    global pool
    pool = await asyncpg.create_pool(DB_URL)

async def get_pool():
    return pool

# ═══════════════════════════════════════════
# DB jadvallarini yaratish
# ═══════════════════════════════════════════
async def init_db():
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                joined_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS animes (
                id SERIAL PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                genre VARCHAR(255),
                rating FLOAT DEFAULT 0,
                cover_file_id TEXT,
                total_episodes INT DEFAULT 0,
                status VARCHAR(50) DEFAULT 'ongoing',
                created_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS episodes (
                id SERIAL PRIMARY KEY,
                anime_id INT REFERENCES animes(id) ON DELETE CASCADE,
                episode_number INT NOT NULL,
                video_file_id TEXT NOT NULL,
                title VARCHAR(255),
                UNIQUE(anime_id, episode_number)
            );

            CREATE TABLE IF NOT EXISTS favorites (
                user_id BIGINT REFERENCES users(id),
                anime_id INT REFERENCES animes(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, anime_id)
            );

            CREATE TABLE IF NOT EXISTS watch_history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(id),
                anime_id INT REFERENCES animes(id) ON DELETE CASCADE,
                episode_id INT REFERENCES episodes(id) ON DELETE CASCADE,
                watched_at TIMESTAMP DEFAULT NOW()
            );
        """)

# ═══════════════════════════════════════════
# YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

async def register_user(user_id: int, username: str):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (id, username)
            VALUES ($1, $2)
            ON CONFLICT (id) DO UPDATE SET username = $2
        """, user_id, username)

# ═══════════════════════════════════════════
# /start
# ═══════════════════════════════════════════
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await register_user(message.from_user.id, message.from_user.username or "")

    text = (
        "🎌 *Anime Bot ga xush kelibsiz!*\n\n"
        "📋 /list — Barcha animalar\n"
        "🔍 /search — Anime qidirish\n"
        "❤️ /favorites — Sevimlilarim\n"
        "🕐 /history — Ko'rish tarixim\n"
    )
    if is_admin(message.from_user.id):
        text += "\n⚙️ *Admin:*\n/addanime — Anime qo'shish\n/delanime — Anime o'chirish"

    await message.answer(text, parse_mode="Markdown")

# ═══════════════════════════════════════════
# /list — Anime ro'yxati (pagination)
# ═══════════════════════════════════════════
@dp.message(Command("list"))
async def cmd_list(message: Message):
    await show_anime_list(message, page=0)

async def show_anime_list(event, page: int):
    offset = page * PAGE_SIZE
    async with pool.acquire() as conn:
        animes = await conn.fetch("""
            SELECT id, title, total_episodes, rating, status
            FROM animes
            ORDER BY title
            LIMIT $1 OFFSET $2
        """, PAGE_SIZE, offset)

        total = await conn.fetchval("SELECT COUNT(*) FROM animes")

    if not animes:
        text = "😔 Hozircha anime yo'q"
        if isinstance(event, Message):
            await event.answer(text)
        else:
            await event.message.edit_text(text)
        return

    builder = InlineKeyboardBuilder()
    for a in animes:
        status_icon = "🟢" if a['status'] == 'ongoing' else "✅"
        builder.button(
            text=f"🎬 {a['title']} [{a['total_episodes']} qism] {status_icon}",
            callback_data=f"anime_{a['id']}_0"
        )
    builder.adjust(1)

    # Pagination tugmalari
    nav_buttons = []
    if page > 0:
        nav_buttons.append(("⬅️ Oldingi", f"page_{page-1}"))
    if offset + PAGE_SIZE < total:
        nav_buttons.append(("Keyingi ➡️", f"page_{page+1}"))

    for btn_text, btn_data in nav_buttons:
        builder.button(text=btn_text, callback_data=btn_data)

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    header = f"📋 *Animalar* ({page+1}/{total_pages} sahifa, jami: {total} ta)\n"

    if isinstance(event, Message):
        await event.answer(header, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await event.message.edit_text(header, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("page_"))
async def pagination_handler(call: CallbackQuery):
    page = int(call.data.split("_")[1])
    await show_anime_list(call, page)
    await call.answer()

# ═══════════════════════════════════════════
# Anime detail sahifasi
# ═══════════════════════════════════════════
@dp.callback_query(F.data.startswith("anime_"))
async def anime_detail(call: CallbackQuery):
    parts = call.data.split("_")
    anime_id = int(parts[1])
    back_page = int(parts[2]) if len(parts) > 2 else 0

    async with pool.acquire() as conn:
        anime = await conn.fetchrow("SELECT * FROM animes WHERE id = $1", anime_id)
        episodes = await conn.fetch("""
            SELECT id, episode_number, title
            FROM episodes
            WHERE anime_id = $1
            ORDER BY episode_number
        """, anime_id)
        is_fav = await conn.fetchval("""
            SELECT 1 FROM favorites WHERE user_id = $1 AND anime_id = $2
        """, call.from_user.id, anime_id)

    if not anime:
        await call.answer("Anime topilmadi!", show_alert=True)
        return

    # Qismlar tugmalari (3 tadan qator)
    builder = InlineKeyboardBuilder()
    for ep in episodes:
        ep_title = ep['title'] or f"{ep['episode_number']}-qism"
        builder.button(
            text=f"▶️ {ep['episode_number']}-qism",
            callback_data=f"ep_{ep['id']}_{anime_id}_{back_page}"
        )
    builder.adjust(3)

    # Sevimli + Orqaga
    fav_text = "💔 Sevimlilardan olib tashlash" if is_fav else "❤️ Sevimliga qo'shish"
    builder.button(text=fav_text, callback_data=f"fav_{anime_id}_{back_page}")
    builder.button(text="🔙 Ro'yxatga qaytish", callback_data=f"page_{back_page}")
    builder.adjust(3, 1, 1)

    status_text = "🟢 Davom etmoqda" if anime['status'] == 'ongoing' else "✅ Tugallangan"
    text = (
        f"🎬 *{anime['title']}*\n\n"
        f"⭐ Reyting: *{anime['rating']}*\n"
        f"📺 Jami qismlar: *{anime['total_episodes']}*\n"
        f"🎭 Janr: {anime['genre'] or 'Noma\'lum'}\n"
        f"📊 Status: {status_text}\n\n"
        f"📝 {(anime['description'] or '')[:400]}"
    )

    if anime['cover_file_id']:
        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer_photo(
            photo=anime['cover_file_id'],
            caption=text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    else:
        await call.message.edit_text(
            text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    await call.answer()

# ═══════════════════════════════════════════
# Epizod yuborish
# ═══════════════════════════════════════════
@dp.callback_query(F.data.startswith("ep_"))
async def send_episode(call: CallbackQuery):
    parts = call.data.split("_")
    ep_id = int(parts[1])
    anime_id = int(parts[2])
    back_page = int(parts[3]) if len(parts) > 3 else 0

    async with pool.acquire() as conn:
        ep = await conn.fetchrow("""
            SELECT e.*, a.title as anime_title, a.total_episodes
            FROM episodes e
            JOIN animes a ON e.anime_id = a.id
            WHERE e.id = $1
        """, ep_id)

        if not ep:
            await call.answer("Epizod topilmadi!", show_alert=True)
            return

        # Tarixga yozish
        await conn.execute("""
            INSERT INTO watch_history (user_id, anime_id, episode_id)
            VALUES ($1, $2, $3)
        """, call.from_user.id, anime_id, ep_id)

        # Oldingi va keyingi epizodlar
        prev_ep = await conn.fetchrow("""
            SELECT id FROM episodes
            WHERE anime_id = $1 AND episode_number = $2
        """, anime_id, ep['episode_number'] - 1)

        next_ep = await conn.fetchrow("""
            SELECT id FROM episodes
            WHERE anime_id = $1 AND episode_number = $2
        """, anime_id, ep['episode_number'] + 1)

    # Navigation tugmalari
    builder = InlineKeyboardBuilder()
    if prev_ep:
        builder.button(text="⬅️ Oldingi qism", callback_data=f"ep_{prev_ep['id']}_{anime_id}_{back_page}")
    if next_ep:
        builder.button(text="Keyingi qism ➡️", callback_data=f"ep_{next_ep['id']}_{anime_id}_{back_page}")
    builder.button(text="🔙 Anime sahifasiga", callback_data=f"anime_{anime_id}_{back_page}")
    builder.adjust(2, 1)

    caption = (
        f"🎬 *{ep['anime_title']}*\n"
        f"▶️ *{ep['episode_number']}-qism*"
        f" / {ep['total_episodes']}\n\n"
        f"⬅️ Oldingi | Keyingi ➡️"
    )

    await call.message.answer_video(
        video=ep['video_file_id'],
        caption=caption,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await call.answer()

# ═══════════════════════════════════════════
# Sevimlilar
# ═══════════════════════════════════════════
@dp.callback_query(F.data.startswith("fav_"))
async def toggle_favorite(call: CallbackQuery):
    parts = call.data.split("_")
    anime_id = int(parts[1])
    back_page = int(parts[2]) if len(parts) > 2 else 0

    async with pool.acquire() as conn:
        existing = await conn.fetchval("""
            SELECT 1 FROM favorites WHERE user_id = $1 AND anime_id = $2
        """, call.from_user.id, anime_id)

        if existing:
            await conn.execute("""
                DELETE FROM favorites WHERE user_id = $1 AND anime_id = $2
            """, call.from_user.id, anime_id)
            await call.answer("💔 Sevimlilardan olib tashlandi", show_alert=True)
        else:
            await conn.execute("""
                INSERT INTO favorites (user_id, anime_id) VALUES ($1, $2)
            """, call.from_user.id, anime_id)
            await call.answer("❤️ Sevimliga qo'shildi!", show_alert=True)

    # Sahifani yangilash
    await anime_detail(call)

@dp.message(Command("favorites"))
async def cmd_favorites(message: Message):
    async with pool.acquire() as conn:
        animes = await conn.fetch("""
            SELECT a.id, a.title, a.total_episodes
            FROM favorites f
            JOIN animes a ON f.anime_id = a.id
            WHERE f.user_id = $1
            ORDER BY a.title
        """, message.from_user.id)

    if not animes:
        await message.answer("❤️ Sevimlilar ro'yxati bo'sh\n\n/list dan anime qo'shing!")
        return

    builder = InlineKeyboardBuilder()
    for a in animes:
        builder.button(
            text=f"🎬 {a['title']} [{a['total_episodes']} qism]",
            callback_data=f"anime_{a['id']}_0"
        )
    builder.adjust(1)

    await message.answer(
        f"❤️ *Sevimli animalarim* ({len(animes)} ta):",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════
# Ko'rish tarixi
# ═══════════════════════════════════════════
@dp.message(Command("history"))
async def cmd_history(message: Message):
    async with pool.acquire() as conn:
        history = await conn.fetch("""
            SELECT DISTINCT ON (a.id) a.id, a.title, e.episode_number, wh.watched_at
            FROM watch_history wh
            JOIN animes a ON wh.anime_id = a.id
            JOIN episodes e ON wh.episode_id = e.id
            WHERE wh.user_id = $1
            ORDER BY a.id, wh.watched_at DESC
            LIMIT 10
        """, message.from_user.id)

    if not history:
        await message.answer("🕐 Ko'rish tarixi bo'sh")
        return

    builder = InlineKeyboardBuilder()
    for h in history:
        builder.button(
            text=f"🎬 {h['title']} — {h['episode_number']}-qism",
            callback_data=f"anime_{h['id']}_0"
        )
    builder.adjust(1)

    await message.answer(
        "🕐 *Oxirgi ko'rganlarim:*",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════
# Qidirish
# ═══════════════════════════════════════════
@dp.message(Command("search"))
async def cmd_search(message: Message):
    query = message.text.replace("/search", "").strip()
    if not query:
        await message.answer("🔍 Misol: /search Naruto")
        return

    async with pool.acquire() as conn:
        animes = await conn.fetch("""
            SELECT id, title, total_episodes
            FROM animes
            WHERE title ILIKE $1
            ORDER BY title
            LIMIT 10
        """, f"%{query}%")

    if not animes:
        await message.answer(f"😔 *{query}* bo'yicha hech narsa topilmadi")
        return

    builder = InlineKeyboardBuilder()
    for a in animes:
        builder.button(
            text=f"🎬 {a['title']} [{a['total_episodes']} qism]",
            callback_data=f"anime_{a['id']}_0"
        )
    builder.adjust(1)

    await message.answer(
        f"🔍 *'{query}'* bo'yicha natijalar ({len(animes)} ta):",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════════════
# ⚙️ ADMIN — Anime qo'shish (bosqichma-bosqich FSM)
# ═══════════════════════════════════════════════════════
@dp.message(Command("addanime"))
async def admin_add_anime(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AddAnime.title)
    await message.answer("➕ *Yangi anime qo'shish*\n\nAnime nomini kiriting:", parse_mode="Markdown")

@dp.message(AddAnime.title)
async def add_anime_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddAnime.description)
    await message.answer("📝 Tavsif kiriting (yoki /skip):")

@dp.message(AddAnime.description)
async def add_anime_desc(message: Message, state: FSMContext):
    desc = "" if message.text == "/skip" else message.text
    await state.update_data(description=desc)
    await state.set_state(AddAnime.genre)
    await message.answer("🎭 Janr kiriting (masalan: Action, Comedy) yoki /skip:")

@dp.message(AddAnime.genre)
async def add_anime_genre(message: Message, state: FSMContext):
    genre = "" if message.text == "/skip" else message.text
    await state.update_data(genre=genre)
    await state.set_state(AddAnime.rating)
    await message.answer("⭐ Reyting kiriting (0-10) yoki /skip:")

@dp.message(AddAnime.rating)
async def add_anime_rating(message: Message, state: FSMContext):
    try:
        rating = 0.0 if message.text == "/skip" else float(message.text)
    except:
        await message.answer("❌ Raqam kiriting! (masalan: 8.5)")
        return
    await state.update_data(rating=rating)
    await state.set_state(AddAnime.total_episodes)
    await message.answer("📺 Jami epizodlar sonini kiriting:")

@dp.message(AddAnime.total_episodes)
async def add_anime_episodes(message: Message, state: FSMContext):
    try:
        total = int(message.text)
    except:
        await message.answer("❌ Butun son kiriting!")
        return
    await state.update_data(total_episodes=total)
    await state.set_state(AddAnime.cover)
    await message.answer("🖼 Cover rasmini yuboring (yoki /skip):")

@dp.message(AddAnime.cover)
async def add_anime_cover(message: Message, state: FSMContext):
    cover_id = None
    if message.photo:
        cover_id = message.photo[-1].file_id
    elif message.text != "/skip":
        await message.answer("🖼 Rasm yuboring yoki /skip yozing!")
        return

    data = await state.get_data()
    async with pool.acquire() as conn:
        anime_id = await conn.fetchval("""
            INSERT INTO animes (title, description, genre, rating, total_episodes, cover_file_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, data['title'], data['description'], data['genre'],
            data['rating'], data['total_episodes'], cover_id)

    await state.clear()
    await message.answer(
        f"✅ *{data['title']}* qo'shildi!\n"
        f"🆔 Anime ID: `{anime_id}`\n\n"
        f"Endi epizod yuklash uchun:\n"
        f"/addepisode",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════════════
# ⚙️ ADMIN — Epizod qo'shish (FSM)
# ═══════════════════════════════════════════════════════
@dp.message(Command("addepisode"))
async def admin_add_episode(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AddEpisode.anime_id)
    await message.answer(
        "📺 *Epizod qo'shish*\n\n"
        "Anime ID sini kiriting:\n"
        "(Anime ID ni /list dan topishingiz mumkin)",
        parse_mode="Markdown"
    )

@dp.message(AddEpisode.anime_id)
async def add_ep_anime_id(message: Message, state: FSMContext):
    try:
        anime_id = int(message.text)
    except:
        await message.answer("❌ Raqam kiriting!")
        return

    async with pool.acquire() as conn:
        anime = await conn.fetchrow("SELECT id, title FROM animes WHERE id = $1", anime_id)

    if not anime:
        await message.answer(f"❌ ID={anime_id} anime topilmadi!")
        return

    await state.update_data(anime_id=anime_id)
    await state.set_state(AddEpisode.episode_number)
    await message.answer(f"✅ *{anime['title']}*\n\nQism raqamini kiriting:", parse_mode="Markdown")

@dp.message(AddEpisode.episode_number)
async def add_ep_number(message: Message, state: FSMContext):
    try:
        ep_num = int(message.text)
    except:
        await message.answer("❌ Raqam kiriting!")
        return

    await state.update_data(episode_number=ep_num)
    await state.set_state(AddEpisode.video)
    await message.answer(f"▶️ *{ep_num}-qism* videosini yuboring:", parse_mode="Markdown")

@dp.message(AddEpisode.video, F.video)
async def add_ep_video(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = message.video.file_id

    loading = await message.answer("⏳ Saqlanmoqda...")

    async with pool.acquire() as conn:
        try:
            await conn.execute("""
                INSERT INTO episodes (anime_id, episode_number, video_file_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (anime_id, episode_number)
                DO UPDATE SET video_file_id = $3
            """, data['anime_id'], data['episode_number'], file_id)
        except Exception as e:
            await loading.edit_text(f"❌ Xato: {e}")
            return

    await state.clear()
    await loading.edit_text(
        f"✅ *{data['episode_number']}-qism* saqlandi!\n\n"
        f"Yana epizod qo'shish: /addepisode",
        parse_mode="Markdown"
    )

@dp.message(AddEpisode.video)
async def add_ep_video_wrong(message: Message):
    await message.answer("❌ Video yuboring (fayl emas, video format)!")

# ═══════════════════════════════════════════════════════
# ⚙️ ADMIN — Anime o'chirish
# ═══════════════════════════════════════════════════════
@dp.message(Command("delanime"))
async def admin_del_anime(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Format: /delanime <anime_id>")
        return

    try:
        anime_id = int(parts[1])
    except:
        await message.answer("❌ Raqam kiriting!")
        return

    async with pool.acquire() as conn:
        anime = await conn.fetchrow("SELECT title FROM animes WHERE id = $1", anime_id)
        if not anime:
            await message.answer(f"❌ ID={anime_id} anime topilmadi!")
            return
        await conn.execute("DELETE FROM animes WHERE id = $1", anime_id)

    await message.answer(f"✅ *{anime['title']}* o'chirildi!", parse_mode="Markdown")

# ═══════════════════════════════════════════════════════
# ⚙️ ADMIN — Statistika
# ═══════════════════════════════════════════════════════
@dp.message(Command("stats"))
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with pool.acquire() as conn:
        users = await conn.fetchval("SELECT COUNT(*) FROM users")
        animes = await conn.fetchval("SELECT COUNT(*) FROM animes")
        episodes = await conn.fetchval("SELECT COUNT(*) FROM episodes")
        views = await conn.fetchval("SELECT COUNT(*) FROM watch_history")

    await message.answer(
        f"📊 *Bot statistikasi:*\n\n"
        f"👥 Foydalanuvchilar: *{users}*\n"
        f"🎬 Animalar: *{animes}*\n"
        f"▶️ Epizodlar: *{episodes}*\n"
        f"👁 Jami ko'rishlar: *{views}*",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════
async def main():
    await create_pool()
    await init_db()
    print("✅ Bot ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
