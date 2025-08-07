import sqlite3
from contextlib import ContextDecorator

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

from config import MONGO_URL, logger


class Database(ContextDecorator):

    def __init__(self, db):
        self.conn = sqlite3.connect(db)
        self.cur = self.conn.cursor()
        self.cur.execute(
            "CREATE TABLE IF NOT EXISTS bookmarks (id INTEGER PRIMARY KEY, userid INTEGER, iid INTEGER);"
        )

        self.cur.execute(
            "CREATE TABLE IF NOT EXISTS pages (id INTEGER PRIMARY KEY, userid INTEGER, page INTEGER);"
        )
        self.conn.commit()

    def insert_bookmark(self, userid, iid):
        try:
            self.cur.execute(
                "SELECT * FROM bookmarks WHERE userid=? AND iid=?",
                (userid, iid),
            )
            rows = self.cur.fetchall()
            if rows:
                print(f"Record already exists: {rows}")
                return False

            self.cur.execute(
                "INSERT INTO bookmarks (userid, iid) VALUES (?, ?)",
                (userid, iid),
            )
            self.conn.commit()
            logger.info("Record inserted: userid=%s, iid=%s", userid, iid)
            return True
        except sqlite3.Error as e:
            logger.error(
                "Database error: %s - insert_bookmark: userid=%s, iid=%s",
                e,
                userid,
                iid,
            )
            return False
        except Exception as e:
            logger.error(
                f"Unexpected error: {e} - insert_bookmark: userid={userid}, iid={iid}"
            )
            return False

    def search_bookmark(self, userid=""):
        try:
            self.cur.execute(
                "SELECT * FROM bookmarks WHERE userid=?",
                (userid,),
            )
            rows = self.cur.fetchall()
            logger.info(f"Record found: userid={userid}, rows={rows}")
            return rows
        except sqlite3.Error as e:
            logger.error(f"Database error: {e} - search_bookmark: userid={userid}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error: {e} - search_bookmark: userid={userid}")
            return []

    def delete_bookmark(self, iid, userid):
        try:
            self.cur.execute(
                "DELETE FROM bookmarks WHERE iid=? AND userid = ? ", (iid, userid)
            )
            self.conn.commit()
            logger.info(f"Record deleted: userid={userid}, iid={iid}")
            return True
        except sqlite3.Error as e:
            logger.error(
                f"Database error: {e} - delete_bookmark: userid={userid}, iid={iid}"
            )
            return False
        except Exception as e:
            logger.error(
                f"Unexpected error: {e} - delete_bookmark: userid={userid}, iid={iid}"
            )
            return False

    def delete_all_bookmarks(self, userid):
        try:
            self.cur.execute("DELETE FROM bookmarks WHERE userid = ? ", (userid,))
            self.conn.commit()
            logger.info(f"All records deleted: userid={userid}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Database error: {e} - delete_all_bookmarks: userid={userid}")
            return False
        except Exception as e:
            logger.error(
                f"Unexpected error: {e} - delete_all_bookmarks: userid={userid}"
            )
            return False

    def search_page(self, userid):
        try:
            self.cur.execute(
                "SELECT * FROM pages WHERE userid=?",
                (userid,),
            )
            rows = self.cur.fetchall()
            return rows
        except sqlite3.Error as e:
            logger.error(f"Database error: {e} - search_page: userid={userid}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error: {e} - search_page: userid={userid}")
            return []

    def upsert_page(self, userid, page):
        try:
            self.cur.execute(
                "SELECT * FROM pages WHERE userid=?",
                (userid,),
            )
            rows = self.cur.fetchall()
            if rows:
                self.cur.execute(
                    "UPDATE pages SET page=? WHERE userid=?",
                    (page, userid),
                )
                self.conn.commit()
                logger.info(f"Record updated: userid={userid}, page={page}")
                return True

            self.cur.execute(
                "INSERT INTO pages (userid, page) VALUES (?, ?)",
                (userid, page),
            )
            self.conn.commit()
            logger.info(f"Record inserted: userid={userid}, page={page}")
            return True
        except sqlite3.Error as e:
            logger.error(
                f"Database error: {e} - upsert_page: userid={userid}, page={page}"
            )
            return False
        except Exception as e:
            logger.error(
                f"Unexpected error: {e} - upsert_page: userid={userid}, page={page}"
            )
            return False

    def __del__(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.conn.close()
        return False


class MongoDatabase(ContextDecorator):

    def __init__(self, db):
        try:
            self.client = MongoClient(MONGO_URL)
            self.bookmarks = self.client[db]["bookmarks"]
            self.pages = self.client[db]["pages"]
            self.stories = self.client[db]["stories"]

            try:
                # The ping command is cheap and does not require auth.
                self.client.admin.command('ping')
            except ConnectionFailure:
                logger.error("Error Connecting to MongoDB: Server not available")
            self.bookmarks.create_index([("userid", 1), ("iid", 1)], unique=True)
            self.stories.create_index("id", unique=True)
            return
        except Exception as e:
            logger.error(f"error occured while trying to connect to mongo database: {e}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.client.close()
        return False

    def __del__(self):
        self.client.close()
        return False

    def insert_bookmark(self, userid, iid):
        try:
            self.bookmarks.insert_one({"userid": userid, "iid": iid})
            logger.info("Record inserted: userid=%s, iid=%s", userid, iid)
            return True
        except Exception as e:
            logger.error(
                f"Unexpected error: {e} - insert_bookmark: userid={userid}, iid={iid}"
            )
            return False

    def search_bookmark(self, userid=""):
        try:
            rows = self.bookmarks.find({"userid": userid})
            logger.info(f"Record found: userid={userid}, rows={rows}")
            return list(rows)
        except Exception as e:
            logger.error(f"Unexpected error: {e} - search_bookmark: userid={userid}")
            return []

    def delete_bookmark(self, iid, userid):
        try:
            self.bookmarks.delete_one({"iid": iid, "userid": userid})
            logger.info(f"Record deleted: userid={userid}, iid={iid}")
            return True
        except Exception as e:
            logger.error(
                f"Unexpected error: {e} - delete_bookmark: userid={userid}, iid={iid}"
            )
            return False

    def delete_all_bookmarks(self, userid):
        try:
            self.bookmarks.delete_many({"userid": userid})
            logger.info(f"All records deleted: userid={userid}")
            return True
        except Exception as e:
            logger.error(
                f"Unexpected error: {e} - delete_all_bookmarks: userid={userid}"
            )
            return False

    def search_page(self, userid):
        try:
            rows = list(self.pages.find({"userid": userid}))
            if not rows:
                return []
            logger.info(f"Record found: userid={userid}, rows={rows}")
            return rows[0]
        except Exception as e:
            logger.error(f"Unexpected error: {e} - search_page: userid={userid}")
            return []

    def upsert_page(self, userid, page):
        try:
            self.pages.update_one(
                {"userid": userid}, {"$set": {"page": page}}, upsert=True
            )
            logger.info(f"Record updated: userid={userid}, page={page}")
            return True
        except Exception as e:
            logger.error(
                f"Unexpected error: {e} - upsert_page: userid={userid}, page={page}"
            )
            return False

    def post_stories(self, stories):
        if not stories:
            return
        try:
            self.stories.insert_many([{"id": str(story)} for story in stories])
            logger.info(f"Record inserted: stories={stories}")
            return True
        except Exception as e:
            logger.error(f"Unexpected error: {e} - post_stories: stories={stories}")

    def search_stories(self, story_ids):
        try:
            rows = list(
                self.stories.find({"id": {"$in": story_ids}}, projection={"_id": False})
            )
            if not rows:
                return set([])
            logger.info(f"Returning {len(rows)} records")
            return set([item["id"] for item in rows])
        except Exception as e:
            logger.error(
                f"Unexpected error: {e} - search_many_stories: story_ids={story_ids}"
            )
            return []
