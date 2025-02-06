function displayCurrentDate() {
    const dateElement = document.getElementById('current-date');
    const today = new Date();
    dateElement.textContent = today.toDateString();
}

document.body.style.backgroundColor = "#A98F6D";

