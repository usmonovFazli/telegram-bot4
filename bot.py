import logging
import os
import openpyxl
from openpyxl.styles import PatternFill
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
    update_channel_status,
    get_channels,
    increment_video_count,
)

# Загрузка переменных среды
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "")
AUTHORIZED_PASSWORD = os.getenv("BOT_PASSWORD", "")

# Авторизованные пользователи
authorized_users = set()

# Главное меню
MAIN_MENU = ReplyKeyboardMarkup(
    [["🎥 Отправить видео", "📊 Статистика"], ["📥 Экспорт Excel"]],
    resize_keyboard=True
)

logging.basicConfig(level=logging.INFO)

# /start
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

# Кнопка: отправить видео
async def prompt_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.effective_user.id):
        await update.message.reply_text("⛔️ У вас нет доступа. Введите /start и пароль.")
        return
    await update.message.reply_text("📤 Пожалуйста, отправьте видео, которое хотите разослать.")

# Обработка видео
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.effective_user.id):
        await update.message.reply_text("⛔️ У вас нет доступа.")
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

# Обработка входа/выхода из чатов
async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.my_chat_member.chat
    new_status = update.my_chat_member.new_chat_member.status

    try:
        members = await context.bot.get_chat_member_count(chat.id)
    except Exception as e:
        members = -1
        logging.warning(f"Не удалось получить количество участников: {e}")

    link = f"https://t.me/{chat.username}" if chat.username else ""
    title = chat.title or "Без названия"

    try:
        add_or_update_channel(chat.id, title, members, new_status, link)
        logging.info(f"✅ Чат зарегистрирован или обновлён: {title} ({new_status}) — {chat.id}")
    except Exception as e:
        logging.error(f"❌ Ошибка при добавлении/обновлении чата: {e}")

# Обновление информации перед статистикой/экспортом
async def refresh_members(context: ContextTypes.DEFAULT_TYPE):
    chats = get_channels()
    for chat_id, title, _, _, _, _, link in chats:
        try:
            members = await context.bot.get_chat_member_count(chat_id)
            chat = await context.bot.get_chat(chat_id)
            name = chat.title or title
            update_channel_status(chat_id, title=name, members=members, chat_type=chat.type, link=link)
        except Exception as e:
            logging.warning(f"⚠️ Не удалось обновить {chat_id}: {e}")
            update_channel_status(chat_id, chat_type="left")

# Кнопка: 📊 Статистика
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.effective_user.id):
        await update.message.reply_text("⛔️ У вас нет доступа.")
        return

    await update.message.reply_text("♻️ Обновляю информацию о каналах...")
    await refresh_members(context)

    chats = get_channels()
    if not chats:
        await update.message.reply_text("⚠️ Нет подключённых каналов/групп.")
        return

    stats = {
        "channel": {"active": 0, "inactive": 0},
        "group": {"active": 0, "inactive": 0},
        "supergroup": {"active": 0, "inactive": 0},
    }

    for _, _, _, _, _, chat_type, _ in chats:
        if chat_type in ["left", "kicked"]:
            continue
        if chat_type in stats:
            stats[chat_type]["active"] += 1

    for _, _, _, _, _, chat_type, _ in chats:
        if chat_type in stats and chat_type not in ["left", "kicked"]:
            continue
        for t in stats:
            stats[t]["inactive"] += 0 if chat_type not in ["left", "kicked"] else 1

    text = "📊 Общая статистика:\n\n"
    for t, label in [("channel", "Каналы"), ("group", "Группы"), ("supergroup", "Супергруппы")]:
        active = stats[t]["active"]
        inactive = stats[t]["inactive"]
        total_type = active + inactive
        text += f"• {label}: {total_type} ({active} активных / {inactive} удалённых)\n"

    text += f"\nВсего чатов: {len(chats)}"
    await update.message.reply_text(text)

# Кнопка: 📥 Экспорт Excel
async def export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.effective_user.id):
        await update.message.reply_text("⛔️ У вас нет доступа.")
        return

    await update.message.reply_text("📦 Обновляю данные перед экспортом...")
    await refresh_members(context)

    chats = get_channels()
    if not chats:
        await update.message.reply_text("⚠️ Нет данных для экспорта.")
        return

    active_chats = [c for c in chats if c[5] not in ["left", "kicked"]]
    left_chats = [c for c in chats if c[5] in ["left", "kicked"]]
    sorted_chats = active_chats + left_chats

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Каналы и группы"
    ws.append(["ID", "Название", "Участники", "Отправлено видео", "Дата добавления", "Тип", "Ссылка"])

    red_fill = PatternFill(start_color="FFCCCC", end_color="FFCCCC", fill_type="solid")
    green_fill = PatternFill(start_color="CCFFCC", end_color="CCFFCC", fill_type="solid")

    for row in sorted_chats:
        id_, title, members, videos, date_added, chat_type, link = row
        date_str = date_added.strftime('%Y-%m-%d %H:%M') if isinstance(date_added, datetime) else str(date_added)
        data = [id_, title, members, videos, date_str, chat_type, link]
        ws.append(data)

        current_row = ws.max_row
        fill = red_fill if chat_type in ["left", "kicked"] else green_fill
        for col in range(1, len(data) + 1):
            ws.cell(row=current_row, column=col).fill = fill

    file_path = "channels_export.xlsx"
    wb.save(file_path)

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
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_password))

    logging.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
