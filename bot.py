import os
import json
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# Токен бота и конфигурация вебхука
TOKEN = os.getenv('TOKEN', '7905448986:AAG5rXLzIjPLK6ayuah9Hsn2VdJKyUPqNPQ')
WEBHOOK_HOST = 'https://cs2-bot-qhok.onrender.com'
WEBHOOK_PATH = f'/{TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'
GIT_REPO_URL = f"https://{os.getenv('GIT_TOKEN')}@github.com/ildarkhan12/cs2-bot.git"

# Инициализация бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Твои ID
ADMIN_ID = 113405030
GROUP_ID = -1002484381098
bot_username = "CS2RatingBot"

# Глобальные переменные
voting_active = False
breakthrough_voting_active = False
current_voting_participants = []
voting_message_id = None
breakthrough_message_id = None

# Функции работы с данными
def migrate_players_data(data):
    """Миграция старой структуры players.json в новую с званиями."""
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

def load_players():
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            migrated_data = migrate_players_data(data)
            save_players(migrated_data)
            return migrated_data
    except FileNotFoundError:
        return {"players": []}

def save_players(data):
    with open('players.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

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

# Команды и обработчики
@dp.message(Command(commands=['start']))
async def send_welcome(message: types.Message):
    welcome_text = ("Салам, боец!\n"
                    "Я бот вашей CS2-тусовки. Вот что я умею:\n"
                    "🏆 Проводить голосования за рейтинг игроков (топ-10)\n"
                    "🚀 Определять 'Прорыв вечера'\n"
                    "🎖 Присуждать награды и звания (от Рядового до Майора)\n"
                    "📊 Вести статистику (очки, награды, игры)\n\n"
                    "ℹ️ Выбери действие ниже:")
    
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

@dp.message(Command(commands=['my_stats']))
async def my_stats(message: types.Message):
    user_id = message.from_user.id
    players = load_players()['players']
    player = next((p for p in players if p['id'] == user_id), None)
    if player:
        stats = player['stats']
        awards = player['awards']
        response = (f"Твоя статистика:\n"
                    f"Звание: {stats.get('rank', 'Рядовой')}\n"
                    f"Очки: {stats.get('rank_points', 0)}\n"
                    f"Игр сыграно: {stats.get('games_played', 0)}\n"
                    f"Голосований: {stats.get('votes_cast', 0)}\n"
                    f"MVP: {awards.get('mvp', 0)} раз\n"
                    f"1st: {awards.get('place1', 0)} раз\n"
                    f"2nd: {awards.get('place2', 0)} раз\n"
                    f"3rd: {awards.get('place3', 0)} раз\n"
                    f"Прорыв вечера: {awards.get('breakthrough', 0)} раз")
        await message.reply(response)
    else:
        await message.reply("❌ Ты не в списке игроков!")

@dp.message(Command(commands=['add_player']))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа, боец!")
        return
    args = message.text.split(maxsplit=2)[1:]
    if len(args) < 2:
        await message.reply("ℹ️ Используй: /add_player [ID] [имя]")
        return
    try:
        player_id = int(args[0])
        player_name = args[1]
        players_data = load_players()
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
        save_players(players_data)
        await message.reply(f"✅ {player_name} добавлен в состав!")
    except ValueError:
        await message.reply("❌ ID должен быть числом!")

@dp.callback_query(lambda c: c.data == 'start_voting_menu')
async def start_voting_menu(callback_query: types.CallbackQuery):
    global voting_active, breakthrough_voting_active
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if voting_active or breakthrough_voting_active:
        inline_keyboard = [
            [
                types.InlineKeyboardButton(text="В процессе", callback_data="voting_active"),
                types.InlineKeyboardButton(text="Остановить голосование", callback_data="stop_voting")
            ],
            [types.InlineKeyboardButton(text="Текущие результаты", callback_data="current_results")]
        ]
        if not voting_active and breakthrough_voting_active:
            inline_keyboard.append([types.InlineKeyboardButton(text="Остановить 'Прорыв вечера'", callback_data="stop_breakthrough_voting")])
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
        await bot.send_message(callback_query.from_user.id, "Голосование уже идёт!", reply_markup=keyboard)
        await bot.answer_callback_query(callback_query.id)
        return
    players = load_players()['players']
    if not players:
        await bot.send_message(callback_query.from_user.id, "Список игроков пуст!")
        await bot.answer_callback_query(callback_query.id)
        return
    for player in players:
        player['played_last_game'] = True
        player['ratings'] = []
        if player['played_last_game']:
            player['stats']['games_played'] = player['stats'].get('games_played', 0) + 1
            player['stats']['rank_points'] = player['stats'].get('rank_points', 0) + 5
            update_rank(player)
    save_players({"players": players})
    
    inline_keyboard = [[types.InlineKeyboardButton(text=f"{player['name']} (ID: {player['id']})", callback_data=f"absent_{player['id']}")] for player in players]
    inline_keyboard.append([types.InlineKeyboardButton(text="Готово", callback_data="finish_voting_setup")])
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(callback_query.from_user.id, "Выбери игроков, которые НЕ участвовали в последней игре:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data.startswith('absent_'))
async def mark_absent(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    player_id = int(callback_query.data.split('_')[1])
    players_data = load_players()
    for player in players_data['players']:
        if player['id'] == player_id:
            player['played_last_game'] = False
            player['stats']['rank_points'] = player['stats'].get('rank_points', 0) - 5
            update_rank(player)
            break
    save_players(players_data)
    players = players_data['players']
    inline_keyboard = [[types.InlineKeyboardButton(text=f"{player['name']} (ID: {player['id']})", callback_data=f"absent_{player['id']}")] for player in players if player['played_last_game']]
    inline_keyboard.append([types.InlineKeyboardButton(text="Готово", callback_data="finish_voting_setup")])
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.edit_message_text(
        chat_id=callback_query.from_user.id,
        message_id=callback_query.message.message_id,
        text="Выбери игроков, которые НЕ участвовали в последней игре:",
        reply_markup=keyboard
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'finish_voting_setup')
async def finish_voting_setup(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text="Запустить голосование", callback_data="launch_voting")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.edit_message_text(
        chat_id=callback_query.from_user.id,
        message_id=callback_query.message.message_id,
        text="Все игроки отмечены. Готов запустить голосование?",
        reply_markup=keyboard
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'launch_voting')
async def launch_voting(callback_query: types.CallbackQuery):
    global voting_active, current_voting_participants, voting_message_id
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    if voting_active:
        await bot.answer_callback_query(callback_query.id, "❌ Голосование уже идёт!")
        return
    voting_active = True
    players = load_players()['players']
    current_voting_participants = [p['id'] for p in players if p['played_last_game']]
    inline_keyboard = [[types.InlineKeyboardButton(text="Начать голосование", url=f"t.me/{bot_username}")]]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    message = await bot.send_message(GROUP_ID, "🏆 Голосование началось! Перейди в личку бота, чтобы оценить игроков:", reply_markup=keyboard)
    await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
    voting_message_id = message.message_id
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data == 'vote')
async def process_start_voting(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    players = load_players()['players']
    if user_id not in current_voting_participants:
        await bot.answer_callback_query(callback_query.id, "❌ Ты не участвуешь в текущем голосовании!")
        return
    player = next((p for p in players if p['id'] == user_id), None)
    if not player or not player['played_last_game']:
        await bot.answer_callback_query(callback_query.id, "❌ Ты не участвовал в последней игре!")
        return
    participants = [p for p in players if p['played_last_game'] and p['id'] != user_id]
    for p in participants:
        inline_keyboard = [
            [
                types.InlineKeyboardButton(text="5", callback_data=f"rate_{p['id']}_5"),
                types.InlineKeyboardButton(text="6", callback_data=f"rate_{p['id']}_6"),
                types.InlineKeyboardButton(text="7", callback_data=f"rate_{p['id']}_7"),
            ],
            [
                types.InlineKeyboardButton(text="8", callback_data=f"rate_{p['id']}_8"),
                types.InlineKeyboardButton(text="9", callback_data=f"rate_{p['id']}_9"),
                types.InlineKeyboardButton(text="10", callback_data=f"rate_{p['id']}_10"),
            ],
            [
                types.InlineKeyboardButton(text="Ещё", callback_data=f"more_rates_{p['id']}")
            ]
        ]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
        await bot.send_message(user_id, f"Оцени {p['name']} (1-10):", reply_markup=keyboard)
    finish_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Завершить голосование", callback_data="finish_voting_user")]
    ])
    await bot.send_message(user_id, "Когда закончишь оценивать всех, нажми ниже:", reply_markup=finish_keyboard)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data.startswith('more_rates_'))
