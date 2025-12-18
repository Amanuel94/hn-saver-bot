import asyncio
import atexit
import datetime
import aiohttp
import time
from flask import Flask, request

import threading

from telebot.types import Update
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.commands import cmds
from bot.jobs import execute_job

from config import (
    API_TOKEN,
    BASE_API_URL,
    CHANNEL_ID,
    DEVELOPMENT,
    MONGO_DB_NAME,
    TG_BOT_CALLBACK_LINK,
    TOP_STORY_SCORE,
    HOST,
    PORT,
    WEBHOOK_URL,
    WEBHOOK_ROUTE,
    bot,
    logger,
)
from bot.middleware import resetter
from bot.utils import slug
from database import Database, MongoDatabase
import tldextract


async def config_webhook():

    # logger.debug("webhook url: ", WEBHOOK_URL, WEBHOOK_ROUTE)
    res = await bot.set_webhook(WEBHOOK_URL + WEBHOOK_ROUTE)
    if not res:
        raise Exception("Couldn't set webhook")
    info = await bot.get_webhook_info()
    logger.debug(info)


def setup():
    logger.debug("Setting up webhook...")
    asyncio.run(config_webhook())


app = Flask(__name__)
setup()


@app.route(f"/{WEBHOOK_ROUTE}", methods=["POST"])
@resetter
async def webhook():
    logger.debug("Getting request...")
    logger.debug(request.headers)

    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True))
        logger.debug("Procesing Updates...")
        res = await bot.process_new_updates(updates=[update])
        return "OK"


@app.route("/test", methods=["GET"])
def test():
    logger.debug("Getting test request...")
    return "Test"




@app.route("/cron", methods=["GET", "HEAD"])
async def cron():
    logger.debug("Getting cron request...")
    logger.debug(request.headers)
    try:
        token = request.authorization.password
    except AttributeError:
        return "Unauthorized", 401

    if token != API_TOKEN:
        return "Unauthorized", 401

    thread = threading.Thread(target=lambda: asyncio.run(execute_job()))
    thread.daemon = True
    thread.start()
    return "OK"


@app.route("/force-cron", methods=["GET", "HEAD"])
async def force_cron():
    logger.warn("Getting forced cron request...")
    logger.debug(request.headers)
    try:
        token = request.authorization.password
    except AttributeError:
        return "Unauthorized", 401

    if token != API_TOKEN:
        return "Unauthorized", 401

    thread = threading.Thread(target=lambda: asyncio.run(execute_job(force=True)))
    thread.daemon = True
    thread.start()
    return "OK"



async def delete_webhook():
    res = await bot.delete_webhook(drop_pending_updates=True)
    if not res:
        logger.warning("Couldn't delete webhook")


def create_app():
    setup()
    return app


@atexit.register
def teardown():
    logger.debug("Closing client connection")
    logger.debug(asyncio.run(bot.close_session()))


if __name__ == "__main__":
    if DEVELOPMENT == "True":
        app.run(host=HOST, port=PORT, debug=True)
