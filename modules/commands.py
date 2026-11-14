"""📋 Меню команд бота (у админов дополнительно /admin)."""
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat, MenuButtonCommands

from config import ADMIN_IDS

COMMANDS = [
    BotCommand(command="start", description="Моё расписание"),
    BotCommand(command="settings", description="Настройки, уведомления, авторассылка"),
    BotCommand(command="bells", description="Звонки и сколько до конца пары"),
    BotCommand(command="premium", description="⭐ Premium: темы, напоминания, избранное"),
    BotCommand(command="fav", description="⭐ Избранное"),
    BotCommand(command="invite", description="🤝 Пригласить друзей — получить Premium"),
    BotCommand(command="achievements", description="🏆 Достижения"),
    BotCommand(command="widget", description="📱 Виджет дня в чате"),
    BotCommand(command="homewidget", description="📲 Виджет на экран телефона"),
    BotCommand(command="feedback", description="Сообщить об ошибке / идея"),
    BotCommand(command="help", description="Как пользоваться"),
]


async def setup(bot: Bot) -> None:
    await bot.set_my_commands(COMMANDS)
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(COMMANDS + [BotCommand(command="admin", description="🛠 Админ-панель")],
                                      scope=BotCommandScopeChat(chat_id=admin_id))
        except TelegramAPIError:
            pass  # админ ещё не писал боту
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
