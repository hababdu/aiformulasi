import os
import sqlite3
import threading
from contextlib import closing

DB_PATH = os.getenv("DB_PATH", "homework.db")

# Baza o'zgarganini bildiradi: persist.py shu belgi bo'yicha kanalga nusxa saqlaydi.
_dirty = threading.Event()
# CSV hisobotlar (archive.py) uchun alohida belgi: ikkalasi ham har yozuvda yoqiladi.
_report_dirty = threading.Event()


def mark_dirty():
    _dirty.set()


def is_dirty() -> bool:
    return _dirty.is_set()


def clear_dirty():
    _dirty.clear()


def mark_report_dirty():
    _report_dirty.set()


def report_is_dirty() -> bool:
    return _report_dirty.is_set()


def clear_report_dirty():
    _report_dirty.clear()


def _commit(c):
    c.commit()
    _dirty.set()
    _report_dirty.set()


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
                username TEXT,
                started INTEGER NOT NULL DEFAULT 0,   -- botga /start bosganmi
                in_group INTEGER NOT NULL DEFAULT 0   -- o'quvchilar guruhi a'zosimi
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
        # Eski bazalar uchun ustunlarni qo'shish (yangisida ustun bor, xato e'tiborsiz qoldiriladi)
        for col in ("started", "in_group"):
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
        _commit(c)


# ---------- users ----------
def upsert_user(user_id: int, full_name: str, username: str | None, started: bool = False):
    """Foydalanuvchini saqlaydi. started=True bo'lsa, botga /start bosgan deb belgilanadi."""
    with closing(_conn()) as c:
        c.execute(
            """INSERT INTO users (id, full_name, username, started) VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET full_name=excluded.full_name,
                                             username=excluded.username,
                                             started=MAX(started, excluded.started)""",
            (user_id, full_name, username, int(started)),
        )
        _commit(c)


def set_in_group(user_id: int, full_name: str, username: str | None, in_group: bool) -> bool:
    """O'quvchining guruh a'zoligini yozadi (started holatiga tegmaydi).

    A'zolik holati o'zgargan bo'lsa True qaytaradi (yangi qo'shildi yoki chiqib ketdi).
    """
    with closing(_conn()) as c:
        row = c.execute("SELECT in_group FROM users WHERE id=?", (user_id,)).fetchone()
        changed = bool(in_group) if row is None else bool(row["in_group"]) != bool(in_group)
        c.execute(
            """INSERT INTO users (id, full_name, username, in_group) VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET full_name=excluded.full_name,
                                             username=excluded.username,
                                             in_group=excluded.in_group""",
            (user_id, full_name, username, int(in_group)),
        )
        _commit(c)
        return changed


def broadcast_ids(group_only: bool) -> list[int]:
    """Xabar yuboriladigan o'quvchilar: botga /start bosganlar (va guruh a'zolari)."""
    sql = "SELECT id FROM users WHERE started=1"
    if group_only:
        sql += " AND in_group=1"
    with closing(_conn()) as c:
        return [r["id"] for r in c.execute(sql)]


def group_members():
    with closing(_conn()) as c:
        return c.execute(
            "SELECT full_name, username, started FROM users WHERE in_group=1 ORDER BY full_name"
        ).fetchall()


def is_empty() -> bool:
    """Bazada hali foydalanuvchi ham, vazifa ham yo'qmi (yoki fayl umuman yo'qmi)."""
    if not os.path.exists(DB_PATH):
        return True
    try:
        with closing(_conn()) as c:
            n = c.execute(
                "SELECT (SELECT COUNT(*) FROM users) + (SELECT COUNT(*) FROM tasks)"
            ).fetchone()[0]
        return n == 0
    except sqlite3.Error:
        return True


def export_all() -> dict[str, list[tuple]]:
    """CSV zahira uchun: o'quvchilar, vazifalar va topshiriqlar (ballar bilan)."""
    with closing(_conn()) as c:
        students = c.execute(
            "SELECT id, full_name, username, in_group, started FROM users ORDER BY full_name"
        ).fetchall()
        tasks = c.execute(
            "SELECT id, title, description, deadline, active, created_at FROM tasks ORDER BY id"
        ).fetchall()
        subs = c.execute(
            """SELECT s.id, t.title, u.full_name, u.username, s.content_type, s.text,
                      s.status, s.grade, s.comment, s.created_at
               FROM submissions s
               JOIN tasks t ON t.id = s.task_id
               JOIN users u ON u.id = s.user_id
               ORDER BY s.id"""
        ).fetchall()
    return {
        "students": [tuple(r) for r in students],
        "tasks": [tuple(r) for r in tasks],
        "submissions": [tuple(r) for r in subs],
    }


# ---------- tasks ----------
def add_task(title: str, description: str, deadline: str | None) -> int:
    with closing(_conn()) as c:
        cur = c.execute(
            "INSERT INTO tasks (title, description, deadline) VALUES (?, ?, ?)",
            (title, description, deadline),
        )
        _commit(c)
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
        _commit(c)
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
        _commit(c)
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
        _commit(c)


def user_results(user_id: int):
    with closing(_conn()) as c:
        return c.execute(
            """SELECT s.*, t.title AS task_title FROM submissions s
               JOIN tasks t ON t.id = s.task_id
               WHERE s.user_id=? ORDER BY s.id DESC LIMIT 20""",
            (user_id,),
        ).fetchall()
