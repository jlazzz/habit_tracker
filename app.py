import sqlite3

# Initialize the database
def init_db():
    with sqlite3.connect("data.db") as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            history TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            last_done DATE
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS habit_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_name TEXT,
            date TEXT,
            status INTEGER,
            UNIQUE(habit_name, date)
        )
        """)
        conn.commit()

