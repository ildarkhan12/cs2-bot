import os
import json
import asyncio
import logging
import aiofiles
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Токен бота и конфигурация вебхука
TOKEN = os.getenv('TOKEN', '7905448986:AAG5rXLzIjPLK6ayuah9Hsn2VdJKyUPqNPQ')
WEBHOOK_HOST = 'https://cs2-bot-qhok.onrender.com'
WEBHOOK_PATH = f'/{TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ID администратора и группы
ADMIN_ID = 113405030
GROUP_ID = -1002484381098
bot_username = "CS2RatingBot"

# Глобальные переменные для голосований
voting_active = False
breakthrough_voting_active = False
current_voting_participants = []
voting_message_id = None
breakthrough_message_id = None

# Глобальный замок для доступа к файлу и переменная для таймера авто-завершения
file_lock = asyncio.Lock()
auto_finish_task = None

# Константа авто-завершения голосования: 24 часа = 86400 секунд
AUTO_FINISH_DELAY = 86400

# --- Функции работы с данными ---

def migrate_players_data(data):
    for player in data['players']:
        if 'stats' not in player:
            player['stats'] = {}
        if 'awards' not in player:
            player['awards'] = {"mvp": 0, "place1": 0, "place2": 0, "place3": 0, "breakthrough": 0}
        if 'avg_rating' in player['stats']:
            del player['stats']['avg_rating']
        player['stats'].setdefault('mvp_count', player['awards'].get('mvp', 0))
        player['stats'].setdefault('games_played', 0)
        player['stats'].setdefault('votes_cast', 0)
        if 'rank_points' not in player['stats']:
            points = player['stats']['games_played'] * 5
            points += player['awards'].get('mvp', 0) * 25
            points += player['awards'].get('place1', 0) * 20
            points += player['awards'].get('place2', 0) * 15
            points += player['awards'].get('place3', 0) * 12
            points += player['awards'].get('breakthrough', 0) * 10
            player['stats']['rank_points'] = points
        update_rank(player)
        player['awards'].setdefault('breakthrough', 0)
    return data

async def load_players():
    async with file_lock:
        try:
            async with aiofiles.open('players.json', mode='r', encoding='utf-8') as f:
                contents = await f.read()
                data = json.loads(contents)
                migrated_data = migrate_players_data(data)
                await save_players(migrated_data)
                return migrated_data
        except FileNotFoundError:
            logger.warning("Файл players.json не найден, возвращаю пустые данные.")
            return {"players": []}
        except Exception as e:
            logger.exception("Ошибка при чтении players.json")
            return {"players": []}

async def save_players(data):
    async with file_lock:
        try:
            async with aiofiles.open('players.json', mode='w', encoding='utf-8') as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=4))
        except Exception as e:
            logger.exception("Ошибка при сохранении players.json")

def update_rank(player):
    points = player['stats'].get('rank_points', 0)
    if points >= 801:
        player['stats']['rank'] = "Майор"
    elif points >= 501:
        player['stats']['rank'] = "Капитан"
    elif points >= 301:
        player['stats']['rank'] = "Лейтенант"
    elif points >= 151:
        player['stats']['rank'] = "Сержант"
    elif points >= 51:
        player['stats']['rank'] = "Капрал"
    else:
        player['stats']['rank'] = "Рядовой"

def get_average_rating(player):
    return (sum(player['ratings']) / len(player['ratings'])) if player['ratings'] else 0

# --- Функция авто-завершения голосования ---
async def auto_finish_voting():
    try:
        await asyncio.sleep(AUTO_FINISH_DELAY)
        if voting_active:
            for participant_id in current_voting_participants:
                try:
                    await bot.send_message(participant_id, "⏰ Голосование завершено автоматически через 24 часа.")
                except Exception as e:
                    logger.exception("Не удалось отправить уведомление участнику %s", participant_id)
            await check_voting_complete()
            logger.info("Голосование автоматически завершено по таймеру (24 часа)")
    except asyncio.CancelledError:
        logger.info("Таймер авто-завершения голосования отменён")
        raise

# --- Команды и обработчики ---

