function displayCurrentDate() {
    const dateElement = document.getElementById('current-date');
    const today = new Date();
    dateElement.textContent = today.toDateString();
}

document.body.style.backgroundColor = "#A98F6D";

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

async function deleteTask(name) {
    await fetch('/tasks', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
    });
    fetchTasks();
}