async def more_rates(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    player_id = int(callback_query.data.split('_')[2])
    players = load_players()['players']
    player = next((p for p in players if p['id'] == player_id), None)
    inline_keyboard = [
        [
            types.InlineKeyboardButton(text="1", callback_data=f"rate_{player_id}_1"),
            types.InlineKeyboardButton(text="2", callback_data=f"rate_{player_id}_2"),
            types.InlineKeyboardButton(text="3", callback_data=f"rate_{player_id}_3"),
        ],
        [
            types.InlineKeyboardButton(text="4", callback_data=f"rate_{player_id}_4"),
        ]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.edit_message_text(
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        text=f"Оцени {player['name']} (1-4):",
        reply_markup=keyboard
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data.startswith('rate_'))
async def process_rating(callback_query: types.CallbackQuery):
    global voting_active
    data = callback_query.data.split('_')
    player_id = int(data[1])
    rating = int(data[2])
    user_id = callback_query.from_user.id
    players_data = load_players()
    for player in players_data['players']:
        if player['id'] == player_id:
            player['ratings'].append(rating)
            save_players(players_data)
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=callback_query.message.message_id,
                text=f"Ты поставил {rating} игроку {player['name']}!",
                reply_markup=None
            )
            await bot.answer_callback_query(callback_query.id)
            break
    if await check_voting_complete():
        print("Голосование автоматически завершено!")

@dp.callback_query(lambda c: c.data == 'finish_voting_user')
async def finish_voting_user(callback_query: types.CallbackQuery):
    global voting_active
    user_id = callback_query.from_user.id
    players_data = load_players()
    players = players_data['players']
    player = next((p for p in players if p['id'] == user_id), None)
    if not player or not player['played_last_game']:
        await bot.answer_callback_query(callback_query.id, "❌ Ты не участвовал в последней игре!")
        return
    participants = [p for p in players if p['played_last_game'] and p['id'] != user_id]
    all_rated = all(len(p['ratings']) > 0 for p in participants)
    if not all_rated:
        not_rated = [p['name'] for p in participants if not p['ratings']]
        await bot.send_message(user_id, f"Ты ещё не оценил: {', '.join(not_rated)}!")
        await bot.answer_callback_query(callback_query.id)
        return
    player['stats']['votes_cast'] = player['stats'].get('votes_cast', 0) + 1
    save_players(players_data)
    await bot.send_message(user_id, "✅ Твоё голосование завершено!")
    await bot.edit_message_reply_markup(
        chat_id=user_id,
        message_id=callback_query.message.message_id,
        reply_markup=None
    )
    if await check_voting_complete():
        print("Голосование автоматически завершено!")
    await bot.answer_callback_query(callback_query.id)

async def check_voting_complete():
    global voting_active, breakthrough_voting_active, voting_message_id
    players = load_players()['players']
    participants = [p for p in players if p['played_last_game']]
    if not participants:
        return False
    total_participants = len(participants)
    for player in participants:
        expected_ratings = total_participants - 1
        if len(player['ratings']) != expected_ratings:
            return False
    sorted_players = sorted([p for p in players if p['ratings']], key=lambda p: sum(p['ratings']) / len(p['ratings']), reverse=True)
    awards_notifications = []
    points_map = {1: 25, 2: 20, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 3, 10: 2}
    for i, player in enumerate(sorted_players[:10], 1):
        if i == 1:
            player['awards']['mvp'] += 1
            player['stats']['mvp_count'] += 1
            awards_notifications.append((player['id'], f"🏆 Ты получил награду MVP за эту игру (+{points_map[i]} очков)! Новое звание: {player['stats']['rank']}"))
        elif i == 2:
            player['awards']['place1'] += 1
            awards_notifications.append((player['id'], f"🥇 Ты занял 1-е место в этой игре (+{points_map[i]} очков)! Новое звание: {player['stats']['rank']}"))
        elif i == 3:
            player['awards']['place2'] += 1
            awards_notifications.append((player['id'], f"🥈 Ты занял 2-е место в этой игре (+{points_map[i]} очков)! Новое звание: {player['stats']['rank']}"))
        elif i == 4:
            player['awards']['place3'] += 1
            awards_notifications.append((player['id'], f"🥉 Ты занял 3-е место в этой игре (+{points_map[i]} очков)! Новое звание: {player['stats']['rank']}"))
        else:
            awards_notifications.append((player['id'], f"Ты вошёл в топ-{i} этой игры (+{points_map[i]} очков)! Новое звание: {player['stats']['rank']}"))
        player['stats']['rank_points'] = player['stats'].get('rank_points', 0) + points_map[i]
        update_rank(player)
    for player in players:
        player['ratings'] = []
    save_players({"players": players})
    result = "🏆 Голосование за рейтинг завершено!\n\nРезультаты боя:\n"
    for i, p in enumerate(sorted_players[:10], 1):
        awards_str = ""
        if i == 1:
            awards_str = " (MVP 🏆)"
        elif i == 2:
            awards_str = " (🥇 1st)"
        elif i == 3:
            awards_str = " (🥈 2nd)"
        elif i == 4:
            awards_str = " (🥉 3rd)"
        result += f"{i}. {p['name']} — {sum(p['ratings'])/len(p['ratings'] if p['ratings'] else 1):.2f}{awards_str}\n"
    message = await bot.send_message(GROUP_ID, result)
    await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
    if voting_message_id:
        await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=voting_message_id)
        voting_message_id = None
    for participant_id in current_voting_participants:
        try:
            await bot.send_message(participant_id, "🏆 Голосование завершено! Проверь результаты в группе!")
        except Exception as e:
            print(f"Не удалось уведомить ID {participant_id}: {e}")
    for winner_id, award_text in awards_notifications:
        try:
            await bot.send_message(winner_id, award_text)
        except Exception as e:
            print(f"Не удалось уведомить ID {winner_id}: {e}")
    await bot.send_message(ADMIN_ID, "✅ Основное голосование завершено автоматически! Запускаем голосование за 'Прорыв вечера'.")
    voting_active = False
    breakthrough_voting_active = True
    await start_breakthrough_voting()
    return True

