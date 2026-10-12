import importlib
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_app(monkeypatch, tmp_path, backup_keep="0"):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("BACKUP_KEEP", backup_keep)
    import app
    return importlib.reload(app)


@pytest.fixture
def client(monkeypatch, tmp_path):
    return load_app(monkeypatch, tmp_path).app.test_client()


# The schema the app created before versioning was introduced
def make_legacy_db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE habits (id INTEGER PRIMARY KEY, name TEXT UNIQUE, history TEXT);
        CREATE TABLE tasks (id INTEGER PRIMARY KEY, name TEXT UNIQUE, last_done DATE);
        CREATE TABLE habit_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, habit_name TEXT, date TEXT, status INTEGER,
            UNIQUE(habit_name, date));
        INSERT INTO habits VALUES (3, 'Read', '0,0'), (7, 'Run', '0,0');
        INSERT INTO tasks VALUES (2, 'Mow lawn', '2026-10-01');
        INSERT INTO habit_history (habit_name, date, status) VALUES
            ('Read', '2026-10-08', 1), ('Read', '2026-10-09', 0), ('Read', '2026-10-10', 1),
            ('Run', '2026-10-10', 1), ('Deleted habit', '2026-10-10', 1);
    """)
    conn.commit()
    conn.close()


def test_index_serves_local_assets_only(client):
    html = client.get('/').get_data(as_text=True)
    assert 'https://' not in html and 'http://' not in html
    for asset in ('style.css', 'script.js', 'fonts/fraunces-latin-full-normal.woff2'):
        assert client.get(f'/static/{asset}').status_code == 200


def test_habit_lifecycle(client):
    assert client.get('/habits').get_json() == []
    res = client.post('/habits', json={"name": "  Read  ", "created": "2026-10-01"})
    assert res.status_code == 201
    habit = res.get_json()
    assert habit["name"] == "Read"
    assert habit["created"] == "2026-10-01" and habit["done"] == []
    assert client.post('/habits', json={"name": "Other", "created": "soon"}).status_code == 400

    assert client.post('/habits', json={"name": "Read"}).status_code == 409
    assert client.post('/habits', json={"name": "   "}).status_code == 400
    assert client.post('/habits', json={}).status_code == 400
    assert client.post('/habits', data="not json").status_code == 400

    url = f'/habits/{habit["id"]}/history/2026-10-10'
    assert client.put(url, json={"done": True}).status_code == 200
    assert client.put(url, json={"done": True}).status_code == 200  # idempotent
    assert client.get('/habits').get_json() == [
        {"id": habit["id"], "name": "Read", "created": "2026-10-01", "done": ["2026-10-10"]}]
    assert client.put(url, json={"done": False}).status_code == 200
    assert client.get('/habits').get_json()[0]["done"] == []


def test_habit_day_validation(client):
    habit_id = client.post('/habits', json={"name": "Read"}).get_json()["id"]
    assert client.put(f'/habits/{habit_id}/history/2026-02-30', json={"done": True}).status_code == 400
    assert client.put(f'/habits/{habit_id}/history/20261010', json={"done": True}).status_code == 400
    assert client.put(f'/habits/{habit_id}/history/2026-10-10', json={"done": 1}).status_code == 400
    assert client.put(f'/habits/{habit_id}/history/2026-10-10', json={}).status_code == 400
    assert client.put('/habits/999/history/2026-10-10', json={"done": True}).status_code == 404


def test_rename_habit_keeps_history(client):
    a = client.post('/habits', json={"name": "Read"}).get_json()["id"]
    client.post('/habits', json={"name": "Run"})
    client.put(f'/habits/{a}/history/2026-10-10', json={"done": True})

    assert client.patch(f'/habits/{a}', json={"name": "Run"}).status_code == 409
    assert client.patch(f'/habits/{a}', json={"name": ""}).status_code == 400
    assert client.patch('/habits/999', json={"name": "X"}).status_code == 404
    assert client.patch(f'/habits/{a}', json={"name": "Read books"}).status_code == 200

    habits = {h["name"]: h for h in client.get('/habits').get_json()}
    assert habits["Read books"]["done"] == ["2026-10-10"]
    assert "Read" not in habits


def test_deleting_habit_deletes_its_history(client):
    habit_id = client.post('/habits', json={"name": "Read"}).get_json()["id"]
    client.put(f'/habits/{habit_id}/history/2026-10-10', json={"done": True})
    assert client.delete(f'/habits/{habit_id}').status_code == 200
    assert client.delete(f'/habits/{habit_id}').status_code == 404

    # Re-adding the same name must not bring the old check-offs back
    client.post('/habits', json={"name": "Read"})
    assert client.get('/habits').get_json()[0]["done"] == []


def test_task_lifecycle(client):
    res = client.post('/tasks', json={"name": "Water mom's plants"})
    assert res.status_code == 201
    task = res.get_json()
    assert task == {"id": task["id"], "name": "Water mom's plants", "last_done": None, "log": []}
    assert client.post('/tasks', json={"name": "Water mom's plants"}).status_code == 409
    assert client.post('/tasks', json={"name": ""}).status_code == 400

    url = f'/tasks/{task["id"]}'
    assert client.patch(url, json={"last_done": "2026-10-11"}).get_json()["last_done"] == "2026-10-11"
    assert client.patch(url, json={"last_done": "yesterday"}).status_code == 400
    assert client.patch(url, json={"name": "Water plants"}).get_json() == {
        "id": task["id"], "name": "Water plants", "last_done": "2026-10-11", "log": ["2026-10-11"]}
    # Every day it was done is kept, not just the latest; clearing last_done keeps the log
    client.patch(url, json={"last_done": "2026-10-13"})
    client.patch(url, json={"last_done": "2026-10-13"})
    cleared = client.patch(url, json={"last_done": None}).get_json()
    assert cleared["last_done"] is None and cleared["log"] == ["2026-10-11", "2026-10-13"]
    assert client.get('/tasks').get_json()[0]["log"] == ["2026-10-11", "2026-10-13"]
    assert client.patch('/tasks/999', json={"name": "X"}).status_code == 404

    assert client.delete(url).status_code == 200
    assert client.delete(url).status_code == 404
    assert client.get('/tasks').get_json() == []


def test_task_patch_is_all_or_nothing(client):
    a = client.post('/tasks', json={"name": "A"}).get_json()["id"]
    client.post('/tasks', json={"name": "B"})

    # Bad date: the valid name in the same request must not be applied
    assert client.patch(f'/tasks/{a}', json={"name": "C", "last_done": "nope"}).status_code == 400
    # Duplicate name: the valid date in the same request must not be applied
    assert client.patch(f'/tasks/{a}', json={"name": "B", "last_done": "2026-10-11"}).status_code == 409

    assert client.get('/tasks').get_json()[0] == {"id": a, "name": "A", "last_done": None, "log": []}


def test_legacy_db_is_migrated(monkeypatch, tmp_path):
    make_legacy_db(tmp_path / "data.db")
    client = load_app(monkeypatch, tmp_path).app.test_client()

    # Ids and names survive; only status=1 rows of habits that still exist are kept
    # A habit's start date is its first check-off, and the task's last date seeds its log
    assert client.get('/habits').get_json() == [
        {"id": 3, "name": "Read", "created": "2026-10-08", "done": ["2026-10-08", "2026-10-10"]},
        {"id": 7, "name": "Run", "created": "2026-10-10", "done": ["2026-10-10"]},
    ]
    assert client.get('/tasks').get_json() == [
        {"id": 2, "name": "Mow lawn", "last_done": "2026-10-01", "log": ["2026-10-01"]}]

    conn = sqlite3.connect(tmp_path / "data.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    tables.discard("sqlite_sequence")  # SQLite's own leftover from the old AUTOINCREMENT column
    assert tables == {"habits", "habit_history", "tasks", "task_log", "days"}
    conn.close()

    # An untouched copy of the old database is kept
    old = sqlite3.connect(tmp_path / "backups" / "data-pre-migration-v1.db")
    assert old.execute("SELECT COUNT(*) FROM habit_history").fetchone()[0] == 5
    assert old.execute("SELECT history FROM habits WHERE id = 3").fetchone()[0] == '0,0'
    old.close()


def test_migration_runs_once(monkeypatch, tmp_path):
    make_legacy_db(tmp_path / "data.db")
    client = load_app(monkeypatch, tmp_path).app.test_client()
    client.put('/habits/3/history/2026-10-11', json={"done": True})
    for name in os.listdir(tmp_path / "backups"):
        os.remove(tmp_path / "backups" / name)

    client = load_app(monkeypatch, tmp_path).app.test_client()
    assert client.get('/habits').get_json()[0]["done"] == ["2026-10-08", "2026-10-10", "2026-10-11"]
    assert os.listdir(tmp_path / "backups") == []


def test_v1_db_is_migrated(monkeypatch, tmp_path):
    conn = sqlite3.connect(tmp_path / "data.db")
    conn.executescript("""
        CREATE TABLE habits (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
        CREATE TABLE habit_history (
            habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
            date TEXT NOT NULL, PRIMARY KEY (habit_id, date));
        CREATE TABLE tasks (id INTEGER PRIMARY KEY, name TEXT UNIQUE, last_done DATE);
        INSERT INTO habits VALUES (1, 'Read'), (2, 'Never ticked');
        INSERT INTO habit_history VALUES (1, '2026-09-20'), (1, '2026-10-02');
        INSERT INTO tasks VALUES (1, 'Mow lawn', '2026-10-01'), (2, 'Never done', NULL);
        PRAGMA user_version = 1;
    """)
    conn.commit()
    conn.close()
    module = load_app(monkeypatch, tmp_path)
    client = module.app.test_client()

    habits = client.get('/habits').get_json()
    assert habits[0] == {"id": 1, "name": "Read", "created": "2026-09-20", "done": ["2026-09-20", "2026-10-02"]}
    assert habits[1]["created"] is not None and module.is_date(habits[1]["created"])
    assert [t["log"] for t in client.get('/tasks').get_json()] == [["2026-10-01"], []]
    assert (tmp_path / "backups" / "data-pre-migration-v2.db").exists()

    # Deleting a task takes its log with it
    client.delete('/tasks/1')
    conn = sqlite3.connect(tmp_path / "data.db")
    assert conn.execute("SELECT COUNT(*) FROM task_log").fetchone()[0] == 0
    conn.close()


def test_daily_backup_and_pruning(monkeypatch, tmp_path):
    module = load_app(monkeypatch, tmp_path)
    module.app.test_client().post('/habits', json={"name": "Read"})
    monkeypatch.setattr(module, "BACKUP_KEEP", 3)

    backups = tmp_path / "backups"
    backups.mkdir()
    for day in ("2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"):
        (backups / f"data-{day}.db").write_bytes(b"old")
    (backups / "data-pre-migration-v1.db").write_bytes(b"keep me")

    module.daily_backup()
    module.daily_backup()  # second call the same day is a no-op

    today = f"data-{module.date.today().isoformat()}.db"
    assert sorted(os.listdir(backups)) == sorted(
        ["data-2020-01-03.db", "data-2020-01-04.db", today, "data-pre-migration-v1.db"])
    copy = sqlite3.connect(backups / today)
    assert copy.execute("SELECT name FROM habits").fetchall() == [("Read",)]
    copy.close()


def test_reordering_habits(client):
    a, b, c = (client.post('/habits', json={"name": n}).get_json()["id"] for n in ("A", "B", "C"))
    assert [h["name"] for h in client.get('/habits').get_json()] == ["A", "B", "C"]

    assert client.put('/habits/order', json={"ids": [c, a, b]}).status_code == 200
    assert [h["name"] for h in client.get('/habits').get_json()] == ["C", "A", "B"]

    # A new habit goes last; a deleted one leaves the rest in order
    d = client.post('/habits', json={"name": "D"}).get_json()["id"]
    client.delete(f'/habits/{a}')
    assert [h["name"] for h in client.get('/habits').get_json()] == ["C", "B", "D"]

    for bad in ([c, b], [c, b, d, d], [c, b, d, 999], "cbd", None):
        assert client.put('/habits/order', json={"ids": bad}).status_code == 400
    assert [h["name"] for h in client.get('/habits').get_json()] == ["C", "B", "D"]


def test_undoing_a_task(client):
    task_id = client.post('/tasks', json={"name": "Mow lawn"}).get_json()["id"]
    client.patch(f'/tasks/{task_id}', json={"last_done": "2026-10-01"})
    client.patch(f'/tasks/{task_id}', json={"last_done": "2026-10-11"})

    # Undoing the latest falls back to the time before
    undone = client.delete(f'/tasks/{task_id}/log/2026-10-11').get_json()
    assert undone == {"id": task_id, "name": "Mow lawn", "last_done": "2026-10-01", "log": ["2026-10-01"]}
    assert client.get('/tasks').get_json()[0]["last_done"] == "2026-10-01"

    # Undoing a day that was never logged changes nothing; undoing the only one leaves "never"
    assert client.delete(f'/tasks/{task_id}/log/2026-10-05').get_json()["last_done"] == "2026-10-01"
    assert client.delete(f'/tasks/{task_id}/log/2026-10-01').get_json() == {
        "id": task_id, "name": "Mow lawn", "last_done": None, "log": []}
    assert client.delete('/tasks/999/log/2026-10-01').status_code == 404


def test_day_rating_and_note(client):
    assert client.get('/days').get_json() == []
    assert client.put('/days/2026-10-11', json={"rating": 3}).get_json() == {"date": "2026-10-11", "rating": 3, "note": ""}
    # Each field is saved on its own without wiping the other
    assert client.put('/days/2026-10-11', json={"note": "  Long walk, slept well.  "}).get_json() == {
        "date": "2026-10-11", "rating": 3, "note": "Long walk, slept well."}
    assert client.put('/days/2026-10-11', json={"rating": 1}).get_json()["note"] == "Long walk, slept well."
    client.put('/days/2026-10-09', json={"note": "<b>it's</b> \"quoted\""})
    assert client.get('/days').get_json() == [
        {"date": "2026-10-09", "rating": None, "note": "<b>it's</b> \"quoted\""},
        {"date": "2026-10-11", "rating": 1, "note": "Long walk, slept well."},
    ]

    # Clearing the rating keeps the note; clearing both removes the day
    assert client.put('/days/2026-10-11', json={"rating": None}).get_json()["note"] == "Long walk, slept well."
    client.put('/days/2026-10-11', json={"note": ""})
    assert [d["date"] for d in client.get('/days').get_json()] == ["2026-10-09"]

    for bad in ({"rating": 0}, {"rating": 4}, {"rating": "3"}, {"rating": True}, {"rating": 2.0}, {"note": 5}, {"note": "x" * 5001}):
        assert client.put('/days/2026-10-11', json=bad).status_code == 400, bad
    assert client.put('/days/2026-13-01', json={"rating": 2}).status_code == 400
    assert [d["date"] for d in client.get('/days').get_json()] == ["2026-10-09"]


def test_v2_db_is_migrated(monkeypatch, tmp_path):
    conn = sqlite3.connect(tmp_path / "data.db")
    conn.executescript("""
        CREATE TABLE habits (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, created TEXT);
        CREATE TABLE habit_history (
            habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
            date TEXT NOT NULL, PRIMARY KEY (habit_id, date));
        CREATE TABLE tasks (id INTEGER PRIMARY KEY, name TEXT UNIQUE, last_done DATE);
        CREATE TABLE task_log (
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            date TEXT NOT NULL, PRIMARY KEY (task_id, date));
        INSERT INTO habits VALUES (4, 'Run', '2026-09-01'), (2, 'Read', '2026-09-01'), (9, 'Stretch', '2026-10-01');
        INSERT INTO habit_history VALUES (2, '2026-10-02');
        INSERT INTO tasks VALUES (1, 'Mow lawn', '2026-10-01');
        INSERT INTO task_log VALUES (1, '2026-10-01');
        PRAGMA user_version = 2;
    """)
    conn.commit()
    conn.close()
    client = load_app(monkeypatch, tmp_path).app.test_client()

    # Habits keep the order they were shown in before (by id) and nothing else changes
    assert client.get('/habits').get_json() == [
        {"id": 2, "name": "Read", "created": "2026-09-01", "done": ["2026-10-02"]},
        {"id": 4, "name": "Run", "created": "2026-09-01", "done": []},
        {"id": 9, "name": "Stretch", "created": "2026-10-01", "done": []},
    ]
    assert client.get('/tasks').get_json() == [{"id": 1, "name": "Mow lawn", "last_done": "2026-10-01", "log": ["2026-10-01"]}]
    assert client.get('/days').get_json() == []
    assert (tmp_path / "backups" / "data-pre-migration-v3.db").exists()
    assert client.put('/habits/order', json={"ids": [9, 2, 4]}).status_code == 200
    assert [h["id"] for h in client.get('/habits').get_json()] == [9, 2, 4]
