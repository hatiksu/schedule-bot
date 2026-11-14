from aiogram import Dispatcher

import modules


def test_all_routers_attach():
    assert len(modules.ROUTERS) >= 25
    names = [r.name for r in modules.ROUTERS]
    assert len(names) == len(set(names)), "у двух модулей один и тот же роутер"
    dp = Dispatcher()
    modules.setup(dp)
    assert len(dp.sub_routers) == len(modules.ROUTERS)
