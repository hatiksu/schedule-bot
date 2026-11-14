from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from config import ADMIN_IDS


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and user.id in ADMIN_IDS)
