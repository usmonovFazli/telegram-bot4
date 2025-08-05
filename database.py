import psycopg2
import os
from dotenv import load_dotenv
load_dotenv()

DB_PARAMS = {
    "dbname": os.getenv("PG_DB"),
    "user": os.getenv("PG_USER"),
    "password": os.getenv("PG_PASSWORD"),
    "host": os.getenv("PG_HOST"),
    "port": os.getenv("PG_PORT"),
}


def connect():
    return psycopg2.connect(**DB_PARAMS)


def init_db():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    id BIGINT PRIMARY KEY,
                    title TEXT,
                    members INTEGER,
                    videos INTEGER DEFAULT 0,
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    type TEXT DEFAULT 'unknown',
                    link TEXT DEFAULT ''
                );
            """)
        conn.commit()


def add_or_update_channel(chat_id, title, members, chat_type="unknown", link=""):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO channels (id, title, members, type, link)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET title = EXCLUDED.title,
                    members = EXCLUDED.members,
                    type = EXCLUDED.type,
                    link = EXCLUDED.link;
            """, (chat_id, title, members, chat_type, link))
        conn.commit()


def update_channel_status(chat_id, title=None, members=None, chat_type=None, link=None):
    with connect() as conn:
        with conn.cursor() as cur:
            updates = []
            values = []

            if title is not None:
                updates.append("title = %s")
                values.append(title)
            if members is not None:
                updates.append("members = %s")
                values.append(members)
            if chat_type is not None:
                updates.append("type = %s")
                values.append(chat_type)
            if link is not None:
                updates.append("link = %s")
                values.append(link)

            if not updates:
                return

            values.append(chat_id)
            query = f"""
                UPDATE channels SET {', '.join(updates)} WHERE id = %s;
            """
            cur.execute(query, values)
        conn.commit()


def increment_video_count(chat_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE channels SET videos = videos + 1 WHERE id = %s;
            """, (chat_id,))
        conn.commit()


def get_channels():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, members, videos, date_added, type, link
                FROM channels ORDER BY title;
            """)
            return cur.fetchall()
