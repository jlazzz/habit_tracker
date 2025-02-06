from flask import Flask, request, jsonify, render_template
import sqlite3
from datetime import datetime

app = Flask(__name__)

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/tasks', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_tasks():
    with sqlite3.connect("data.db") as conn:
        c = conn.cursor()
        if request.method == 'GET':
            c.execute("SELECT name, last_done FROM tasks")
            tasks = [{"name": row[0], "last_done": row[1]} for row in c.fetchall()]
            return jsonify(tasks)

        elif request.method == 'POST':
            data = request.json
            if not data.get('name'):
                return jsonify({"error": "Task name is required"}), 400

            try:
                c.execute("INSERT INTO tasks (name, last_done) VALUES (?, ?)", (data['name'], None))
                conn.commit()
                return jsonify({"status": "success"}), 201
            except sqlite3.IntegrityError:
                return jsonify({"error": "Task already exists"}), 409

        elif request.method == 'PUT':
            data = request.json
            c.execute("UPDATE tasks SET last_done = ? WHERE name = ?", (data['last_done'], data['name']))
            conn.commit()
            return jsonify({"status": "updated"}), 200

        elif request.method == 'DELETE':
            data = request.json
            c.execute("DELETE FROM tasks WHERE name = ?", (data['name'],))
            conn.commit()
            return jsonify({"status": "deleted"}), 200

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)

