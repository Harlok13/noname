import asyncio
import logging

from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aioredis import Redis
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import sessionmaker

from julia_bot.apps.library.middlewares.mw_library import LibraryMenu
from julia_bot.apps.trigger.middlewares.mw_triggers import Trigger
from julia_bot.data.engine import create_async_engine, get_session_maker
from julia_bot.middlewares.mw_user_register_check import UserRegisterCheck
# Импорт настроек apps. Должен быть выше остальных импортов.
from julia_bot.settings import *

from julia_bot.config_reader import config

if trigger_app:
    from julia_bot.apps.trigger.handlers.trigger_cmd_handler import register_trigger_message_handler

if library_app:
    from julia_bot.apps.library.handlers.library_cb_handler import register_library_cb_handlers
    # from julia_bot.apps.library.handlers.library_msg_handler import register_library_msg_handlers
    from julia_bot.apps.library.handlers.library_cmd_handler import register_library_cmd_handlers

from julia_bot.handlers.callback_handlers import register_callback_handlers
from julia_bot.handlers.message_handler import register_message_handlers
from julia_bot.handlers.command_handler import register_command_handler

from julia_bot.keyboards.set_menu import set_main_menu

logger: logging.Logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level='INFO',
        format=u'%(filename)s:%(lineno)d #%(levelname)-8s '
               u'[%(asctime)s] - %(name)s - %(message)s'
    )
    logger.info('is started')

    bot = Bot(config.bot_token, parse_mode='HTML')

    redis: Redis = Redis().from_url(config.redis_dsn)
    logger.info(config.redis_dsn)

    match config.bot_fsm_storage:
        case 'redis':
            logger.info('redis enabled')
            dp: Dispatcher = Dispatcher(storage=RedisStorage.from_url(config.redis_dsn))
        case _:
            logger.info('memory enabled')
            dp: Dispatcher = Dispatcher(storage=MemoryStorage())

    # register mw
    dp.callback_query.middleware(LibraryMenu())  # type: ignore
    dp.message.middleware(UserRegisterCheck())
    dp.callback_query.middleware(UserRegisterCheck())
    dp.message.middleware(Trigger())

    # register router
    register_callback_handlers(dp)
    register_message_handlers(dp)
    register_command_handler(dp)

    if library_app:
        logger.info('library app enabled')
        register_library_cb_handlers(dp)
        # register_library_msg_handlers(dp)
        register_library_cmd_handlers(dp)

    if trigger_app:
        logger.info('trigger app enabled')
        register_trigger_message_handler(dp)

    # register bot cmd
    await set_main_menu(bot)

    # include postgres
    async_engine: AsyncEngine = create_async_engine(config.postgres_dsn)
    session_maker: sessionmaker = get_session_maker(async_engine)
    # delegated alembic
    # await proceed_schemas(async_engine, BaseModel.metadata)

    try:
        if not config.webhook_domain:
            logger.info('webhook domain not set')
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                session_maker=session_maker,
                redis=redis
            )
        else:
            logger.info('webhook domain set')
            aiohttp_logger = logging.getLogger('aiohttp.access')
            aiohttp_logger.setLevel(level='FATAL')

            await bot.set_webhook(
                url=f'{config.webhook_domain}{config.webhook_path}',
                allowed_updates=dp.resolve_used_update_types(),
                drop_pending_updates=True
            )

            # aiohttp app

    finally:
        logger.info('finally closing connection')
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as exc:
        logger.error(exc)
        logger.info('close connection')