# Если команда /start вызвана в группе – перенаправляем в ЛС
@dp.message(Command(commands=['start']))
async def send_welcome(message: types.Message):
    if message.chat.type != "private":
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Перейти в ЛС", url=f"t.me/{bot_username}")]
        ])
        await message.reply("Это групповой чат. Для полноценного взаимодействия перейдите в личные сообщения с ботом.", reply_markup=keyboard)
        logger.info("Команда /start получена в группе от пользователя %s", message.from_user.id)
        return

    welcome_text = (
        "Салам, боец!\n"
        "Я бот вашей CS2-тусовки. Вот что я умею:\n"
        "🏆 Проводить голосования за рейтинг игроков (топ-10)\n"
        "🚀 Определять 'Прорыв вечера'\n"
        "🎖 Присуждать награды и звания (от Рядового до Майора)\n"
        "📊 Вести статистику (очки, награды, игры)\n\n"
        "ℹ️ Выбери действие ниже:"
    )
    inline_keyboard = [
        [
            types.InlineKeyboardButton(text="Список команд", callback_data="help"),
            types.InlineKeyboardButton(text="Моя статистика", callback_data="my_stats")
        ]
    ]
    if message.from_user.id == ADMIN_ID:
        inline_keyboard.extend([
            [
                types.InlineKeyboardButton(text="Управление игроками", callback_data="manage_players"),
                types.InlineKeyboardButton(text="Голосование за рейтинг", callback_data="start_voting_menu")
            ]
        ])
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await message.reply(welcome_text, reply_markup=keyboard)
    logger.info("Отправлено приветственное сообщение пользователю %s", message.from_user.id)

