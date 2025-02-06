function displayCurrentDate() {
    const dateElement = document.getElementById('current-date');
    const today = new Date();
    dateElement.textContent = today.toDateString();
}

document.body.style.backgroundColor = "#A98F6D";

async function fetchHabits() {
    const response = await fetch('/habits');
    const habits = await response.json();
    renderHabits(habits);
}

async function addHabit(name) {
    console.log('Adding habit:', name);
    try {
        const response = await fetch('/habits', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name })
        });

        if (response.ok) {
            console.log('Habit added successfully');
            fetchHabits();
        } else {
            console.error('Failed to add habit:', await response.text());
        }
    } catch (error) {
        console.error('Error:', error);
    }
}

async function toggleHabit(name, date) {
    const response = await fetch('/habits/history', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, date: date })
    });
    if (response.ok) {
        fetchHabits();
    }
}

function renderHabits(habits) {
    const habitList = document.getElementById('habit-list');
    habitList.innerHTML = '';

    habits.forEach(habit => {
        const li = document.createElement('li');
        li.className = 'flex flex-col bg-gray-100 px-4 py-2 rounded-md mb-2';

        const habitName = document.createElement('span');
        habitName.textContent = habit.name;

        const containerDiv = document.createElement('div');
        containerDiv.className = 'flex flex-col items-center';

        const dayLabels = document.createElement('div');
        dayLabels.className = 'flex justify-between w-full';

        const historyDiv = document.createElement('div');
        historyDiv.className = 'flex justify-between w-full mt-1';

        const today = new Date();

        for (let i = 0; i <= 13; i++) { // Reverse the loop order
            const date = new Date(today);
            date.setDate(today.getDate() - i);
            const dateString = date.toISOString().split('T')[0];
            const dayOfWeek = date.toLocaleDateString('en-US', { weekday: 'short' }).charAt(0);

            const dayLabel = document.createElement('div');
            dayLabel.textContent = dayOfWeek;
            dayLabel.className = 'text-sm text-gray-600 text-center w-6';
            dayLabels.appendChild(dayLabel);

            const checkboxWrapper = document.createElement('div');
            checkboxWrapper.className = 'w-6 flex justify-center';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = habit.history && habit.history[dateString] === 1;
            checkbox.addEventListener('change', () => toggleHabit(habit.name, dateString));

            checkboxWrapper.appendChild(checkbox);
            historyDiv.appendChild(checkboxWrapper);
        }

        const deleteBtn = document.createElement('button');
        deleteBtn.textContent = 'Delete';
        deleteBtn.className = 'text-red-500 mt-2';
        deleteBtn.onclick = () => deleteHabit(habit.name);

        containerDiv.appendChild(dayLabels);
        containerDiv.appendChild(historyDiv);

        li.appendChild(habitName);
        li.appendChild(containerDiv);
        li.appendChild(deleteBtn);

        habitList.appendChild(li);
    });
}

async function deleteHabit(name) {
    await fetch('/habits', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
    });
    fetchHabits();
}

async function addTask(name) {
    await fetch('/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
    });
    fetchTasks();
}

async function markTaskDone(name) {
    await fetch('/tasks', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, last_done: new Date().toISOString().split('T')[0] })
    });
    fetchTasks();
}

async function deleteTask(name) {
    await fetch('/tasks', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
    });
    fetchTasks();
}

function renderTasks(tasks) {
    const taskList = document.getElementById('days-since-list');
    taskList.innerHTML = '';

    tasks.forEach(task => {
        const daysAgo = task.last_done
            ? Math.floor((Date.now() - new Date(task.last_done)) / (1000 * 60 * 60 * 24))
            : 'Never';

        const li = document.createElement('li');
        li.className = 'flex justify-between items-center bg-gray-100 px-4 py-2 rounded-md';
        li.innerHTML = `
            <span>${task.name}: ${daysAgo} days ago</span>
            <button onclick="markTaskDone('${task.name}')" class="bg-gray-500 text-white px-2 py-1 rounded-md">Did It Today</button>
            <button onclick="deleteTask('${task.name}')" class="text-red-500 ml-4">Delete</button>
        `;
        taskList.appendChild(li);
    });
}
fetchHabits();

