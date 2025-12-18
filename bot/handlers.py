import asyncio, json
from telebot.util import quick_markup
from telebot.types import Message

from .api import get_comment, get_info, get_user_karma
from .commands import cmds
from config import (
    DEFAULT_PAGE_SIZE,
    GENERIC_ERROR_MESSAGE,
    TG_BOT_CALLBACK_LINK,
    bot,
    logger,
    MONGO_DB_NAME,
    ME
)
from .middleware import rate_limiter
from .utils import get_args, template, user_url, item_url, parse_xml
from database import Database, MongoDatabase
from .jobs import execute_job


async def list_comments(iid, message: Message, page=0):

    message = await bot.send_message(message.chat.id, text="Fetching comments...")

    res = await asyncio.create_task(get_info(iid))
    if res.status_code != 200:
        logger.error(f"An error occurred: {res.status_code} - list_comments")
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message.message_id,
            text="Failed to fetch story. Please check the story id is correct",
        )
        return

    item = json.loads(res.content)
    with MongoDatabase(MONGO_DB_NAME) as db:
        page_size = await get_page_size(db, message.chat.id) or DEFAULT_PAGE_SIZE
    kids, title = item["kids"][page : page + page_size], item["title"]

    if not kids:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message.message_id,
            text="No comments found" if page == 0 else "No more comments",
        )
        return

    logger.debug("Fetching comments...")
    tasks = [asyncio.create_task(get_comment(kid)) for kid in kids]
    for i, task in enumerate(tasks):

        comment = await task
        if comment.status_code != 200:
            logger.error(f"An error occurred: {comment.status_code} - list_comments")
            continue

        if i == 0:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=message.message_id,
                text=f"*Story: {title}*\n*Comments* `{page+1} - {page+page_size}`",
                parse_mode="Markdown",
            )

        comment = json.loads(comment.content)
        if comment.get("deleted", False):
            continue

        msg = template(
            user_url(comment.get("by", "")),
            get_user_karma(comment.get("by", "")),
            comment.get("by", "user not found"),
            parse_xml(comment.get("text", "text not found")),
            comment["time"],
        )

        kid = comment["id"]
        markup = quick_markup(
            {
                "Read on site": {"url": item_url(kid)},
                "Bookmark comment": {"callback_data": f"bookmark_{kid}"},
            },
            row_width=2,
        )

        try:
            await bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            logger.warning(f"An error occurred while parsing: {str(e)} - list_comments")
            await bot.reply_to(message, msg, reply_markup=markup)

    cmd = cmds["list"]["name"]
    next_btn = quick_markup(
        {
            f"Next {page_size} comments": {
                "callback_data": f"{cmd}_{iid}_{page+page_size}"
            },
            "Bookmark Story": {"callback_data": f"bookmark_{iid}"},
        },
        row_width=2,
    )
    await bot.send_message(
        message.chat.id, text=f"What do you want to do?", reply_markup=next_btn
    )


async def save_story(db: Database, iid, userid):
    res = await get_info(iid)
    if res.status_code != 200 or res.content == b"null":
        logger.warning(f"Failed to fetch story: {iid} - save_story")
        return False

    res = db.insert_bookmark(userid, iid)
    if not res:
        logger.warning(
            f"Failed to create bookmark: userid={userid}, iid={iid} - save_story"
        )
    return res


async def delete_story(db: Database, iid, userid):
    res = db.delete_bookmark(iid, userid)
    if not res:
        logger.warning(
            f"Failed to delete bookmark: userid={userid}, iid={iid} - delete_story"
        )
    return res


async def list_bookmarks(db: Database, userid):
    res = db.search_bookmark(userid)
    return res


async def get_page_size(db: Database, userid):
    res = db.search_page(userid)
    if res:
        return res["page"]
    return None


async def set_page_size(db: Database, userid, page_size):
    res = db.upsert_page(userid, page_size)
    if not res:
        logger.warning(
            f"Failed to set page size: userid={userid}, page_size={page_size} - set_page_size"
        )
    return res


