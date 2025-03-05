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
    players = load_players()['players']
    for player in players:
        if player['ratings']:
            avg_rating = sum(player['ratings']) / len(player['ratings'])
            player['stats']['avg_rating'] = avg_rating
            player['ratings'] = []
        else:
            player['stats']['avg_rating'] = 0

    sorted_players = sorted(players, key=lambda p: p['stats']['avg_rating'], reverse=True)
    if sorted_players:
        sorted_players[0]['awards']['mvp'] += 1
        sorted_players[0]['stats']['mvp_count'] += 1
    if len(sorted_players) >= 2:
        sorted_players[1]['awards']['place1'] += 1
    if len(sorted_players) >= 3:
        sorted_players[2]['awards']['place2'] += 1
    if len(sorted_players) >= 4:
        sorted_players[3]['awards']['place3'] += 1

    save_players({"players": players})
    result = "🏆 **Результаты боя**\n\n"
    for i, p in enumerate(sorted_players, 1):
        awards = f" (MVP: {p['awards']['mvp']}, 1st: {p['awards']['place1']}, 2nd: {p['awards']['place2']}, 3rd: {p['awards']['place3']})"
        result += f"{i}. {p['name']} — {p['stats']['avg_rating']:.2f}{awards}\n"
    result += "\n🎖 **Награды**\n"
    if sorted_players: result += f"👑 MVP: {sorted_players[0]['name']}\n"
    if len(sorted_players) >= 2: result += f"🥇 1st: {sorted_players[1]['name']}\n"
    if len(sorted_players) >= 3: result += f"🥈 2nd: {sorted_players[2]['name']}\n"
    if len(sorted_players) >= 4: result += f"🥉 3rd: {sorted_players[3]['name']}\n"
    await bot.send_message(GROUP_ID, result, parse_mode='Markdown')

# Обработка кнопки "Голосование за карты" (админ)
@dp.callback_query(lambda c: c.data == 'start_map_voting')
async def start_map_voting_button(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "❌ У тебя нет доступа!")
        return
    maps = ["Dust2", "Mirage", "Inferno", "Nuke", "Overpass", "Vertigo", "Ancient", "Anubis", "Cache", "Train"]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    for map_name in maps:
        keyboard.add(types.InlineKeyboardButton(map_name, callback_data=f"vote_map_{map_name}"))
    await bot.send_message(GROUP_ID, "🗺 Выбери карты для следующего боя:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

# Команда /start_map_voting (админ)
@dp.message(Command(commands=['start_map_voting']))
async def start_map_voting(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа, боец!")
        return
    maps = ["Dust2", "Mirage", "Inferno", "Nuke", "Overpass", "Vertigo", "Ancient", "Anubis", "Cache", "Train"]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    for map_name in maps:
        keyboard.add(types.InlineKeyboardButton(map_name, callback_data=f"vote_map_{map_name}"))
    await bot.send_message(GROUP_ID, "🗺 Выбери карты для следующего боя:", reply_markup=keyboard)

# Обработка голосов за карты
@dp.callback_query(lambda c: c.data.startswith('vote_map_'))
async def process_map_voting(callback_query: types.CallbackQuery):
    map_name = callback_query.data.split('_')[2]
    maps_data = load_maps()
    maps_data[map_name] += 1
    save_maps(maps_data)
    await bot.answer_callback_query(callback_query.id, f"Ты проголосовал за {map_name}!")

# Команда /end_map_voting (админ)
@dp.message(Command(commands=['end_map_voting']))
async def end_map_voting(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ У тебя нет доступа, боец!")
        return
    maps_data = load_maps()
    sorted_maps = sorted(maps_data.items(), key=lambda x: x[1], reverse=True)[:5]
    result = "🗺 **Топ-5 карт**:\n"
    for i, (map_name, votes) in enumerate(sorted_maps, 1):
        result += f"{i}. {map_name} — {votes} голосов\n"
    await bot.send_message(GROUP_ID, result, parse_mode='Markdown')
    save_maps({map_name: 0 for map_name in maps_data})

# Команда /top
@dp.message(Command(commands=['top']))
async def top_players(message: types.Message):
    players = load_players()['players']
    sorted_players = sorted(players, key=lambda p: p['stats'].get('avg_rating', 0), reverse=True)[:5]
    result = "🏆 **Топ-5 игроков по рейтингу**:\n"
    for i, p in enumerate(sorted_players, 1):
        result += f"{i}. {p['name']} — {p['stats'].get('avg_rating', 0):.2f}\n"
    await message.reply(result, parse_mode='Markdown')

# Команда /my_stats
@dp.message(Command(commands=['my_stats']))
async def my_stats(message: types.Message):
    user_id = message.from_user.id
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
            await message.reply(response, parse_mode='Markdown')
            return
    await message.reply("❌ Ты не в списке игроков!")

# Настройка Webhook
async def on_startup(_):
    await bot.set_webhook(WEBHOOK_URL)
    print(f"Webhook установлен на {WEBHOOK_URL}")

# Запуск бота через aiohttp
app = web.Application()
handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
handler.register(app, path=WEBHOOK_PATH)
setup_application(app, dp, bot=bot)

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    web.run_app(app, host='0.0.0.0', port=port)