async def start_breakthrough_voting():
    global breakthrough_voting_active, breakthrough_message_id
    players = load_players()['players']
    eligible_players = [p for p in players if p['played_last_game'] and not any([p['awards']['mvp'], p['awards']['place1'], p['awards']['place2'], p['awards']['place3']])]
    if not eligible_players:
        await bot.send_message(GROUP_ID, "🚀 Нет кандидатов на 'Прорыв вечера'!")
        breakthrough_voting_active = False
        return
    inline_keyboard = [[types.InlineKeyboardButton(text="Голосовать за 'Прорыв вечера'", url=f"t.me/{bot_username}")]]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    message = await bot.send_message(GROUP_ID, "🚀 Голосование за 'Прорыв вечера' началось! Перейди в личку бота, чтобы выбрать игрока:", reply_markup=keyboard)
    await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
    breakthrough_message_id = message.message_id
    breakthrough_voting_active = True

@dp.callback_query(lambda c: c.data == 'vote_breakthrough')
async def process_breakthrough_voting(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    players = load_players()['players']
    if user_id not in current_voting_participants:
        await bot.answer_callback_query(callback_query.id, "❌ Ты не участвуешь в текущем голосовании!")
        return
    player = next((p for p in players if p['id'] == user_id), None)
    if not player or not player['played_last_game']:
        await bot.answer_callback_query(callback_query.id, "❌ Ты не участвовал в последней игре!")
        return
    eligible_players = [p for p in players if p['played_last_game'] and not any([p['awards']['mvp'], p['awards']['place1'], p['awards']['place2'], p['awards']['place3']])]
    if not eligible_players:
        await bot.answer_callback_query(callback_query.id, "❌ Нет кандидатов на 'Прорыв вечера'!")
        return
    inline_keyboard = [
        [types.InlineKeyboardButton(text=f"{p['name']}", callback_data=f"breakthrough_{p['id']}")] for p in eligible_players
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await bot.send_message(user_id, "Выбери игрока для 'Прорыва вечера':", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query(lambda c: c.data.startswith('breakthrough_'))
async def process_breakthrough_rating(callback_query: types.CallbackQuery):
    global breakthrough_voting_active
    data = callback_query.data.split('_')
    player_id = int(data[1])
    user_id = callback_query.from_user.id
    players_data = load_players()
    for player in players_data['players']:
        if player['id'] == player_id:
            if 'breakthrough_ratings' not in player:
                player['breakthrough_ratings'] = []
            player['breakthrough_ratings'].append(1)
            save_players(players_data)
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=callback_query.message.message_id,
                text=f"Ты проголосовал за {player['name']} как 'Прорыв вечера'!",
                reply_markup=None
            )
            await bot.answer_callback_query(callback_query.id)
            break
    if await check_breakthrough_voting_complete():
        print("Голосование за 'Прорыв вечера' автоматически завершено!")

async def check_breakthrough_voting_complete():
    global breakthrough_voting_active, breakthrough_message_id
    players = load_players()['players']
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
            awards_notifications.append((winner['id'], f"🚀 Ты получил награду 'Прорыв вечера' за эту игру (+10 очков)! Новое звание: {winner['stats']['rank']}"))
        result = f"🚀 Голосование за 'Прорыв вечера' завершено автоматически!\n\nПрорыв вечера: {winner_names}!"
        message = await bot.send_message(GROUP_ID, result)
        await bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id, disable_notification=True)
    for player in players:
        player.pop('breakthrough_ratings', None)
    save_players({"players": players})
    if breakthrough_message_id:
        await bot.unpin_chat_message(chat_id=GROUP_ID, message_id=breakthrough_message_id)
        breakthrough_message_id = None
    for participant_id in current_voting_participants:
        try:
            await bot.send_message(participant_id, "🚀 Голосование за 'Прорыв вечера' завершено! Проверь результаты в группе!")
        except Exception as e:
            print(f"Не удалось уведомить ID {participant_id}: {e}")
    for winner_id, award_text in awards_notifications:
        try:
            await bot.send_message(winner_id, award_text)
        except Exception as e:
            print(f"Не удалось уведомить ID {winner_id}: {e}")
    breakthrough_voting_active = False
    return True

# Настройка вебхука и запуск
async def on_startup(dispatcher: Dispatcher):
    await bot.set_webhook(WEBHOOK_URL)
    print(f"Бот запущен с вебхуком: {WEBHOOK_URL}")

async def on_shutdown(dispatcher: Dispatcher):
    await bot.delete_webhook()
    print("Бот остановлен")

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
    
    try:
        await asyncio.Event().wait()  # Держим приложение запущенным
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