# Управление игроками (для админа)
@dp.callback_query(lambda c: c.data == 'manage_players')
async def manage_players_handler(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text="Добавить игрока", callback_data="add_player_prompt")],
        [types.InlineKeyboardButton(text="Удалить игрока", callback_data="remove_player_prompt")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(callback_query.from_user.id, "Выберите действие:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)
    logger.info("Администратор %s вызвал управление игроками", callback_query.from_user.id)

@dp.callback_query(lambda c: c.data == 'add_player_prompt')
async def add_player_prompt(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "Используйте команду /add_player [ID] [Имя] для добавления игрока.")
    logger.info("Подсказка по добавлению игрока отправлена админу %s", callback_query.from_user.id)

@dp.callback_query(lambda c: c.data == 'remove_player_prompt')
async def remove_player_prompt(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "Используйте команду /remove_player [ID] для удаления игрока.\nПосле ввода команды вам будет предложено подтвердить удаление.")
    logger.info("Подсказка по удалению игрока отправлена админу %s", callback_query.from_user.id)

# Команда для удаления игрока (с подтверждением)
@dp.message(Command(commands=['remove_player']))
async def remove_player(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа!")
        return
    args = message.text.split(maxsplit=1)[1:]
    if len(args) < 1:
        await message.reply("ℹ️ Используй: /remove_player [ID]")
        return
    try:
        player_id = int(args[0])
        inline_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Да", callback_data=f"confirm_remove_{player_id}")],
            [types.InlineKeyboardButton(text="Нет", callback_data="cancel_remove")]
        ])
        await message.reply(f"Вы уверены, что хотите удалить игрока с ID {player_id}?", reply_markup=inline_keyboard)
        logger.info("Запрошено подтверждение на удаление игрока с ID %s", player_id)
    except ValueError:
        await message.reply("❌ ID должен быть числом!")

@dp.callback_query(lambda c: c.data.startswith('confirm_remove_'))
async def confirm_remove(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    try:
        player_id = int(callback_query.data.split('_')[2])
        players_data = await load_players()
        players_list = players_data['players']
        new_players_list = [p for p in players_list if p['id'] != player_id]
        if len(new_players_list) == len(players_list):
            await bot.send_message(callback_query.from_user.id, f"❌ Игрок с ID {player_id} не найден!")
            await bot.answer_callback_query(callback_query.id)
            return
        players_data['players'] = new_players_list
        await save_players(players_data)
        await bot.send_message(callback_query.from_user.id, f"✅ Игрок с ID {player_id} удалён!")
        logger.info("Удалён игрок с ID %s", player_id)
    except Exception as e:
        logger.exception("Ошибка при удалении игрока")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'cancel_remove')
async def cancel_remove(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, "Удаление отменено")
    await bot.send_message(callback_query.from_user.id, "❌ Удаление отменено")
    logger.info("Удаление игрока отменено администратором %s", callback_query.from_user.id)

# Команда /add_player (реализована ранее)
@dp.message(Command(commands=['add_player']))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа, боец!")
        return
    args = message.text.split(maxsplit=2)[1:]
    if len(args) < 2:
        await message.reply("ℹ️ Используй: /add_player [ID] [Имя]")
        return
    try:
        player_id = int(args[0])
        player_name = args[1]
        players_data = await load_players()
        if any(p['id'] == player_id for p in players_data['players']):
            await message.reply(f"❌ Игрок с ID {player_id} уже существует!")
            return
        players_data['players'].append({
            "id": player_id,
            "name": player_name,
            "ratings": [],
            "played_last_game": False,
            "awards": {"mvp": 0, "place1": 0, "place2": 0, "place3": 0, "breakthrough": 0},
            "stats": {"mvp_count": 0, "games_played": 0, "votes_cast": 0, "rank_points": 0, "rank": "Рядовой"}
        })
        await save_players(players_data)
        await message.reply(f"✅ {player_name} добавлен в состав!")
        logger.info("Добавлен игрок %s (ID: %s)", player_name, player_id)
    except ValueError:
        await message.reply("❌ ID должен быть числом!")
    except Exception as e:
        logger.exception("Ошибка при добавлении игрока")

# Команда /leaderboard (оформление с Markdown)
@dp.message(Command(commands=['leaderboard']))
async def leaderboard(message: types.Message):
    players_data = await load_players()
    players = players_data['players']
    if not players:
        await message.reply("Список игроков пуст!")
        return
    sorted_players = sorted(players, key=lambda p: p['stats'].get('rank_points', 0), reverse=True)
    text = "*Лидерборд игроков:*\n\n"
    for i, p in enumerate(sorted_players, 1):
        text += f"• *{i}. {p['name']}* — *{p['stats'].get('rank_points', 0)}* очков\n"
    await message.reply(text, parse_mode="Markdown")
    logger.info("Лидерборд запрошен пользователем %s", message.from_user.id)

# Команда /my_stats – блок статистики оформлен красивее (без votes_cast)
@dp.message(Command(commands=['my_stats']))
async def my_stats(message: types.Message):
    user_id = message.from_user.id
    players_data = await load_players()
    player = next((p for p in players_data['players'] if p['id'] == user_id), None)
    if player:
        stats = player['stats']
        awards = player['awards']
        response = (
            "*Ваша статистика:*\n\n"
            f"• *Звание:* {stats.get('rank', 'Рядовой')}\n"
            f"• *Очки:* {stats.get('rank_points', 0)}\n"
            f"• *Игр сыграно:* {stats.get('games_played', 0)}\n"
            f"• *MVP:* {awards.get('mvp', 0)} раз\n"
            f"• *1st:* {awards.get('place1', 0)} раз\n"
            f"• *2nd:* {awards.get('place2', 0)} раз\n"
            f"• *3rd:* {awards.get('place3', 0)} раз\n"
            f"• *Прорыв вечера:* {awards.get('breakthrough', 0)} раз\n"
        )
        await message.reply(response, parse_mode="Markdown")
    else:
        await message.reply("❌ Вы не в списке игроков!")
        
# Остальные обработчики (голосование, оценка, авто-завершение голосования, прорыв вечера и т.д.)
# При досрочном завершении голосования, если все участники оценили всех, мы отменяем таймер авто-завершения:
@dp.callback_query(lambda c: c.data.startswith('finish_voting_user'))
async def finish_voting_user(callback_query: types.CallbackQuery):
    global voting_active, auto_finish_task
    user_id = callback_query.from_user.id
    players_data = await load_players()
    players = players_data['players']
    player = next((p for p in players if p['id'] == user_id), None)
    if not player or not player['played_last_game']:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвовали в последней игре!")
        return
    player['stats']['votes_cast'] = player['stats'].get('votes_cast', 0) + 1
    await save_players(players_data)
    await bot.send_message(user_id, "✅ Ваше голосование завершено!")
    await bot.edit_message_reply_markup(
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        reply_markup=None
    )
    await bot.answer_callback_query(callback_query.id)
    logger.info("Пользователь %s завершил голосование", user_id)
    all_finished = all(
        (len(p['ratings']) >= (len([pp for pp in players if pp['played_last_game']]) - 1))
         for p in players if p['played_last_game']
    )
    if all_finished:
        if auto_finish_task is not None:
            auto_finish_task.cancel()
            auto_finish_task = None
        await check_voting_complete()

# Пример обработчика завершения голосования, расчёт результатов и публикация итогов
async def check_voting_complete():
    global voting_active, breakthrough_voting_active, voting_message_id, auto_finish_task
    players_data = await load_players()
    players = players_data['players']
    participants = [p for p in players if p['played_last_game']]
    if not participants:
        return False
    averages = {p['id']: get_average_rating(p) for p in participants}
    sorted_players = sorted(participants, key=lambda p: averages[p['id']], reverse=True)
    awards_notifications = []
    points_map = {1: 25, 2: 20, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 3, 10: 2}
    for i, player in enumerate(sorted_players[:10], 1):
        if i == 1:
            player['awards']['mvp'] += 1
            player['stats']['mvp_count'] += 1
            awards_notifications.append((player['id'], f"🏆 Вы получили награду MVP за эту игру (+{points_map[i]} очков)! Новое звание: {player['stats']['rank']}"))
        elif i == 2:
            player['awards']['place1'] += 1
            awards_notifications.append((player['id'], f"🥇 Вы заняли 1-е место в этой игре (+{points_map[i]} очков)! Новое звание: {player['stats']['rank']}"))
        elif i == 3:
            player['awards']['place2'] += 1
            awards_notifications.append((player['id'], f"🥈 Вы заняли 2-е место в этой игре (+{points_map[i]} очков)! Новое звание: {player['stats']['rank']}"))
        elif i == 4:
            player['awards']['place3'] += 1
            awards_notifications.append((player['id'], f"🥉 Вы заняли 3-е место в этой игре (+{points_map[i]} очков)! Новое звание: {player['stats']['rank']}"))
        else:
            awards_notifications.append((player['id'], f"Вы вошли в топ-{i} этой игры (+{points_map[i]} очков)! Новое звание: {player['stats']['rank']}"))
        player['stats']['rank_points'] = player['stats'].get('rank_points', 0) + points_map[i]
        update_rank(player)
    result = "🏆 Голосование за рейтинг завершено!\n\nРезультаты боя:\n"
    for i, p in enumerate(sorted_players[:10], 1):
        result += f"{i}. {p['name']} — {averages[p['id']]:.2f}"
        if i == 1:
            result += " (MVP 🏆)"
        elif i == 2:
            result += " (🥇 1st)"
        elif i == 3:
            result += " (🥈 2nd)"
        elif i == 4:
            result += " (🥉 3rd)"
        result += "\n"
    for p in players:
        p['ratings'] = []
    await save_players(players_data)
    message = await bot.send_message(GROUP_ID, result)
    await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
    if voting_message_id:
        await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=voting_message_id)
        voting_message_id = None
    for participant_id in current_voting_participants:
        try:
            await bot.send_message(participant_id, "🏆 Голосование завершено! Проверьте результаты в группе!")
        except Exception as e:
            logger.exception("Не удалось уведомить пользователя ID %s", participant_id)
    for winner_id, award_text in awards_notifications:
        try:
            await bot.send_message(winner_id, award_text)
        except Exception as e:
            logger.exception("Не удалось уведомить пользователя ID %s", winner_id)
    await bot.send_message(ADMIN_ID, "✅ Основное голосование завершено автоматически! Запускаем голосование за 'Прорыв вечера'.")
    voting_active = False
    breakthrough_voting_active = True
    await start_breakthrough_voting()
    logger.info("Основное голосование завершено")
    return True

