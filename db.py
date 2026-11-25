import os
import sqlite3
from contextlib import closing

DB_PATH = os.getenv("DB_PATH", "homework.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(_conn()) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                username TEXT
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                deadline TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES tasks(id),
                user_id INTEGER NOT NULL REFERENCES users(id),
                content_type TEXT NOT NULL,      -- text | photo | document
                text TEXT,
                file_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',  -- pending | graded | redo
                grade TEXT,
                comment TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        c.commit()


# ---------- users ----------
def upsert_user(user_id: int, full_name: str, username: str | None):
    with closing(_conn()) as c:
        c.execute(
            """INSERT INTO users (id, full_name, username) VALUES (?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET full_name=excluded.full_name,
                                             username=excluded.username""",
            (user_id, full_name, username),
        )
        c.commit()


def all_user_ids() -> list[int]:
    with closing(_conn()) as c:
        return [r["id"] for r in c.execute("SELECT id FROM users")]


# ---------- tasks ----------
def add_task(title: str, description: str, deadline: str | None) -> int:
    with closing(_conn()) as c:
        cur = c.execute(
            "INSERT INTO tasks (title, description, deadline) VALUES (?, ?, ?)",
            (title, description, deadline),
        )
        c.commit()
        return cur.lastrowid


def get_task(task_id: int):
    with closing(_conn()) as c:
        return c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()


def active_tasks():
    with closing(_conn()) as c:
        return c.execute(
            "SELECT * FROM tasks WHERE active=1 ORDER BY id DESC"
        ).fetchall()


def close_task(task_id: int) -> bool:
    with closing(_conn()) as c:
        cur = c.execute("UPDATE tasks SET active=0 WHERE id=?", (task_id,))
        c.commit()
        return cur.rowcount > 0


# ---------- submissions ----------
def get_user_submission(task_id: int, user_id: int):
    with closing(_conn()) as c:
        return c.execute(
            """SELECT * FROM submissions WHERE task_id=? AND user_id=?
               ORDER BY id DESC LIMIT 1""",
            (task_id, user_id),
        ).fetchone()


def add_submission(task_id, user_id, content_type, text, file_id) -> int:
    with closing(_conn()) as c:
        cur = c.execute(
            """INSERT INTO submissions (task_id, user_id, content_type, text, file_id)
               VALUES (?, ?, ?, ?, ?)""",
            (task_id, user_id, content_type, text, file_id),
        )
        c.commit()
        return cur.lastrowid


def get_submission(sub_id: int):
    with closing(_conn()) as c:
        return c.execute(
            """SELECT s.*, u.full_name, u.username, t.title AS task_title
               FROM submissions s
               JOIN users u ON u.id = s.user_id
               JOIN tasks t ON t.id = s.task_id
               WHERE s.id=?""",
            (sub_id,),
        ).fetchone()


def pending_submissions():
    with closing(_conn()) as c:
        return c.execute(
            """SELECT s.id FROM submissions s WHERE s.status='pending'
               ORDER BY s.id"""
        ).fetchall()


def pending_count_by_task():
    with closing(_conn()) as c:
        return {
            r["task_id"]: r["n"]
            for r in c.execute(
                """SELECT task_id, COUNT(*) AS n FROM submissions
                   WHERE status='pending' GROUP BY task_id"""
            )
        }


def review_submission(sub_id: int, status: str, grade: str | None, comment: str | None):
    with closing(_conn()) as c:
        c.execute(
            "UPDATE submissions SET status=?, grade=?, comment=? WHERE id=?",
            (status, grade, comment, sub_id),
        )
        c.commit()


def user_results(user_id: int):
    with closing(_conn()) as c:
        return c.execute(
            """SELECT s.*, t.title AS task_title FROM submissions s
               JOIN tasks t ON t.id = s.task_id
               WHERE s.user_id=? ORDER BY s.id DESC LIMIT 20""",
            (user_id,),
        ).fetchall()
