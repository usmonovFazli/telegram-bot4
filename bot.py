import logging
import os
import openpyxl
from dotenv import load_dotenv
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

from database import (
    init_db,
    add_or_update_channel,
    get_channels,
    increment_video_count,
)

# Загрузка .env переменных
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN" , "7978985604:AAEuHxd3X-v2UNW3Twygfbf4VEKme2efGmo")
AUTHORIZED_PASSWORD = os.getenv("BOT_PASSWORD", "@12321231’m’@")

# Список авторизованных пользователей
authorized_users = set()

# Главное меню
MAIN_MENU = ReplyKeyboardMarkup(
    [["🎥 Отправить видео", "📊 Статистика"], ["📥 Экспорт Excel"]],
    resize_keyboard=True
)

logging.basicConfig(level=logging.INFO)

# Старт
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in authorized_users:
        await update.message.reply_text("✅ Добро пожаловать снова!", reply_markup=MAIN_MENU)
    else:
        await update.message.reply_text("🔐 Введите пароль для доступа:")
        context.user_data["awaiting_password"] = True

# Проверка пароля
async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_password"):
        return

    password = update.message.text.strip()
    user_id = update.effective_user.id

    if password == AUTHORIZED_PASSWORD:
        authorized_users.add(user_id)
        context.user_data["awaiting_password"] = False
        await update.message.reply_text("✅ Доступ разрешён!", reply_markup=MAIN_MENU)
    else:
        await update.message.reply_text("❌ Неверный пароль. Попробуйте снова:")

# Проверка доступа
def check_access(user_id):
    return user_id in authorized_users

# Запрос на отправку видео
async def prompt_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.effective_user.id):
        await update.message.reply_text("⛔ У вас нет доступа. Введите /start и пароль.")
        return
    await update.message.reply_text("📤 Пожалуйста, отправьте видео, которое хотите разослать.")

# Обработка видео и отправка
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.effective_user.id):
        await update.message.reply_text("⛔ У вас нет доступа.")
        return

    if not update.message or not update.message.video:
        return

    video = update.message.video
    caption = update.message.caption or "📹 Новое видео:"
    chats = get_channels()

    count = 0
    for chat_id, *_ in chats:
        try:
            await context.bot.send_video(chat_id=chat_id, video=video.file_id, caption=caption)
            increment_video_count(chat_id)
            count += 1
        except Exception as e:
            logging.warning(f"❌ Не удалось отправить в {chat_id}: {e}")

    await update.message.reply_text(f"✅ Видео отправлено в {count} чатов.")

# Добавление в чат
async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.my_chat_member.chat
    new_status = update.my_chat_member.new_chat_member.status

    if new_status in ["member", "administrator"]:
        try:
            members = await context.bot.get_chat_member_count(chat.id)
        except Exception as e:
            members = -1
            logging.warning(f"Не удалось получить кол-во участников: {e}")

        chat_type = chat.type or "unknown"
        link = f"https://t.me/{chat.username}" if chat.username else ""
        title = chat.title or "Без названия"

        add_or_update_channel(chat.id, title, members, chat_type, link)
        logging.info(f"✅ Добавлен: {title} ({chat_type}) — {chat.id}")

# Статистика
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.effective_user.id):
        await update.message.reply_text("⛔ У вас нет доступа.")
        return

    chats = get_channels()
    if not chats:
        await update.message.reply_text("⚠️ Нет подключённых каналов/групп.")
        return

    filter_type = context.args[0].lower() if context.args else "all"
    valid_types = ["group", "channel", "all"]

    if filter_type not in valid_types:
        await update.message.reply_text("❌ Неверный фильтр. Используй /stats [group|channel|all]")
        return

    filtered = []
    for _, title, members, videos, _, chat_type, _ in chats:
        if filter_type == "all" or chat_type == filter_type:
            filtered.append((title, members, videos, chat_type))

    if not filtered:
        await update.message.reply_text(f"ℹ️ Нет данных для фильтра: {filter_type}")
        return

    text = f"📊 Статистика ({filter_type}):\n\n"
    for title, members, videos, chat_type in filtered:
        text += f"• {title} ({chat_type}) — 👥 {members} участников, 📹 {videos} видео\n"

    await update.message.reply_text(text)

# Экспорт Excel
async def export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.effective_user.id):
        await update.message.reply_text("⛔ У вас нет доступа.")
        return

    chats = get_channels()
    if not chats:
        await update.message.reply_text("⚠️ Нет данных для экспорта.")
        return

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Каналы и группы"
    ws.append(["ID", "Название", "Участники", "Отправлено видео", "Дата добавления", "Тип", "Ссылка"])

    for row in chats:
        id_, title, members, videos, date_added, chat_type, link = row
        date_str = date_added.strftime('%Y-%m-%d %H:%M') if isinstance(date_added, datetime) else str(date_added)
        ws.append([id_, title, members, videos, date_str, chat_type, link])

    file_path = "channels_export.xlsx"
    wb.save(file_path)

    with open(file_path, "rb") as f:
        await update.message.reply_document(InputFile(f, filename="channels_export.xlsx"))

    os.remove(file_path)

# Главная
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.Regex("^🎥 Отправить видео$"), prompt_video))
    app.add_handler(MessageHandler(filters.Regex("^📊 Статистика$"), show_stats))
    app.add_handler(MessageHandler(filters.Regex("^📥 Экспорт Excel$"), export_excel))
    app.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, handle_video))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_password))

    logging.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
