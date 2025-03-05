import os
import json
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# Токен бота из переменной окружения (для Render)
TOKEN = os.getenv('TOKEN', '7905448986:AAG5rXLzIjPLK6ayuah9Hsn2VdJKyUPqNPQ')
WEBHOOK_HOST = 'https://cs2-bot-qhok.onrender.com'
WEBHOOK_PATH = f'/{TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

# Инициализация бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Твои ID
ADMIN_ID = 113405030  # Твой Telegram ID
GROUP_ID = -2484381098  # ID группы

# Функции для работы с файлами
def load_players():
    try:
        with open('players.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"players": []}

def save_players(players_data):
    with open('players.json', 'w', encoding='utf-8') as f:
        json.dump(players_data, f, ensure_ascii=False, indent=4)

def load_maps():
    try:
        with open('maps.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {map_name: 0 for map_name in ["Dust2", "Mirage", "Inferno", "Nuke", "Overpass", "Vertigo", "Ancient", "Anubis", "Cache", "Train"]}

def save_maps(maps_data):
    with open('maps.json', 'w', encoding='utf-8') as f:
        json.dump(maps_data, f, ensure_ascii=False, indent=4)

# Команда /start с приветствием и кнопками
@dp.message(Command(commands=['start']))
async def send_welcome(message: types.Message):
    welcome_text = ("Салам, боец!\n"
                    "Я бот вашей CS2-тусовки. Вот что я умею:\n"
                    "🏆 Проводить голосования за рейтинг и карты\n"
                    "🎖 Присуждать награды\n"
                    "📊 Показывать статистику\n\n"
                    "ℹ️ Админ управляет мной через команды. Выбери действие ниже:")
    
    # Создаём клавиатуру с пустым списком кнопок
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    keyboard.add(
        types.InlineKeyboardButton("Список команд", callback_data="help"),
        types.InlineKeyboardButton("Моя статистика", callback_data="my_stats")
    )
    if message.from_user.id == ADMIN_ID:
        keyboard.add(
            types.InlineKeyboardButton("Управление игроками", callback_data="manage_players"),
            types.InlineKeyboardButton("Голосование за рейтинг", callback_data="start_voting"),
            types.InlineKeyboardButton("Голосование за карты", callback_data="start_map_voting")
        )
    
    await message.reply(welcome_text, reply_markup=keyboard)

# Обработка кнопки "Список команд"
@dp.callback_query(lambda c: c.data == 'help')
async def process_help(callback_query: types.CallbackQuery):
    help_text = ("📜 **Список команд**:\n"
                 "/start — начать работу\n"
                 "/my_stats — твоя статистика\n"
                 "**Для админа**:\n"
                 "/add_player <ID> <имя> — добавить игрока\n"
                 "/remove_player <ID> — удалить игрока\n"
                 "/start_voting — начать голосование за рейтинг\n"
                 "/end_voting — завершить голосование\n"
                 "/start_map_voting — голосование за карты\n"
                 "/end_map_voting — завершить голосование за карты\n"
                 "/top — показать топ игроков")
    await bot.send_message(callback_query.from_user.id, help_text, parse_mode='Markdown')
    await bot.answer_callback_query(callback_query.id)

# Обработка кнопки "Моя статистика"
@dp.callback_query(lambda c: c.data == 'my_stats')
async def process_my_stats(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    players = load_players()['players']
    for p in players:
        if p['id'] == user_id:
            stats = p['stats']
            awards = p['awards']
            response = (f"📊 **Твоя статистика**\n"
                        f"Побед: {stats['wins']}\n"
                        f"Средний рейтинг: {stats['avg_rating']:.2f}\n"
                        f"MVP: {awards['mvp']} раз\n"
                        f"1st: {awards['place1']} раз\n"
                        f"2nd: {awards['place2']} раз\n"
                        f"3rd: {awards['place3']} раз")
            await bot.send_message(user_id, response, parse_mode='Markdown')
            await bot.answer_callback_query(callback_query.id)
            return
    await bot.send_message(user_id, "❌ Ты не в списке игроков!")
    await bot.answer_callback_query(callback_query.id)

# Обработка кнопки "Управление игроками" (админ)
@dp.callback_query(lambda c: c.data == 'manage_players')
async def manage_players(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    keyboard.add(
        types.InlineKeyboardButton("Добавить игрока", callback_data="add_player_menu"),
        types.InlineKeyboardButton("Удалить игрока", callback_data="remove_player_menu")
    )
    await bot.send_message(callback_query.from_user.id, "Выбери действие:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# Меню "Добавить игрока" (админ)
@dp.callback_query(lambda c: c.data == 'add_player_menu')
async def add_player_menu(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    await bot.send_message(callback_query.from_user.id, "Напиши: /add_player <ID> <имя>\nНапример: /add_player 123456789 Иван")
    await bot.answer_callback_query(callback_query.id)

# Меню "Удалить игрока" (админ)
@dp.callback_query(lambda c: c.data == 'remove_player_menu')
async def remove_player_menu(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    players = load_players()['players']
    if not players:
        await bot.send_message(callback_query.from_user.id, "Список игроков пуст!")
        await bot.answer_callback_query(callback_query.id)
        return
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    for player in players:
        keyboard.add(types.InlineKeyboardButton(f"{player['name']} (ID: {player['id']})", callback_data=f"remove_{player['id']}"))
    await bot.send_message(callback_query.from_user.id, "Выбери игрока для удаления:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# Удаление игрока через кнопку
@dp.callback_query(lambda c: c.data.startswith('remove_'))
async def process_remove_player(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    player_id = int(callback_query.data.split('_')[1])
    players_data = load_players()
    players_data['players'] = [p for p in players_data['players'] if p['id'] != player_id]
    save_players(players_data)
    await bot.send_message(callback_query.from_user.id, f"✅ Игрок с ID {player_id} удалён!")
    await bot.answer_callback_query(callback_query.id)

# Команда /add_player (админ)
@dp.message(Command(commands=['add_player']))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа, боец!")
        return
    args = message.text.split(maxsplit=2)[1:]
    if len(args) < 2:
        await message.reply("ℹ️ Используй: /add_player <ID> <имя>")
        return
    try:
        player_id = int(args[0])
        player_name = args[1]
        players_data = load_players()
        players_data['players'].append({
            "id": player_id,
            "name": player_name,
            "ratings": [],
            "awards": {"mvp": 0, "place1": 0, "place2": 0, "place3": 0},
            "stats": {"wins": 0, "avg_rating": 0, "mvp_count": 0}
        })
        save_players(players_data)
        await message.reply(f"✅ {player_name} добавлен в состав!")
    except ValueError:
        await message.reply("❌ ID должен быть числом!")

# Команда /start_voting (админ)
@dp.message(Command(commands=['start_voting']))
async def start_voting(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа, боец!")
        return
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    keyboard.add(types.InlineKeyboardButton("Голосовать", callback_data="vote"))
    await bot.send_message(GROUP_ID, "🏆 Голосование началось! Нажми кнопку, чтобы оценить игроков:", reply_markup=keyboard)

# Обработка кнопки "Голосование за рейтинг" (админ)
@dp.callback_query(lambda c: c.data == 'start_voting')
async def process_start_voting_button(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    keyboard.add(types.InlineKeyboardButton("Голосовать", callback_data="vote"))
    await bot.send_message(GROUP_ID, "🏆 Голосование началось! Нажми кнопку, чтобы оценить игроков:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# Обработка кнопки "Голосовать"
@dp.callback_query(lambda c: c.data == 'vote')
async def process_start_voting(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    players = load_players()['players']
    if user_id not in [p['id'] for p in players]:
        await bot.answer_callback_query(callback_query.id, "Ты не в списке игроков!")
        return
    for player in players:
        if player['id'] != user_id:  # Нельзя голосовать за себя
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
            buttons = [types.InlineKeyboardButton(str(i), callback_data=f"rate_{player['id']}_{i}") for i in range(1, 11)]
            keyboard.add(*buttons)
            await bot.send_message(user_id, f"Оцени {player['name']} (1-10):", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id, "Проверь личку для голосования!")

# Сохранение оценок
@dp.callback_query(lambda c: c.data.startswith('rate_'))
async def process_rating(callback_query: types.CallbackQuery):
    data = callback_query.data.split('_')
    player_id = int(data[1])
    rating = int(data[2])
    players_data = load_players()
    for player in players_data['players']:
        if player['id'] == player_id:
            player['ratings'].append(rating)
            save_players(players_data)
            await bot.answer_callback_query(callback_query.id, f"Ты поставил {rating} игроку {player['name']}!")
            return

# Команда /end_voting (админ)
@dp.message(Command(commands=['end_voting']))
async def end_voting(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа, боец!")
        return
    players