# Обработчики для голосования за "Прорыв вечера" остаются без изменений…
@dp.callback_query(lambda c: c.data == 'vote_breakthrough')
async def process_breakthrough_voting(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    players_data = await load_players()
    players = players_data['players']
    if user_id not in current_voting_participants:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвуете в текущем голосовании!")
        return
    player = next((p for p in players if p['id'] == user_id), None)
    if not player or not player['played_last_game']:
        await bot.answer_callback_query(callback_query.id, "❌ Вы не участвовали в последней игре!")
        return
    eligible_players = [p for p in players if p['played_last_game'] and not any([p['awards']['mvp'], p['awards']['place1'], p['awards']['place2'], p['awards']['place3']])]
    if not eligible_players:
        await bot.answer_callback_query(callback_query.id, "❌ Нет кандидатов на 'Прорыв вечера'!")
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text=f"{p['name']}", callback_data=f"breakthrough_{p['id']}")] for p in eligible_players
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(user_id, "Выберите игрока для 'Прорыва вечера':", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)
    logger.info("Пользователь %s начал голосование за 'Прорыв вечера'", user_id)

@dp.callback_query(lambda c: c.data.startswith('breakthrough_'))
async def process_breakthrough_rating(callback_query: types.CallbackQuery):
    global breakthrough_voting_active
    data = callback_query.data.split('_')
    player_id = int(data[1])
    user_id = callback_query.from_user.id
    players_data = await load_players()
    for player in players_data['players']:
        if player['id'] == player_id:
            if 'breakthrough_ratings' not in player:
                player['breakthrough_ratings'] = []
            player['breakthrough_ratings'].append(1)
            await save_players(players_data)
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=callback_query.message.message_id,
                text=f"Вы проголосовали за {player['name']} как 'Прорыв вечера'!",
                reply_markup=None
            )
            await bot.answer_callback_query(callback_query.id)
            logger.info("Пользователь %s проголосовал за 'Прорыв вечера' за игрока %s", user_id, player_id)
            break
    if await check_breakthrough_voting_complete():
        logger.info("Голосование за 'Прорыв вечера' автоматически завершено")

