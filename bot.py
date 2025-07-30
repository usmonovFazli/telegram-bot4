import logging
import os
import openpyxl
from dotenv import load_dotenv
load_dotenv()
from telegram import Update, ReplyKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)



import io
from datetime import datetime

from database import (
    init_db,
    add_or_update_channel,
    get_channels,
    increment_video_count,
)

TOKEN = os.getenv("BOT_TOKEN", "7978985604:AAEuHxd3X-v2UNW3Twygfbf4VEKme2efGmo")
logging.basicConfig(level=logging.INFO)

# Главное меню
MAIN_MENU = ReplyKeyboardMarkup(
    [["🎥 Отправить видео", "📊 Статистика"], ["📥 Экспорт Excel"]],
    resize_keyboard=True
)

# Старт
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Выберите действие:", reply_markup=MAIN_MENU)

# Запрос на отправку видео
async def prompt_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📤 Пожалуйста, отправьте видео, которое хотите разослать.")

# Обработка и рассылка видео
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.video:
        return

    video = update.message.video
    chats = get_channels()

    count = 0
    for chat_id, *_ in chats:
        try:
            await context.bot.send_video(chat_id=chat_id, video=video.file_id, caption="📹 Новое видео:")
            increment_video_count(chat_id)
            count += 1
        except Exception as e:
            logging.warning(f"❌ Не удалось отправить в {chat_id}: {e}")

    await update.message.reply_text(f"✅ Видео отправлено в {count} чатов.")

# Обработка добавления бота в канал
# Хендлер обновления чатов (бот добавлен в группу/канал)
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

        add_or_update_channel(chat.id, chat.title or "Без названия", members, chat_type, link)
        logging.info(f"Бот добавлен в {chat.title} ({chat.id}), тип: {chat_type}, ссылка: {link}")

# Статистика
async def show_stats(update, context):
    chats = get_channels()
    if not chats:
        await update.message.reply_text("⚠️ Нет подключённых каналов/групп.")
        return

    # Получаем аргумент, если есть
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

# экспорт в экзель
async def export_excel(update, context):
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
        if isinstance(date_added, datetime):
            date_str = date_added.strftime('%Y-%m-%d %H:%M')
        else:
            date_str = str(date_added)
        ws.append([id_, title, members, videos, date_str, chat_type, link])

    file_path = "channels_export.xlsx"
    wb.save(file_path)

    # Отправка файла с правильным именем
    with open(file_path, "rb") as f:
        await update.message.reply_document(InputFile(f, filename="channels_export.xlsx"))

    os.remove(file_path)
# Запуск бота
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.Regex("^🎥 Отправить видео$"), prompt_video))
    app.add_handler(MessageHandler(filters.Regex("^📊 Статистика$"), show_stats))
    app.add_handler(MessageHandler(filters.Regex("^📥 Экспорт Excel$"), export_excel))
    app.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, handle_video))

    logging.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
