from flask import Flask, request, jsonify, render_template
from contextlib import contextmanager
from datetime import date
import os
import re
import sqlite3
import threading
import time

app = Flask(__name__)

DB_PATH = os.environ.get("DB_PATH", "data.db")
BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups"))
# Number of daily backups to keep; 0 disables backups
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "14"))

SCHEMA_VERSION = 3
NOTE_MAX_LENGTH = 5000
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
DAILY_BACKUP_RE = re.compile(r"data-\d{4}-\d{2}-\d{2}\.db")

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()

# Copy the database to BACKUP_DIR/data-<label>.db
def backup_db(label):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dest = os.path.join(BACKUP_DIR, f"data-{label}.db")
    tmp = dest + ".tmp"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, dest)
    return dest

# Make today's backup if it doesn't exist yet, and drop the oldest ones
def daily_backup():
    today = date.today().isoformat()
    if not os.path.exists(os.path.join(BACKUP_DIR, f"data-{today}.db")):
        backup_db(today)
    dailies = sorted(f for f in os.listdir(BACKUP_DIR) if DAILY_BACKUP_RE.fullmatch(f))
    for old in dailies[:-BACKUP_KEEP]:
        os.remove(os.path.join(BACKUP_DIR, old))

def backup_loop():
    while True:
        try:
            daily_backup()
        except Exception as e:
            print('Backup failed:', e)
        time.sleep(3600)

# Move a pre-versioning database (habits keyed by name) to schema version 1.
# History rows whose habit no longer exists are dropped.
def migrate_legacy():
    backup_db("pre-migration-v1")
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        conn.executescript("""
        BEGIN;
        ALTER TABLE habits RENAME TO habits_old;
        ALTER TABLE habit_history RENAME TO habit_history_old;
        CREATE TABLE habits (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE habit_history (
            habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            PRIMARY KEY (habit_id, date)
        );
        INSERT INTO habits (id, name) SELECT id, name FROM habits_old;
        INSERT OR IGNORE INTO habit_history (habit_id, date)
            SELECT h.id, o.date FROM habit_history_old o
            JOIN habits h ON h.name = o.habit_name
            WHERE o.status = 1;
        DROP TABLE habit_history_old;
        DROP TABLE habits_old;
        PRAGMA user_version = 1;
        COMMIT;
        """)
    finally:
        conn.close()

# Version 2 adds the date a habit was started (so completion rates have a denominator)
# and a log of every day a task was done (before this only the last one was kept).
def migrate_v2():
    backup_db("pre-migration-v2")
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        conn.executescript("""
        BEGIN;
        ALTER TABLE habits ADD COLUMN created TEXT;
        UPDATE habits SET created = COALESCE(
            (SELECT MIN(date) FROM habit_history WHERE habit_id = habits.id), date('now'));
        CREATE TABLE task_log (
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            PRIMARY KEY (task_id, date)
        );
        INSERT INTO task_log (task_id, date) SELECT id, last_done FROM tasks WHERE last_done IS NOT NULL;
        PRAGMA user_version = 2;
        COMMIT;
        """)
    finally:
        conn.close()

# Version 3 adds a manual order for habits and a rating and note for each day
def migrate_v3():
    backup_db("pre-migration-v3")
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        conn.executescript("""
        BEGIN;
        ALTER TABLE habits ADD COLUMN position INTEGER;
        UPDATE habits SET position = id;
        CREATE TABLE days (
            date TEXT PRIMARY KEY,
            rating INTEGER,
            note TEXT NOT NULL DEFAULT ''
        );
        PRAGMA user_version = 3;
        COMMIT;
        """)
    finally:
        conn.close()

def schema_version():
    with db() as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]

