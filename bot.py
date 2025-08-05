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

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN", "your_default_token")
AUTHORIZED_PASSWORD = os.getenv("BOT_PASSWORD")
LEAVE_PASSWORD = "1234"

authorized_users = set()
leave_confirmations = {}  # user_id: stage

MAIN_MENU = ReplyKeyboardMarkup(
    [["🎥 Отправить видео", "📊 Статистика"], ["📥 Экспорт Excel", "🚪 Покинуть чаты"]],
    resize_keyboard=True
)

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in authorized_users:
        await update.message.reply_text("✅ Добро пожаловать снова!", reply_markup=MAIN_MENU)
    else:
        await update.message.reply_text("🔐 Введите пароль для доступа:")
        context.user_data["awaiting_password"] = True

async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_password"):
        return

    password = update.message.text.strip()
    user_id = update.effective_user.id
    logging.info(f"Проверка пароля от пользователя {user_id}: {password}")

    if password == AUTHORIZED_PASSWORD:
        authorized_users.add(user_id)
        context.user_data["awaiting_password"] = False
        await update.message.reply_text("✅ Доступ разрешён!", reply_markup=MAIN_MENU)
    else:
        await update.message.reply_text("❌ Неверный пароль. Попробуйте снова:")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.user_data.get("awaiting_password"):
        await handle_password(update, context)
    elif leave_confirmations.get(user_id) == "password":
        await handle_leave_password(update, context)


def check_access(user_id):
    return user_id in authorized_users

async def prompt_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.effective_user.id):
        await update.message.reply_text("⛔️ У вас нет доступа. Введите /start и пароль.")
        return
    await update.message.reply_text("📤 Пожалуйста, отправьте видео, которое хотите разослать.")

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

async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.my_chat_member.chat
    new_status = update.my_chat_member.new_chat_member.status

    try:
        members = await context.bot.get_chat_member_count(chat.id)
    except Exception as e:
        members = -1
        logging.warning(f"Не удалось получить количество участников: {e}")

    if members != -1 and members < 50:
        try:
            await context.bot.leave_chat(chat.id)
            logging.info(f"🚪 Покинул чат {chat.title} — участников меньше 50 ({members})")
        except Exception as e:
            logging.warning(f"❌ Не удалось выйти из {chat.title}: {e}")
        return

    link = f"https://t.me/{chat.username}" if chat.username else ""
    title = chat.title or "Без названия"

    try:
        add_or_update_channel(chat.id, title, members, new_status, link)
        logging.info(f"✅ Чат зарегистрирован или обновлён: {title} ({new_status}) — {chat.id}")
    except Exception as e:
        logging.error(f"❌ Ошибка при добавлении/обновлении чата: {e}")

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.effective_user.id):
        await update.message.reply_text("⛔️ У вас нет доступа.")
        return

    chats = get_channels()
    total = len(chats)
    channels = sum(1 for c in chats if c[5] == "channel")
    groups = sum(1 for c in chats if c[5] == "group")
    supergroups = sum(1 for c in chats if c[5] == "supergroup")
    active = sum(1 for c in chats if c[2] > 0)
    inactive = total - active

    text = (
        f"📊 Общая статистика:\n"
        f"• Каналов: {channels}\n"
        f"• Групп: {groups}\n"
        f"• Супергрупп: {supergroups}\n"
        f"• Активных: {active}\n"
        f"• Неактивных: {inactive}"
    )
    await update.message.reply_text(text)

async def export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.effective_user.id):
        await update.message.reply_text("⛔️ У вас нет доступа.")
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

async def initiate_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_access(user_id):
        await update.message.reply_text("⛔️ У вас нет доступа.")
        return

    leave_confirmations[user_id] = "confirm"
    markup = ReplyKeyboardMarkup([["✅ Да", "❌ Нет"]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("⚠️ Вы уверены, что хотите выйти из всех чатов?", reply_markup=markup)

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if leave_confirmations.get(user_id) != "confirm":
        return

    if text == "✅ Да":
        leave_confirmations[user_id] = "password"
        await update.message.reply_text("🔐 Введите пароль для подтверждения выхода:")
    else:
        leave_confirmations.pop(user_id, None)
        await update.message.reply_text("❎ Отменено.", reply_markup=MAIN_MENU)

async def handle_leave_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if leave_confirmations.get(user_id) != "password":
        return

    if text == LEAVE_PASSWORD:
        chats = get_channels()
        left = 0
        for chat_id, *_ in chats:
            try:
                await context.bot.leave_chat(chat_id)
                left += 1
            except Exception as e:
                logging.warning(f"❌ Не смог выйти из {chat_id}: {e}")

        leave_confirmations.pop(user_id, None)
        await update.message.reply_text(f"🚪 Вышел из {left} чатов.", reply_markup=MAIN_MENU)
    else:
        await update.message.reply_text("❌ Неверный пароль. Операция отменена.")
        leave_confirmations.pop(user_id, None)

def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.Regex("^🎥 Отправить видео$"), prompt_video))
    app.add_handler(MessageHandler(filters.Regex("^📊 Статистика$"), show_stats))
    app.add_handler(MessageHandler(filters.Regex("^📥 Экспорт Excel$"), export_excel))
    app.add_handler(MessageHandler(filters.Regex("^🚪 Покинуть чаты$"), initiate_leave))
    app.add_handler(MessageHandler(filters.Regex("^(✅ Да|❌ Нет)$"), handle_confirmation))
    app.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, handle_video))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_text))

    logging.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
