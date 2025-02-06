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

@app.route('/habits', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_habits():
    with sqlite3.connect("data.db") as conn:
        c = conn.cursor()
        if request.method == 'GET':
            c.execute("SELECT name FROM habits")
            habits = []
            for row in c.fetchall():
                habit_name = row[0]
                c.execute("SELECT date, status FROM habit_history WHERE habit_name = ?", (habit_name,))
                history = {date: status for date, status in c.fetchall()}
                habits.append({"name": habit_name, "history": history})
            return jsonify(habits)

        elif request.method == 'POST':
            data = request.json
            if not data.get('name'):
                return jsonify({"error": "Habit name is required"}), 400

            try:
                c.execute("INSERT INTO habits (name, history) VALUES (?, ?)", (data['name'], '0,0,0,0,0,0,0,0,0,0,0,0,0,0'))
                conn.commit()
                return jsonify({"status": "success"}), 201
            except sqlite3.IntegrityError:
                return jsonify({"error": "Habit already exists"}), 409

        elif request.method == 'PUT':
            data = request.json
            c.execute("UPDATE habits SET history = ? WHERE name = ?", (','.join(data['history']), data['name']))
            conn.commit()
            return jsonify({"status": "updated"}), 200

        elif request.method == 'DELETE':
            data = request.json
            c.execute("DELETE FROM habits WHERE name = ?", (data['name'],))
            conn.commit()
            return jsonify({"status": "deleted"}), 200

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

@app.route('/habits', methods=['POST'])
def add_habit():
    data = request.json
    print('Received data:', data)  # Debugging line
    if not data.get('name'):
        return jsonify({"error": "Habit name is required"}), 400

    try:
        with sqlite3.connect("data.db") as conn:
            c = conn.cursor()
            c.execute("INSERT INTO habits (name, history) VALUES (?, ?)", (data['name'], '0,0,0,0,0,0,0,0,0,0,0,0,0,0'))
            conn.commit()
        print('Habit added successfully')  # Debugging line
        return jsonify({"status": "success"}), 201
    except sqlite3.IntegrityError as e:
        print('Database error:', e)  # Debugging line
        return jsonify({"error": "Habit already exists"}), 409

@app.route('/habits/history', methods=['PUT'])
def update_habit_history():
    data = request.json
    habit_name = data['name']
    date = data['date']

    with sqlite3.connect("data.db") as conn:
        c = conn.cursor()

        # Toggle the current status
        c.execute("SELECT status FROM habit_history WHERE habit_name = ? AND date = ?", (habit_name, date))
        row = c.fetchone()
        new_status = 0 if row and row[0] == 1 else 1

        # Insert new or update existing record
        c.execute("""
            INSERT INTO habit_history (habit_name, date, status)
            VALUES (?, ?, ?)
            ON CONFLICT(habit_name, date) DO UPDATE SET status = excluded.status
        """, (habit_name, date, new_status))
        
        conn.commit()

    return jsonify({"status": "updated"})

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)