# Initialize the database
def init_db():
    with db() as conn:
        habit_columns = [row[1] for row in conn.execute("PRAGMA table_info(habits)")]
    if schema_version() == 0 and 'history' in habit_columns:
        migrate_legacy()
    if schema_version() == 1:
        migrate_v2()
    if schema_version() == 2:
        migrate_v3()

    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            created TEXT,
            position INTEGER
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS habit_history (
            habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            PRIMARY KEY (habit_id, date)
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            last_done DATE
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS task_log (
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            PRIMARY KEY (task_id, date)
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS days (
            date TEXT PRIMARY KEY,
            rating INTEGER,
            note TEXT NOT NULL DEFAULT ''
        )
        """)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

def is_date(value):
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False

def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}

def clean_name(data):
    name = data.get('name')
    return name.strip() if isinstance(name, str) else ''

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/habits', methods=['GET', 'POST'])
def manage_habits():
    with db() as conn:
        if request.method == 'GET':
            habits = {}
            for habit_id, name, created in conn.execute("SELECT id, name, created FROM habits ORDER BY position, id"):
                habits[habit_id] = {"id": habit_id, "name": name, "created": created, "done": []}
            for habit_id, day in conn.execute("SELECT habit_id, date FROM habit_history ORDER BY date"):
                habits[habit_id]["done"].append(day)
            return jsonify(list(habits.values()))

        data = body()
        name = clean_name(data)
        if not name:
            return jsonify({"error": "Habit name is required"}), 400
        # The browser sends its own local date; the server's date may be a different day
        created = data.get('created', date.today().isoformat())
        if not is_date(created):
            return jsonify({"error": "created must be a YYYY-MM-DD date"}), 400
        try:
            # New habits go to the end of the list
            c = conn.execute("""
                INSERT INTO habits (name, created, position)
                VALUES (?, ?, (SELECT COALESCE(MAX(position), 0) + 1 FROM habits))
            """, (name, created))
            return jsonify({"id": c.lastrowid, "name": name, "created": created, "done": []}), 201
        except sqlite3.IntegrityError:
            return jsonify({"error": "Habit already exists"}), 409

# Body {"ids": [...]} listing every habit id once, in the order they should appear
@app.route('/habits/order', methods=['PUT'])
def order_habits():
    ids = body().get('ids')
    with db() as conn:
        existing = [row[0] for row in conn.execute("SELECT id FROM habits")]
        if not isinstance(ids, list) or sorted(map(str, ids)) != sorted(map(str, existing)):
            return jsonify({"error": "ids must list every habit exactly once"}), 400
        conn.executemany("UPDATE habits SET position = ? WHERE id = ?",
                         [(position, habit_id) for position, habit_id in enumerate(ids, start=1)])
    return jsonify({"ids": ids}), 200

@app.route('/habits/<int:habit_id>', methods=['PATCH', 'DELETE'])
def manage_habit(habit_id):
    with db() as conn:
        if request.method == 'DELETE':
            # habit_history rows go with it (ON DELETE CASCADE)
            c = conn.execute("DELETE FROM habits WHERE id = ?", (habit_id,))
            if c.rowcount == 0:
                return jsonify({"error": "Habit not found"}), 404
            return jsonify({"status": "deleted"}), 200

        name = clean_name(body())
        if not name:
            return jsonify({"error": "Habit name is required"}), 400
        try:
            c = conn.execute("UPDATE habits SET name = ? WHERE id = ?", (name, habit_id))
        except sqlite3.IntegrityError:
            return jsonify({"error": "Habit already exists"}), 409
        if c.rowcount == 0:
            return jsonify({"error": "Habit not found"}), 404
        return jsonify({"id": habit_id, "name": name}), 200

@app.route('/habits/<int:habit_id>/history/<day>', methods=['PUT'])
def set_habit_day(habit_id, day):
    done = body().get('done')
    if not is_date(day) or not isinstance(done, bool):
        return jsonify({"error": "Expected a YYYY-MM-DD date and a boolean 'done'"}), 400

    with db() as conn:
        if not conn.execute("SELECT 1 FROM habits WHERE id = ?", (habit_id,)).fetchone():
            return jsonify({"error": "Habit not found"}), 404
        if done:
            conn.execute("INSERT OR IGNORE INTO habit_history (habit_id, date) VALUES (?, ?)", (habit_id, day))
        else:
            conn.execute("DELETE FROM habit_history WHERE habit_id = ? AND date = ?", (habit_id, day))
    return jsonify({"date": day, "done": done}), 200

@app.route('/tasks', methods=['GET', 'POST'])
def manage_tasks():
    with db() as conn:
        if request.method == 'GET':
            tasks = {}
            for task_id, name, last_done in conn.execute("SELECT id, name, last_done FROM tasks ORDER BY id"):
                tasks[task_id] = {"id": task_id, "name": name, "last_done": last_done, "log": []}
            for task_id, day in conn.execute("SELECT task_id, date FROM task_log ORDER BY date"):
                tasks[task_id]["log"].append(day)
            return jsonify(list(tasks.values()))

        name = clean_name(body())
        if not name:
            return jsonify({"error": "Task name is required"}), 400
        try:
            c = conn.execute("INSERT INTO tasks (name, last_done) VALUES (?, ?)", (name, None))
            return jsonify({"id": c.lastrowid, "name": name, "last_done": None, "log": []}), 201
        except sqlite3.IntegrityError:
            return jsonify({"error": "Task already exists"}), 409

@app.route('/tasks/<int:task_id>', methods=['PATCH', 'DELETE'])
def manage_task(task_id):
    with db() as conn:
        if request.method == 'DELETE':
            c = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            if c.rowcount == 0:
                return jsonify({"error": "Task not found"}), 404
            return jsonify({"status": "deleted"}), 200

        # Validate everything before writing so a bad field can't leave a half-applied update
        data = body()
        name = clean_name(data)
        last_done = data.get('last_done')
        if 'name' in data and not name:
            return jsonify({"error": "Task name is required"}), 400
        if last_done is not None and not is_date(last_done):
            return jsonify({"error": "last_done must be a YYYY-MM-DD date or null"}), 400
        if not conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone():
            return jsonify({"error": "Task not found"}), 404

        if 'last_done' in data:
            conn.execute("UPDATE tasks SET last_done = ? WHERE id = ?", (last_done, task_id))
            if last_done is not None:
                conn.execute("INSERT OR IGNORE INTO task_log (task_id, date) VALUES (?, ?)", (task_id, last_done))
        if 'name' in data:
            try:
                conn.execute("UPDATE tasks SET name = ? WHERE id = ?", (name, task_id))
            except sqlite3.IntegrityError:
                conn.rollback()
                return jsonify({"error": "Task already exists"}), 409

        row = conn.execute("SELECT id, name, last_done FROM tasks WHERE id = ?", (task_id,)).fetchone()
        log = [r[0] for r in conn.execute("SELECT date FROM task_log WHERE task_id = ? ORDER BY date", (task_id,))]
        return jsonify({"id": row[0], "name": row[1], "last_done": row[2], "log": log}), 200

# Take back a day a task was marked done; last_done falls back to the time before, if any
@app.route('/tasks/<int:task_id>/log/<day>', methods=['DELETE'])
def undo_task_day(task_id, day):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone():
            return jsonify({"error": "Task not found"}), 404
        conn.execute("DELETE FROM task_log WHERE task_id = ? AND date = ?", (task_id, day))
        log = [r[0] for r in conn.execute("SELECT date FROM task_log WHERE task_id = ? ORDER BY date", (task_id,))]
        last_done = log[-1] if log else None
        conn.execute("UPDATE tasks SET last_done = ? WHERE id = ?", (last_done, task_id))
        name = conn.execute("SELECT name FROM tasks WHERE id = ?", (task_id,)).fetchone()[0]
        return jsonify({"id": task_id, "name": name, "last_done": last_done, "log": log}), 200

@app.route('/days', methods=['GET'])
def list_days():
    with db() as conn:
        c = conn.execute("SELECT date, rating, note FROM days ORDER BY date")
        return jsonify([{"date": row[0], "rating": row[1], "note": row[2]} for row in c.fetchall()])

# Body may carry "rating" (1 bad, 2 okay, 3 good, or null to clear) and/or "note"; what is left out is kept
@app.route('/days/<day>', methods=['PUT'])
def set_day(day):
    data = body()
    if not is_date(day):
        return jsonify({"error": "Expected a YYYY-MM-DD date"}), 400
    if 'rating' in data and data['rating'] is not None and (type(data['rating']) is not int or data['rating'] not in (1, 2, 3)):
        return jsonify({"error": "rating must be 1, 2, 3 or null"}), 400
    if 'note' in data and (not isinstance(data['note'], str) or len(data['note']) > NOTE_MAX_LENGTH):
        return jsonify({"error": f"note must be text of at most {NOTE_MAX_LENGTH} characters"}), 400

    with db() as conn:
        row = conn.execute("SELECT rating, note FROM days WHERE date = ?", (day,)).fetchone() or (None, '')
        rating = data['rating'] if 'rating' in data else row[0]
        note = data['note'].strip() if 'note' in data else row[1]
        if rating is None and not note:
            # Nothing left to say about the day
            conn.execute("DELETE FROM days WHERE date = ?", (day,))
        else:
            conn.execute("""
                INSERT INTO days (date, rating, note) VALUES (?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET rating = excluded.rating, note = excluded.note
            """, (day, rating, note))
    return jsonify({"date": day, "rating": rating, "note": note}), 200

# Runs on import so the tables exist under gunicorn and `flask run` too
init_db()
if BACKUP_KEEP > 0:
    threading.Thread(target=backup_loop, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