async def fetch_bookmarks(
    chat_id,
):
    try:
        with MongoDatabase(MONGO_DB_NAME) as db:
            res = await list_bookmarks(db, chat_id)
            if not res:
                await bot.send_message(chat_id, text="No bookmarks found")
                return

            msg = "Bookmarks:\n\n"
            tasks = [asyncio.create_task(get_info(row["iid"])) for row in res]
            for i, row in enumerate(res):
                iid = row["iid"]

                story = await tasks[i]
                if (story.status_code != 200) or (not story.content):
                    logger.warning(f"Failed to fetch story: {iid} - bookmarks")
                    continue

                story = json.loads(story.content)
                if story["type"] != "comment":
                    story_title = story["title"]
                else:
                    story_title = story["text"][:50] + (
                        "..." if len(story["text"]) > 25 else ""
                    )
                type = story["type"]
                delete_cb_link = TG_BOT_CALLBACK_LINK.format(f"del_{iid}")
                visite_site_link = item_url(iid)
                msg += f"{i + 1}. [{story_title}]({item_url(iid)})\n [🔗 visit]({visite_site_link}) | [🗑 remove]({delete_cb_link})\n\n"
            msg = parse_xml(msg)
            await bot.send_message(
                chat_id,
                text=msg,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.error(f"An error occurred: {str(e)} - bookmarks")
        await bot.send_message(chat_id, text=GENERIC_ERROR_MESSAGE)


# handlers


@bot.message_handler(commands=["start"])
@rate_limiter
async def send_welcome(message):

    if not isinstance(message, Message):
        logger.warning("param is not type of telebot.types.Message")
    try:
        args = get_args(message.text)
        if args:
            if args[0].startswith(cmds["list"]["name"]):
                iid, *_ = get_args(args[0], delimiter="_")
                await list_comments(iid, message)
            elif args[0].startswith(cmds["bookmark"]["name"]):
                iid, *_ = get_args(args[0], delimiter="_")
                with MongoDatabase(MONGO_DB_NAME) as db:
                    await save_story(db, iid, message.chat.id)
                await bot.send_message(message.chat.id, text="Story bookmarked")
            elif args[0].startswith(cmds["delete"]["name"]):
                iid, *_ = get_args(args[0], delimiter="_")
                with MongoDatabase(MONGO_DB_NAME) as db:
                    await delete_story(db, iid, message.chat.id)
                await bot.send_message(message.chat.id, text=f"Bookmark removed.")

            else:
                logger.warning(f"Invalid command: {args[0]} - send_welcome")
            return

        text = "Welcome! See /help to see all commands.\n\n"
        await bot.send_message(chat_id=message.chat.id, text=text)

    except Exception as e:
        logger.error(f"An error occurred: {str(e)} - send_welcome")
        await bot.send_message(message.chat.id, text=GENERIC_ERROR_MESSAGE)
        return


@bot.message_handler(commands=[cmds["help"]["name"]])
@rate_limiter
async def help(message):
    text = "**Commands**:\n\n"
    for cmd in cmds.values():
        text += f"/{cmd['name']} - {cmd['description']}\n"
        if cmd.get("usage"):
            text += f"Usage: {cmd['usage']}\n"
        text += "\n"

    await bot.send_message(message.chat.id, text, parse_mode="Markdown")


@bot.message_handler(commands=[cmds["list"]["name"]])
@rate_limiter
async def get_comments(message):
    try:
        args = get_args(message.text)
        iid, *(opts) = args

        page = int(opts[0]) if opts else 0
        await list_comments(iid, message, page=page)
    except Exception as e:
        logger.error(f"An error occurred: {str(e)} - get_comments")
        await bot.send_message(message.chat.id, text=GENERIC_ERROR_MESSAGE)


@bot.callback_query_handler(
    func=lambda call: call.data.startswith(cmds["list"]["name"])
)
async def list_callback(call):
    try:
        _, iid, *args = call.data.split("_")
        page = int(args[0]) if args else 0
        await list_comments(iid, call.message, page=page)
    except Exception as e:
        logger.error(f"An error occurred: {str(e)} - list_callback")
        await bot.send_message(call.message.chat.id, text=GENERIC_ERROR_MESSAGE)


@bot.callback_query_handler(
    func=lambda call: call.data.startswith(cmds["bookmark"]["name"])
)
async def bookmark_callback(call):
    try:
        _, iid, *_ = call.data.split("_")
        with MongoDatabase(MONGO_DB_NAME) as db:
            await save_story(db, iid, call.message.chat.id)
        await bot.send_message(call.message.chat.id, text="Item bookmarked")
        await fetch_bookmarks(call.message.chat.id)
    except Exception as e:
        logger.error(f"An error occurred: {str(e)} - bookmark_callback")
        await bot.send_message(call.message.chat.id, text=GENERIC_ERROR_MESSAGE)


@bot.message_handler(commands=[cmds["bookmark"]["name"]])
@rate_limiter
async def bookmark(message):
    try:
        args = get_args(message.text)
        if not args:
            await bot.send_message(message.chat.id, text="Please provide a story id")
            return

        await bot.send_message(message.chat.id, text="Bookmarking story...")
        iid = args[0]
        if not iid.isdigit():
            await bot.send_message(
                message.chat.id, text="Please provide a valid story id"
            )
            return

        item = await get_info(iid)
        logger.debug(item.content)
        if item.status_code != 200 or item.content == b"null":
            logger.warning(f"Failed to fetch story: {iid} - bookmark")
            await bot.send_message(
                message.chat.id,
                text="Failed to fetch story. Please check the story id is correct",
            )
            return

        with MongoDatabase(MONGO_DB_NAME) as db:
            res = await save_story(db, iid, message.chat.id)
            if not res:
                logger.warning("Failed to create bookmark - bookmark")
                await bot.send_message(
                    message.chat.id,
                    text="Failed to create bookmark. Check if story is already bookmarked by using /bookmarks",
                )
                return

        await bot.send_message(message.chat.id, text="Story bookmarked")
        await fetch_bookmarks(message.chat.id)

    except Exception as e:
        logger.error(f"An error occurred: {str(e)} - bookmark")
        await bot.send_message(message.chat.id, text=GENERIC_ERROR_MESSAGE)


@bot.message_handler(commands=[cmds["bookmarks"]["name"]])
@rate_limiter
async def bookmarks(message):
    await fetch_bookmarks(message.chat.id)


@bot.message_handler(commands=[cmds["delete"]["name"]])
@rate_limiter
async def delete(message):
    try:
        args = get_args(message.text)
        if not args:
            await bot.send_message(message.chat.id, text="Please provide a bookmark id")
            return

        with MongoDatabase(MONGO_DB_NAME) as db:
            res = await delete_story(db, args[0], message.chat.id)
            if not res:
                logger.warning(
                    f"Failed to delete bookmark - iid: {args[0]}, userid:{message.chat.id} -  delete"
                )
                await bot.send_message(
                    message.chat.id,
                    text="Failed to delete bookmark. Check if bookmark exists by using /bookmarks",
                )
                return

        await bot.send_message(message.chat.id, text="Bookmark deleted")

    except Exception as e:
        logger.error(f"An error occurred: {str(e)} - delete")
        await bot.send_message(message.chat.id, text=GENERIC_ERROR_MESSAGE)


@bot.message_handler(commands=[cmds["setpage"]["name"]])
@rate_limiter
async def set_page(message):
    try:
        args = get_args(message.text)
        if not args:
            await bot.send_message(message.chat.id, text="Please provide a page size")
            return

        try:
            x = int(args[0])
            with MongoDatabase(MONGO_DB_NAME) as db:
                res = await set_page_size(db, message.chat.id, x)
                if not res:
                    await bot.send_message(
                        message.chat.id,
                        text="Failed to set page size. Please try again",
                    )
                    return
        except ValueError:
            await bot.send_message(
                message.chat.id, text="Please provide a valid number"
            )
            return
        except Exception as e:
            await bot.send_message(message.chat.id, text=f"An error occurred: {str(e)}")
            return

        await bot.send_message(message.chat.id, text="Page size set")
    except Exception as e:
        logger.error(f"An error occurred: {str(e)} - set_page")
        await bot.send_message(message.chat.id, text=GENERIC_ERROR_MESSAGE)


@bot.message_handler(commands=[cmds["deleteall"]["name"]])
@rate_limiter
async def delete_all(message):
    try:
        with MongoDatabase(MONGO_DB_NAME) as db:
            res = db.delete_all_bookmarks(message.chat.id)
            if not res:
                await bot.send_message(
                    message.chat.id, text="Failed to delete all bookmarks"
                )
                return

        await bot.send_message(message.chat.id, text="All bookmarks deleted")
    except Exception as e:
        logger.error(f"An error occurred: {str(e)} - delete_all")
        await bot.send_message(message.chat.id, text=GENERIC_ERROR_MESSAGE)


@bot.message_handler(commands=['sync'])
@rate_limiter
async def sync_db(message):
    if(message.from_user.id != int(ME)):
        return
    await execute_job(force=True)
