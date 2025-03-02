import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from database import get_session, Player, WeeklyPlayer, History

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))

# Проверка прав администратора
async def is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID

# Команда /start_vote
async def start_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return

    session = get_session()
    try:
        # Получаем список игроков из аргументов команды
        players = context.args
        if not players:
            await update.message.reply_text("⚠️ Укажите игроков: /start_vote Игрок1 Игрок2 ...")
            return

        # Очищаем предыдущее голосование
        session.query(WeeklyPlayer).delete()
        session.query(Player).delete()

        # Добавляем новых игроков
        for name in players:
            session.add(WeeklyPlayer(name=name))
            session.add(Player(name=name, total_rating=0.0, votes=0))
        session.commit()

        # Создаем клавиатуру с кнопками
        keyboard = [
            [InlineKeyboardButton(name, callback_data=f"rate_{name}")]
            for name in players
        ]
        keyboard.append([InlineKeyboardButton("🚫 Не играл", callback_data="skip_vote")])

        await update.message.reply_text(
            "⭐ *Голосование запущено!*\nВыберите игрока для оценки:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="MarkdownV2"
        )

    except Exception as e:
        logging.error(f"Ошибка: {e}")
    finally:
        session.close()

# Обработка выбора игрока
async def handle_player_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "skip_vote":
        await query.edit_message_text("✅ Ваш голос учтен (вы не участвовали).")
        return

    _, player_name = query.data.split('_', 1)
    # Создаем клавиатуру с оценками 1-5
    keyboard = [
        [InlineKeyboardButton(str(i), callback_data=f"set_rating_{player_name}_{i}")]
        for i in range(1, 6)
    ]
    await query.edit_message_text(
        f"Оцените игрока *{player_name}* (1-5):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2"
    )

# Обработка оценки
async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, _, player_name, rating = query.data.split('_', 3)
    session = get_session()
    try:
        player = session.query(Player).filter_by(name=player_name).first()
        if player:
            player.total_rating += int(rating)
            player.votes += 1
            session.commit()
            await query.edit_message_text(f"✅ Игрок *{player_name}* получил оценку {rating}!", parse_mode="MarkdownV2")
    except Exception as e:
        logging.error(f"Ошибка: {e}")
    finally:
        session.close()

# Команда /stop_vote
async def stop_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return

    session = get_session()
    try:
        players = session.query(Player).order_by(Player.total_rating.desc()).all()
        if len(players) < 3:
            await update.message.reply_text("❌ Недостаточно данных для подсчета результатов.")
            return

        # Определяем MVP и призеров
        mvp = players[0].name
        first = players[1].name
        second = players[2].name
        third = players[3].name if len(players) >= 4 else "–"

        # Сохраняем историю
        history = History(
            mvp=mvp,
            first_place=first,
            second_place=second,
            third_place=third
        )
        session.add(history)
        session.commit()

        # Формируем ответ
        response = (
            "🏆 *Итоги недели:*\n\n"
            f"🏅 MVP: {mvp}\n"
            f"🥇 1-е место: {first}\n"
            f"🥈 2-е место: {second}\n"
            f"🥉 3-е место: {third}"
        )
        await update.message.reply_text(response, parse_mode="MarkdownV2")

        # Обнуляем голоса
        session.query(Player).delete()
        session.commit()

    except Exception as e:
        logging.error(f"Ошибка: {e}")
    finally:
        session.close()

# Запуск бота
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Регистрация обработчиков
    app.add_handler(CommandHandler("start_vote", start_vote))
    app.add_handler(CommandHandler("stop_vote", stop_vote))
    app.add_handler(CallbackQueryHandler(handle_player_selection, pattern="^rate_"))
    app.add_handler(CallbackQueryHandler(handle_rating, pattern="^set_rating_"))

    app.run_polling()

if __name__ == "__main__":
    main()