import asyncio
import datetime
import aiohttp
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.commands import cmds

from config import (
    BASE_API_URL,
    CHANNEL_ID,
    MONGO_DB_NAME,
    TG_BOT_CALLBACK_LINK,
    TOP_STORY_SCORE,
    bot,
    logger,
)
from bot.utils import slug
from database import MongoDatabase
import tldextract

async def make_req(url, session):
    async with session.get(url) as response:
        if response.status != 200:
            logger.error("Error: %s, make_req", response.status)
            return []
        return await response.json()


def filter_posted(all_top_stories):
    all_top_stories = list(map(str, all_top_stories))
    with MongoDatabase(MONGO_DB_NAME) as db:
        return set(all_top_stories) - set(db.search_stories(all_top_stories))

async def execute_job(force=False):

    logger.debug("Getting cron request...")
    url = BASE_API_URL + "topstories.json"
    async with aiohttp.ClientSession() as hn_session:
        all_top_stories = await make_req(url, hn_session)
        top_stories = filter_posted(all_top_stories)

        urls = list(map(lambda x: BASE_API_URL + slug("item", x), top_stories))
        tasks = [asyncio.create_task(make_req(url, hn_session)) for url in urls]
        posted = []

        # a different session has to be used for telegram otherwise telebot destroys session for message handlers
        async with aiohttp.ClientSession() as tg_session:
            while tasks:

                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                logger.debug("Remaining: %d/%d", len(tasks), len(top_stories))
                for task in done:
                    story = await task

                    if not story:
                        logger.error("Failed to get story")
                        tasks.remove(task)
                        continue

                    if (
                        story.get("score", None) is None
                        or story["score"] < TOP_STORY_SCORE
                    ):
                        logger.debug("Story score is too low or undefined")
                        tasks.remove(task)
                        continue

                    if story.get("deleted", False):
                        tasks.remove(task)
                        logger.debug("Story is deleted")
                        continue

                    now = datetime.datetime.now()
                    published = datetime.datetime.fromtimestamp(story["time"])
                    time_diff = now - published
                    hrs = int(time_diff.total_seconds()) // 3600
                    mins = int(time_diff.total_seconds()) // 60
                    display_time = (
                        str(mins) + " minute" + ("s" if mins > 1 else "")
                        if mins < 60
                        else (
                            str(hrs) + " hour" + ("s" if hrs > 1 else "")
                            if hrs < 24
                            else str(time_diff.days) + " days"
                        )
                    )

                    activity = ""
                    if hrs <= 3:
                        activity = "🔥"
                    if hrs <= 2:
                        activity = "🔥🔥"
                    if hrs <= 1:
                        activity = "🔥🔥🔥"
                        if story["score"] >= 300:
                            activity = "🔥🔥🔥🔥"

                    if time_diff.days >= 7:
                        activity = "❄️"

                    msg = (
                        f"*{story['title']}*\n"
                        f"`- score: {story['score']} {activity}`\n"
                        f"`- posted: {display_time} ago`\n\n"
                    )
                    if story.get("url", None):
                        u = tldextract.extract(story["url"])
                        domain = u.domain
                        if u.suffix:
                            domain += "." + u.suffix

                        msg += "Read: |" + f"[{domain}]({story['url']})" + "|"

                    markup = InlineKeyboardMarkup()
                    markup.row_width = 1

                    markup.add(
                        InlineKeyboardButton(
                            text="Read Later",
                            url=TG_BOT_CALLBACK_LINK.format(
                                f"{cmds['bookmark']['name']}_" + str(story["id"])
                            ),
                        ),
                        InlineKeyboardButton(
                            text=f"Comments({len(story.get('kids', []))}+)",
                            url=TG_BOT_CALLBACK_LINK.format(
                                f"{cmds['list']['name']}_" + str(story["id"])
                            ),
                        ),
                        InlineKeyboardButton(
                            text="Read on HN",
                            url=f"https://news.ycombinator.com/item?id={story['id']}",
                        ),
                        row_width=2,
                    )

                    payload = {
                        "chat_id": CHANNEL_ID,
                        "text": msg,
                        "parse_mode": "Markdown",
                        "reply_markup": markup.to_dict(),
                    }

                    if force:
                        posted.append(str(story["id"]))
                        tasks.remove(task)
                    else:
                        async with tg_session.post(
                            f"https://api.telegram.org/bot{bot.token}/sendMessage",
                            json=payload,
                        ) as response:
                            if response.status != 200:
                                logger.error(
                                    "Failed to send message: %s", await response.text()
                                )

                                logger.debug(f"{len(posted)} messages are posted")
                                response_data = await response.json(
                                    encoding=response.get_encoding()
                                )
                                if response_data.get("error_code", None) == 429:
                                    logger.error("Rate limit exceeded")
                                    try:
                                        with MongoDatabase(MONGO_DB_NAME) as db:
                                            logger.debug("Saving posts in database in the mean time...")
                                            db.post_stories(posted)
                                            logger.debug(f"{len(posted)} postes saved to database")
                                            posted = []
                                    except Exception as e:
                                        logger.error("Failed to post story: %s", e)

                                    await asyncio.sleep(
                                        response_data["parameters"]["retry_after"] + 1
                                    )

                            else:
                                posted.append(str(story["id"]))
                                tasks.remove(task)

            logger.debug("loop exit")
            try:
                with MongoDatabase(MONGO_DB_NAME) as db:
                    db.post_stories(posted)
            except Exception as e:
                logger.error("Failed to post story: %s", e)