async def check_breakthrough_voting_complete():
    global breakthrough_voting_active, breakthrough_message_id
    players_data = await load_players()
    players = players_data['players']
    participants = [p for p in players if p['played_last_game']]
    eligible_players = [p for p in players if p['played_last_game'] and not any([p['awards']['mvp'], p['awards']['place1'], p['awards']['place2'], p['awards']['place3']])]
    if not eligible_players:
        breakthrough_voting_active = False
        message = await bot.send_message(GROUP_ID, "🚀 Голосование за 'Прорыв вечера' завершено!\n\nНет кандидатов.")
        await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
        if breakthrough_message_id:
            await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=breakthrough_message_id)
            breakthrough_message_id = None
        return True
    total_participants = len(participants)
    rated_players = [p for p in eligible_players if p.get('breakthrough_ratings', [])]
    if len(rated_players) < total_participants:
        return False
    sorted_eligible = sorted(eligible_players, key=lambda p: len(p.get('breakthrough_ratings', [])), reverse=True)
    max_votes = len(sorted_eligible[0].get('breakthrough_ratings', [])) if sorted_eligible else 0
    winners = [p for p in sorted_eligible if len(p.get('breakthrough_ratings', [])) == max_votes]
    awards_notifications = []
    if winners:
        winner_names = ", ".join(p['name'] for p in winners)
        for winner in winners:
            winner['awards']['breakthrough'] = winner['awards'].get('breakthrough', 0) + 1
            winner['stats']['rank_points'] = winner['stats'].get('rank_points', 0) + 10
            update_rank(winner)
            awards_notifications.append((winner['id'], f"🚀 Вы получили награду 'Прорыв вечера' за эту игру (+10 очков)! Новое звание: {winner['stats']['rank']}"))
        result = f"🚀 Голосование за 'Прорыв вечера' завершено автоматически!\n\nПрорыв вечера: {winner_names}!"
        message = await bot.send_message(GROUP_ID, result)
        await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
    for player in players:
        player.pop('breakthrough_ratings', None)
    await save_players(players_data)
    if breakthrough_message_id:
        await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=breakthrough_message_id)
        breakthrough_message_id = None
    for participant_id in current_voting_participants:
        try:
            await bot.send_message(participant_id, "🚀 Голосование за 'Прорыв вечера' завершено! Проверьте результаты в группе!")
        except Exception as e:
            logger.exception("Не удалось уведомить пользователя ID %s", participant_id)
    for winner_id, award_text in awards_notifications:
        try:
            await bot.send_message(winner_id, award_text)
        except Exception as e:
            logger.exception("Не удалось уведомить пользователя ID %s", winner_id)
    breakthrough_voting_active = False
    logger.info("Голосование за 'Прорыв вечера' завершено")
    return True

# --- Настройка вебхука и запуск приложения ---

async def on_startup(dispatcher: Dispatcher):
    await bot.set_webhook(WEBHOOK_URL)
    logger.info("Бот запущен с вебхуком: %s", WEBHOOK_URL)

async def on_shutdown(dispatcher: Dispatcher):
    await bot.delete_webhook()
    logger.info("Бот остановлен")

async def main():
    app = web.Application()
    webhook_request_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_request_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
    await site.start()
    logger.info("Сервер запущен на порту %s", os.getenv('PORT', 8080))
    
    try:
        await asyncio.Event().wait()  # Держим приложение запущенным
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
