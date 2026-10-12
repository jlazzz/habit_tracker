const MS_PER_DAY = 1000 * 60 * 60 * 24;
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const SVG_NS = 'http://www.w3.org/2000/svg';
const PERIOD_TITLES = { '7': 'Last 7 days', '30': 'Last 30 days', '90': 'Last 90 days', '365': 'Last year', 'all': 'All time' };
const SORT_LABELS = { rate: 'Rate', change: 'Change', streak: 'Streak', best: 'Best', name: 'Name' };
// Longer periods are charted per week; a bar per day gets too thin to read
const MAX_DAILY_BARS = 92;
const MIN_BAR_SLOT = 5;
const MAX_CALENDAR_WEEKS = 53;
// Day ratings, worst to best; stored as 1, 2, 3
const RATINGS = [{ value: 1, label: 'Bad' }, { value: 2, label: 'Okay' }, { value: 3, label: 'Good' }];
const MAX_NOTES_SHOWN = 40;

const state = {
    habits: [],
    tasks: [],
    days: {},                 // date string -> { rating, note }
    day: startOfToday(),      // the day shown on the Today view
    period: loadSetting('period', '30'),
    sort: loadSetting('sort', { key: 'rate', descending: true }),
};

// ---------- dates ----------
// All dates are the viewer's local calendar dates as YYYY-MM-DD.
// (toISOString() would give the UTC date, which is the wrong day for part of every day.)

function localDateString(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function parseLocalDate(dateString) {
    const [year, month, day] = dateString.split('-').map(Number);
    return new Date(year, month - 1, day);
}

function addDays(date, days) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

// Whole calendar days from one local date to another (rounding absorbs DST's 23/25 hour days)
function daysBetween(from, to) {
    return Math.round((to - from) / MS_PER_DAY);
}

function startOfToday() {
    return addDays(new Date(), 0);
}

// Monday = 0 ... Sunday = 6
function weekdayIndex(date) {
    return (date.getDay() + 6) % 7;
}

function shortDate(date) {
    return `${WEEKDAYS[weekdayIndex(date)]} ${date.getDate()} ${date.toLocaleDateString('en-US', { month: 'short' })}`;
}

function longDate(date) {
    return `${date.getDate()} ${date.toLocaleDateString('en-US', { month: 'long' })} ${date.getFullYear()}`;
}

function pluralDays(count) {
    return `${count} ${count === 1 ? 'day' : 'days'}`;
}

// ---------- statistics ----------

// The first day a habit counts from: when it was added, or its first check-off if that is earlier
function habitStart(habit, today) {
    const candidates = [habit.created, habit.done[0], localDateString(today)].filter(Boolean).sort();
    return parseLocalDate(candidates[0]);
}

// done: Set of YYYY-MM-DD strings. A streak still counts if today isn't checked off yet.
function habitStats(done, today) {
    let cursor = done.has(localDateString(today)) ? today : addDays(today, -1);
    let current = 0;
    while (done.has(localDateString(cursor))) {
        current++;
        cursor = addDays(cursor, -1);
    }

    let best = 0;
    let run = 0;
    let previous = null;
    for (const dateString of [...done].sort()) {
        const date = parseLocalDate(dateString);
        run = previous && daysBetween(previous, date) === 1 ? run + 1 : 1;
        best = Math.max(best, run);
        previous = date;
    }
    return { current, best };
}

// How a habit did between two dates (inclusive). Days before the habit started don't count against it.
function habitPeriodStats(habit, from, to, today) {
    const start = habitStart(habit, today);
    const first = start > from ? start : from;
    if (first > to) return { active: 0, done: 0, rate: null };
    const firstString = localDateString(first);
    const lastString = localDateString(to);
    const active = daysBetween(first, to) + 1;
    const done = habit.done.filter(d => d >= firstString && d <= lastString).length;
    return { active, done, rate: done / active };
}

// period: '7' | '30' | '90' | '365' | 'all'
// dayDates: dates that have a rating or note, so "all" reaches back to those too
function periodRange(period, habits, today, dayDates) {
    if (period === 'all') {
        let from = today;
        for (const habit of habits) {
            const start = habitStart(habit, today);
            if (start < from) from = start;
        }
        const firstDay = [...(dayDates || [])].sort()[0];
        if (firstDay && parseLocalDate(firstDay) < from) from = parseLocalDate(firstDay);
        return { from, to: today, days: daysBetween(from, today) + 1 };
    }
    const days = Number(period);
    return { from: addDays(today, -(days - 1)), to: today, days };
}

// One entry per day: how many habits existed and how many were done
function dailySeries(habits, from, to, today) {
    const starts = habits.map(habit => localDateString(habitStart(habit, today)));
    const doneSets = habits.map(habit => new Set(habit.done));
    const series = [];
    for (let date = from; date <= to; date = addDays(date, 1)) {
        const dateString = localDateString(date);
        let active = 0;
        let done = 0;
        habits.forEach((habit, i) => {
            if (starts[i] <= dateString) {
                active++;
                if (doneSets[i].has(dateString)) done++;
            }
        });
        series.push({ date, active, done });
    }
    return series;
}

// Group a daily series into Monday-to-Sunday weeks
function weeklySeries(daily) {
    const weeks = [];
    for (const day of daily) {
        const last = weeks[weeks.length - 1];
        if (last && weekdayIndex(day.date) !== 0) {
            last.active += day.active;
            last.done += day.done;
            last.end = day.date;
        } else {
            weeks.push({ date: day.date, end: day.date, active: day.active, done: day.done });
        }
    }
    return weeks;
}

function weekdayBreakdown(daily) {
    const totals = WEEKDAYS.map(name => ({ name, active: 0, done: 0 }));
    for (const day of daily) {
        totals[weekdayIndex(day.date)].active += day.active;
        totals[weekdayIndex(day.date)].done += day.done;
    }
    return totals.map(t => ({ ...t, rate: t.active ? t.done / t.active : null }));
}

function recordSummary(habits, period, today, dayDates) {
    const range = periodRange(period, habits, today, dayDates);
    const daily = dailySeries(habits, range.from, range.to, today);
    const active = daily.reduce((sum, d) => sum + d.active, 0);
    const done = daily.reduce((sum, d) => sum + d.done, 0);

    // The same number of days immediately before, for comparison ("all" has nothing before it)
    const previousTo = addDays(range.from, -1);
    const previousFrom = addDays(range.from, -range.days);
    let previousRate = null;
    if (period !== 'all') {
        const previous = dailySeries(habits, previousFrom, previousTo, today);
        const previousActive = previous.reduce((sum, d) => sum + d.active, 0);
        if (previousActive) previousRate = previous.reduce((sum, d) => sum + d.done, 0) / previousActive;
    }

    const entries = habits.map(habit => {
        const stats = habitPeriodStats(habit, range.from, range.to, today);
        const before = period === 'all' ? { rate: null } : habitPeriodStats(habit, previousFrom, previousTo, today);
        const streaks = habitStats(new Set(habit.done), today);
        return {
            habit,
            ...stats,
            change: stats.rate !== null && before.rate !== null ? stats.rate - before.rate : null,
            streak: streaks.current,
            best: streaks.best,
        };
    });

    return {
        range,
        daily,
        active,
        done,
        rate: active ? done / active : null,
        change: active && previousRate !== null ? done / active - previousRate : null,
        perfectDays: daily.filter(d => d.active > 0 && d.done === d.active).length,
        countedDays: daily.filter(d => d.active > 0).length,
        weekdays: weekdayBreakdown(daily),
        entries,
    };
}

// Missing values always sort last, whichever direction is chosen
function sortEntries(entries, sort) {
    const direction = sort.descending ? -1 : 1;
    return [...entries].sort((a, b) => {
        if (sort.key === 'name') return direction * a.habit.name.localeCompare(b.habit.name);
        const x = a[sort.key];
        const y = b[sort.key];
        if (x === null && y === null) return a.habit.name.localeCompare(b.habit.name);
        if (x === null) return 1;
        if (y === null) return -1;
        return direction * (x - y) || a.habit.name.localeCompare(b.habit.name);
    });
}

// Average gap between the days a task was done, or null with fewer than two
function averageInterval(log) {
    if (log.length < 2) return null;
    return daysBetween(parseLocalDate(log[0]), parseLocalDate(log[log.length - 1])) / (log.length - 1);
}

function formatPercent(rate) {
    return rate === null ? '—' : `${Math.round(rate * 100)}%`;
}

function formatChange(change) {
    if (change === null) return '';
    const points = Math.round(change * 100);
    if (points === 0) return 'no change';
    return `${points > 0 ? '▲' : '▼'} ${Math.abs(points)} pts`;
}

// ---------- small DOM helpers ----------

function el(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
}

function svg(tag, attributes) {
    const element = document.createElementNS(SVG_NS, tag);
    for (const [name, value] of Object.entries(attributes || {})) element.setAttribute(name, value);
    return element;
}

function loadSetting(name, fallback) {
    try {
        const value = JSON.parse(localStorage.getItem(`habits.${name}`));
        return value === null ? fallback : value;
    } catch (error) {
        return fallback;
    }
}

function saveSetting(name, value) {
    try {
        localStorage.setItem(`habits.${name}`, JSON.stringify(value));
    } catch (error) {
        // Private windows may refuse storage; the setting just won't be remembered
    }
}

function showError(message) {
    const error = document.getElementById('error');
    error.textContent = message;
    error.hidden = !message;
}

// fetch wrapper: sends JSON, returns the parsed body, and shows the server's error message on failure
async function api(method, url, payload) {
    const options = { method };
    if (payload !== undefined) {
        options.headers = { 'Content-Type': 'application/json' };
        options.body = JSON.stringify(payload);
    }
    try {
        const response = await fetch(url, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            showError(data.error || `Request failed (${response.status})`);
            return null;
        }
        showError('');
        return data;
    } catch (error) {
        showError('Could not reach the server');
        return null;
    }
}

function textButton(label, className, onClick) {
    const button = el('button', className, label);
    button.type = 'button';
    button.addEventListener('click', onClick);
    return button;
}

// A button that asks for a second click before running onConfirm
function confirmButton(label, className, onConfirm) {
    const button = el('button', className, label);
    button.type = 'button';
    let armed = false;
    let timer = null;
    button.addEventListener('click', () => {
        if (armed) {
            clearTimeout(timer);
            onConfirm();
            return;
        }
        armed = true;
        button.textContent = 'Click again to delete';
        timer = setTimeout(() => {
            armed = false;
            button.textContent = label;
        }, 4000);
    });
    return button;
}

// Replace a name with a text box; Enter saves, Escape or leaving the box cancels
function startRename(nameElement, currentName, onSave) {
    const input = el('input', 'rename');
    input.type = 'text';
    input.value = currentName;
    input.setAttribute('aria-label', `Rename ${currentName}`);
    let finished = false;
    const finish = (save) => {
        if (finished) return;
        finished = true;
        const name = input.value.trim();
        if (save && name && name !== currentName) {
            onSave(name);
        } else {
            input.replaceWith(nameElement);
        }
    };
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            finish(true);
        }
        if (e.key === 'Escape') finish(false);
    });
    input.addEventListener('blur', () => finish(false));
    // The name sits inside the row's <label>; don't let clicks in the box tick the habit
    input.addEventListener('click', (e) => e.preventDefault());
    nameElement.replaceWith(input);
    input.focus();
    input.select();
}

function rowActions(nameElement, currentName, onRename, onDelete, extraButtons) {
    const actions = el('div', 'actions');
    (extraButtons || []).forEach(button => actions.appendChild(button));
    actions.appendChild(textButton('Rename', 'text-button', () => startRename(nameElement, currentName, onRename)));
    actions.appendChild(confirmButton('Delete', 'text-button danger', onDelete));
    return actions;
}

// ---------- data ----------

async function fetchHabits() {
    const habits = await api('GET', '/habits');
    if (habits) {
        state.habits = habits;
        render();
    }
}

async function fetchTasks() {
    const tasks = await api('GET', '/tasks');
    if (tasks) {
        state.tasks = tasks;
        render();
    }
}

async function addHabit(name) {
    if (await api('POST', '/habits', { name, created: localDateString(new Date()) })) fetchHabits();
}

async function renameHabit(id, name) {
    await api('PATCH', `/habits/${id}`, { name });
    fetchHabits();
}

async function deleteHabit(id) {
    await api('DELETE', `/habits/${id}`);
    fetchHabits();
}

// Move a habit one place up (-1) or down (+1) the list
async function moveHabit(id, direction) {
    const ids = state.habits.map(habit => habit.id);
    const from = ids.indexOf(id);
    const to = from + direction;
    if (to < 0 || to >= ids.length) return;
    [ids[from], ids[to]] = [ids[to], ids[from]];
    await api('PUT', '/habits/order', { ids });
    fetchHabits();
}

async function fetchDays() {
    const days = await api('GET', '/days');
    if (days) {
        state.days = {};
        days.forEach(day => { state.days[day.date] = { rating: day.rating, note: day.note }; });
        render();
    }
}

// Save part of a day's entry ({rating} or {note}) and keep the local copy in step
async function saveDay(dateString, changes) {
    const saved = await api('PUT', `/days/${dateString}`, changes);
    if (!saved) return false;
    if (saved.rating === null && !saved.note) delete state.days[dateString];
    else state.days[dateString] = { rating: saved.rating, note: saved.note };
    return true;
}

async function addTask(name) {
    if (await api('POST', '/tasks', { name })) fetchTasks();
}

async function markTaskDone(id) {
    await api('PATCH', `/tasks/${id}`, { last_done: localDateString(new Date()) });
    fetchTasks();
}

async function undoTaskToday(id) {
    await api('DELETE', `/tasks/${id}/log/${localDateString(new Date())}`);
    fetchTasks();
}

async function renameTask(id, name) {
    await api('PATCH', `/tasks/${id}`, { name });
    fetchTasks();
}

async function deleteTask(id) {
    await api('DELETE', `/tasks/${id}`);
    fetchTasks();
}

// ---------- Today ----------

function habitCaption(habit, today) {
    const stats = habitStats(new Set(habit.done), today);
    return `Streak ${pluralDays(stats.current)} · Best ${stats.best}`;
}

// The headline count and progress line, which change with every tick
function renderTally() {
    const dayString = localDateString(state.day);
    const total = state.habits.length;
    const done = state.habits.filter(habit => habit.done.includes(dayString)).length;

    const tally = document.getElementById('tally');
    tally.innerHTML = '';
    tally.className = 'tally' + (total > 0 && done === total ? ' complete' : '');
    if (total > 0) {
        tally.appendChild(el('span', 'count', String(done)));
        tally.appendChild(el('span', 'total', `of ${total}`));
        tally.setAttribute('aria-label', `${done} of ${total} habits done`);
    }
    document.getElementById('progress-bar').style.width = total ? `${(done / total) * 100}%` : '0';
}

// Tick or untick a habit for the day on screen. The row updates at once; the server follows.
async function setHabitDay(habit, row, done) {
    const dayString = localDateString(state.day);
    habit.done = habit.done.filter(d => d !== dayString);
    if (done) habit.done = [...habit.done, dayString].sort();

    row.classList.toggle('done', done);
    row.querySelector('.label').textContent = habitCaption(habit, startOfToday());
    row.querySelector('.week i:last-child').classList.toggle('on', done);
    renderTally();

    const saved = await api('PUT', `/habits/${habit.id}/history/${dayString}`, { done });
    if (!saved) fetchHabits();
}

function renderToday() {
    const today = startOfToday();
    const day = state.day;
    const dayString = localDateString(day);
    const daysAgo = daysBetween(day, today);

    document.getElementById('view-today').classList.toggle('past', daysAgo > 0);
    document.getElementById('day-label').textContent =
        daysAgo === 0 ? 'Today' : daysAgo === 1 ? 'Yesterday' : `${daysAgo} days ago`;
    const title = document.getElementById('day-title');
    title.innerHTML = '';
    title.appendChild(el('em', '', `${day.toLocaleDateString('en-US', { weekday: 'long' })},`));
    title.appendChild(document.createElement('br'));
    title.appendChild(document.createTextNode(`${day.getDate()} ${day.toLocaleDateString('en-US', { month: 'long' })}`));
    document.getElementById('day-next').disabled = daysAgo === 0;
    document.getElementById('day-today').hidden = daysAgo === 0;
    renderTally();

    const habitList = document.getElementById('habit-list');
    habitList.innerHTML = '';
    if (state.habits.length === 0) {
        habitList.appendChild(el('li', 'empty', 'Nothing here yet. Add the first habit below.'));
    }

    state.habits.forEach((habit, i) => {
        const done = new Set(habit.done);
        const li = document.createElement('li');
        const row = el('label', 'habit' + (done.has(dayString) ? ' done' : ''));

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = done.has(dayString);
        checkbox.setAttribute('aria-label', `${habit.name}, ${shortDate(day)}`);
        checkbox.addEventListener('change', () => setHabitDay(habit, row, checkbox.checked));

        const body = document.createElement('div');
        const name = el('div', 'name');
        const nameText = el('span', 'name-text', habit.name);
        name.appendChild(nameText);
        body.appendChild(name);
        body.appendChild(el('p', 'label', habitCaption(habit, today)));

        // The seven days ending on the day shown, oldest first
        const week = el('span', 'week');
        week.setAttribute('aria-hidden', 'true');
        for (let back = 6; back >= 0; back--) {
            week.appendChild(el('i', done.has(localDateString(addDays(day, -back))) ? 'on' : ''));
        }

        const tick = el('span', 'tick');
        const check = svg('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' });
        check.appendChild(svg('path', { d: 'M4 12.5 L10 18.5 L20 6' }));
        tick.appendChild(check);

        row.appendChild(checkbox);
        row.appendChild(el('span', 'index', String(i + 1).padStart(2, '0')));
        row.appendChild(body);
        row.appendChild(week);
        row.appendChild(tick);

        const up = textButton('↑ Up', 'text-button', () => moveHabit(habit.id, -1));
        const down = textButton('↓ Down', 'text-button', () => moveHabit(habit.id, 1));
        up.disabled = i === 0;
        down.disabled = i === state.habits.length - 1;
        up.setAttribute('aria-label', `Move ${habit.name} up`);
        down.setAttribute('aria-label', `Move ${habit.name} down`);

        li.appendChild(row);
        li.appendChild(rowActions(nameText, habit.name,
            (newName) => renameHabit(habit.id, newName), () => deleteHabit(habit.id), [up, down]));
        habitList.appendChild(li);
    });

    renderDayEntry();
    renderTasks(today);
}

function ratingMark(value) {
    const mark = el('span', `mark level-${value}`);
    mark.appendChild(document.createElement('i'));
    mark.setAttribute('aria-hidden', 'true');
    return mark;
}

// The note box grows with its text instead of scrolling
function fitNote() {
    const note = document.getElementById('day-note');
    note.style.height = 'auto';
    note.style.height = `${note.scrollHeight}px`;
}

// A note is saved shortly after typing stops, and at once when leaving the box or the day
const pendingNote = { timer: null, date: null };

async function flushNote() {
    if (pendingNote.date === null) return;
    clearTimeout(pendingNote.timer);
    const date = pendingNote.date;
    pendingNote.date = null;
    const saved = await saveDay(date, { note: document.getElementById('day-note').value });
    if (pendingNote.date === null) document.getElementById('note-status').textContent = saved ? 'Saved' : 'Not saved';
}

function noteChanged() {
    fitNote();
    clearTimeout(pendingNote.timer);
    pendingNote.date = localDateString(state.day);
    pendingNote.timer = setTimeout(flushNote, 700);
    document.getElementById('note-status').textContent = 'Saving…';
}

// Go to another day on the Today view, saving any half-typed note for the day being left first
async function showDay(date) {
    await flushNote();
    document.getElementById('note-status').textContent = '';
    state.day = date;
    render();
}

function renderDayEntry() {
    const dayString = localDateString(state.day);
    const entry = state.days[dayString] || { rating: null, note: '' };

    const rating = document.getElementById('rating');
    rating.innerHTML = '';
    RATINGS.forEach(({ value, label }) => {
        const selected = entry.rating === value;
        const button = el('button');
        button.type = 'button';
        button.setAttribute('role', 'radio');
        button.setAttribute('aria-checked', String(selected));
        button.appendChild(ratingMark(value));
        button.appendChild(document.createTextNode(label));
        // Pressing the chosen rating again clears it
        button.addEventListener('click', async () => {
            await saveDay(dayString, { rating: selected ? null : value });
            renderDayEntry();
        });
        rating.appendChild(button);
    });

    // Leave the box alone while it is being typed in
    const note = document.getElementById('day-note');
    if (document.activeElement !== note && pendingNote.date === null) {
        note.value = entry.note;
        fitNote();
    }
}

function renderTasks(today) {
    const taskList = document.getElementById('task-list');
    taskList.innerHTML = '';
    if (state.tasks.length === 0) {
        taskList.appendChild(el('li', 'empty', 'Nothing is being counted yet.'));
    }

    state.tasks.forEach(task => {
        const li = document.createElement('li');
        const row = el('div', 'task');
        const name = el('span', 'name', task.name);

        const since = el('span', 'since');
        if (!task.last_done) {
            since.appendChild(el('b', '', 'Never'));
        } else {
            const days = Math.max(0, daysBetween(parseLocalDate(task.last_done), today));
            if (days === 0) {
                since.appendChild(el('b', '', 'Today'));
            } else {
                since.appendChild(el('b', '', String(days)));
                since.appendChild(el('span', 'label', days === 1 ? 'day ago' : 'days ago'));
            }
        }

        row.appendChild(name);
        row.appendChild(since);
        // Once it's done today the button takes it back instead
        const doneToday = task.last_done === localDateString(today);
        row.appendChild(doneToday
            ? textButton('Undo', 'box-button', () => undoTaskToday(task.id))
            : textButton('Done today', 'box-button', () => markTaskDone(task.id)));

        li.appendChild(row);
        li.appendChild(rowActions(name, task.name,
            (newName) => renameTask(task.id, newName), () => deleteTask(task.id)));
        taskList.appendChild(li);
    });
}

// ---------- Record ----------

function renderFigures(summary) {
    const figures = document.getElementById('figures');
    figures.innerHTML = '';
    const add = (label, value, note) => {
        const figure = el('div', 'figure');
        figure.appendChild(el('p', 'label', label));
        figure.appendChild(el('div', 'value', value));
        figure.appendChild(el('div', 'note', note));
        figures.appendChild(figure);
    };

    const best = summary.weekdays.filter(w => w.rate !== null).sort((a, b) => b.rate - a.rate)[0];
    add('Completion', formatPercent(summary.rate),
        summary.change === null ? 'nothing earlier to compare' : `${formatChange(summary.change)} on the period before`);
    add('Check-offs', String(summary.done), `of ${summary.active} possible`);
    add('Perfect days', String(summary.perfectDays), `of ${pluralDays(summary.countedDays)}`);
    add('Best weekday', best && best.done > 0 ? best.name : '—',
        best && best.done > 0 ? `${formatPercent(best.rate)} done` : 'no check-offs yet');
}

function renderChart(summary) {
    const container = document.getElementById('chart');
    container.innerHTML = '';
    const width = Math.max(280, container.clientWidth);
    const left = 34;
    // Group into weeks when there are too many days, or the screen is too narrow, for a readable bar per day
    const weekly = summary.daily.length > MAX_DAILY_BARS || (width - left) / summary.daily.length < MIN_BAR_SLOT;
    const points = weekly ? weeklySeries(summary.daily) : summary.daily;
    document.getElementById('chart-unit').textContent = weekly ? 'Share of habits done, per week' : 'Share of habits done, per day';
    const top = 6;
    const plotHeight = 150;
    const height = top + plotHeight + 30;
    const plotWidth = width - left;
    const slot = plotWidth / points.length;
    const barWidth = Math.max(1, Math.min(slot - 2, 30));

    const chart = svg('svg', { viewBox: `0 0 ${width} ${height}`, height, role: 'img',
        'aria-label': `Share of habits done per ${weekly ? 'week' : 'day'}, ${PERIOD_TITLES[state.period].toLowerCase()}` });

    for (const percent of [0, 50, 100]) {
        const y = top + plotHeight - (percent / 100) * plotHeight;
        chart.appendChild(svg('line', { class: 'grid', x1: left, x2: width, y1: y, y2: y }));
        const label = svg('text', { x: 0, y: y + 3 });
        label.textContent = `${percent}%`;
        chart.appendChild(label);
    }

    // Label every bar when there is room, otherwise four or five evenly spaced ones
    const labelEvery = points.length <= 14 && slot >= 30 ? 1 : Math.ceil(points.length / (width < 420 ? 4 : 5));
    points.forEach((point, i) => {
        const x = left + i * slot;
        const rate = point.active ? point.done / point.active : null;
        if (rate) {
            const barHeight = Math.max(2, rate * plotHeight);
            chart.appendChild(svg('rect', { class: 'bar', x: x + (slot - barWidth) / 2, y: top + plotHeight - barHeight,
                width: barWidth, height: barHeight }));
        }

        if ((points.length - 1 - i) % labelEvery === 0) {
            const label = svg('text', { x: x + slot / 2, y: top + plotHeight + 16, 'text-anchor': 'middle' });
            label.textContent = labelEvery === 1 && !weekly
                ? `${WEEKDAYS[weekdayIndex(point.date)].slice(0, 2)} ${point.date.getDate()}`
                : `${point.date.getDate()} ${point.date.toLocaleDateString('en-US', { month: 'short' })}`;
            // Keep the last label inside the plot
            if (x + slot / 2 > width - 24) {
                label.setAttribute('text-anchor', 'end');
                label.setAttribute('x', width);
            }
            chart.appendChild(label);
        }

        const when = weekly ? `${shortDate(point.date)} – ${shortDate(point.end)}` : shortDate(point.date);
        const what = point.active ? `${point.done} of ${point.active} (${formatPercent(rate)})` : 'no habits yet';
        chart.appendChild(svg('rect', { class: 'hit', x, y: top, width: slot, height: plotHeight, 'data-tip': `${when} · ${what}` }));
    });

    container.appendChild(chart);
}

function renderWeekdays(summary) {
    const container = document.getElementById('weekdays');
    container.innerHTML = '';
    for (const weekday of summary.weekdays) {
        const row = el('div', 'weekday');
        row.appendChild(el('span', 'label', weekday.name));
        const track = el('div', 'track');
        const fill = document.createElement('div');
        fill.style.width = `${(weekday.rate || 0) * 100}%`;
        track.appendChild(fill);
        row.appendChild(track);
        row.appendChild(el('span', 'pct', formatPercent(weekday.rate)));
        row.setAttribute('data-tip', weekday.active ? `${weekday.name} · ${weekday.done} of ${weekday.active}` : `${weekday.name} · no data`);
        container.appendChild(row);
    }
}

// One square per day. Short periods are a single strip; longer ones stack weeks as columns.
// describe(date, dateString) returns null to leave a day blank, or { tip, on } for a habit square,
// or { tip, level } for a rating, drawn as a coloured bar filling a third, two thirds or all of the square.
function renderCalendar(range, today, width, describe) {
    const todayString = localDateString(today);
    const cell = (date, x, y, size) => {
        const dateString = localDateString(date);
        const day = date <= today ? describe(date, dateString) : null;
        const group = [];
        if (day) {
            group.push(svg('rect', { class: 'cell' + (day.on ? ' on' : ''), x, y, width: size, height: size, 'data-tip': day.tip }));
            if (day.level) {
                const height = Math.max(2, Math.round(size * day.level / 3));
                group.push(svg('rect', { class: `fill-${day.level}`, x, y: y + size - height, width: size, height, 'pointer-events': 'none' }));
            }
        }
        if (dateString === todayString) {
            group.push(svg('rect', { class: 'cell-today', x, y: y + size + 2, width: size, height: 2 }));
        }
        return group;
    };

    if (range.days <= 31) {
        const size = Math.max(6, Math.min(22, Math.floor((width - (range.days - 1) * 2) / range.days)));
        const labelled = range.days <= 14;
        const chart = svg('svg', { width: range.days * (size + 2), height: size + (labelled ? 20 : 6) });
        for (let i = 0; i < range.days; i++) {
            const date = addDays(range.from, i);
            cell(date, i * (size + 2), 0, size).forEach(node => chart.appendChild(node));
            if (labelled) {
                const label = svg('text', { x: i * (size + 2) + size / 2, y: size + 16, 'text-anchor': 'middle' });
                label.textContent = date.getDate();
                chart.appendChild(label);
            }
        }
        return chart;
    }

    const earliest = addDays(today, -(MAX_CALENDAR_WEEKS * 7 - 1));
    const from = range.from > earliest ? range.from : earliest;
    const gridStart = addDays(from, -weekdayIndex(from));
    const weeks = Math.floor(daysBetween(gridStart, today) / 7) + 1;
    const left = 16;
    const top = 14;
    // On a narrow screen a year doesn't fit; the squares stay readable and the strip scrolls sideways
    const size = Math.max(9, Math.min(15, Math.floor((width - left) / weeks) - 2));
    const chart = svg('svg', { width: left + weeks * (size + 2) + 14, height: top + 7 * (size + 2) + 4 });

    ['M', '', 'W', '', 'F', '', ''].forEach((letter, row) => {
        if (!letter) return;
        const label = svg('text', { x: 0, y: top + row * (size + 2) + size - 1 });
        label.textContent = letter;
        chart.appendChild(label);
    });

    let lastLabelWeek = -4;
    for (let week = 0; week < weeks; week++) {
        for (let row = 0; row < 7; row++) {
            const date = addDays(gridStart, week * 7 + row);
            if (date < from || date > today) continue;
            cell(date, left + week * (size + 2), top + row * (size + 2), size).forEach(node => chart.appendChild(node));
            // Name each month above the week it starts in, unless that would crowd the previous name
            if (date.getDate() === 1 && week - lastLabelWeek >= 3) {
                const label = svg('text', { x: left + week * (size + 2), y: 9 });
                label.textContent = date.toLocaleDateString('en-US', { month: 'short' });
                chart.appendChild(label);
                lastLabelWeek = week;
            }
        }
    }
    return chart;
}

function renderEntries(summary, today) {
    const container = document.getElementById('entries');
    container.innerHTML = '';
    if (summary.entries.length === 0) {
        container.appendChild(el('p', 'empty', 'No habits yet.'));
        return;
    }
    const width = container.clientWidth || 700;

    for (const entry of sortEntries(summary.entries, state.sort)) {
        const block = el('article', 'entry');
        block.dataset.habit = entry.habit.name;

        const head = el('div', 'entry-head');
        head.appendChild(el('span', 'name', entry.habit.name));
        const rate = el('span', 'rate', formatPercent(entry.rate));
        if (entry.change !== null) rate.appendChild(el('small', '', formatChange(entry.change)));
        head.appendChild(rate);

        const track = el('div', 'track');
        const fill = document.createElement('div');
        fill.style.width = `${(entry.rate || 0) * 100}%`;
        track.appendChild(fill);

        const caption = entry.active
            ? `${entry.done} of ${pluralDays(entry.active)} · Streak ${entry.streak} · Best ${entry.best}`
            : 'Not started in this period';

        const done = new Set(entry.habit.done);
        const start = habitStart(entry.habit, today);
        const calendar = el('div', 'calendar');
        calendar.appendChild(renderCalendar(summary.range, today, width, (date, dateString) => date < start ? null : {
            on: done.has(dateString),
            tip: `${shortDate(date)} · ${done.has(dateString) ? 'done' : 'missed'}`,
        }));

        block.appendChild(head);
        block.appendChild(track);
        block.appendChild(el('p', 'label', caption));
        block.appendChild(calendar);
        container.appendChild(block);
        // Start scrolled to the most recent days
        calendar.scrollLeft = calendar.scrollWidth;
    }
}

function ratingLabel(value) {
    const rating = RATINGS.find(r => r.value === value);
    return rating ? rating.label : 'Not rated';
}

function renderRatings(summary, today) {
    const fromString = localDateString(summary.range.from);
    const lastString = localDateString(summary.range.to);
    const inRange = Object.keys(state.days).filter(d => d >= fromString && d <= lastString).sort();

    // The legend doubles as the count of each rating in the period
    const legend = document.getElementById('rating-legend');
    legend.innerHTML = '';
    [...RATINGS].reverse().forEach(({ value, label }) => {
        const item = document.createElement('span');
        item.appendChild(ratingMark(value));
        item.appendChild(document.createTextNode(label));
        item.appendChild(el('b', '', String(inRange.filter(d => state.days[d].rating === value).length)));
        legend.appendChild(item);
    });
    const unrated = el('span');
    unrated.appendChild(document.createTextNode('Not rated'));
    unrated.appendChild(el('b', '', String(summary.range.days - inRange.filter(d => state.days[d].rating).length)));
    legend.appendChild(unrated);

    const calendar = document.getElementById('rating-calendar');
    calendar.innerHTML = '';
    calendar.appendChild(renderCalendar(summary.range, today, calendar.clientWidth || 700, (date, dateString) => {
        const rating = state.days[dateString] ? state.days[dateString].rating : null;
        return { level: rating, tip: `${shortDate(date)} · ${ratingLabel(rating).toLowerCase()}` };
    }));
    calendar.scrollLeft = calendar.scrollWidth;

    // What was written, newest first
    const notes = document.getElementById('notes');
    notes.innerHTML = '';
    const written = inRange.filter(d => state.days[d].note).reverse();
    written.slice(0, MAX_NOTES_SHOWN).forEach(dateString => {
        const entry = state.days[dateString];
        const row = el('div', 'note');
        const when = el('div', 'when');
        if (entry.rating) when.appendChild(ratingMark(entry.rating));
        when.appendChild(el('span', 'label', `${shortDate(parseLocalDate(dateString))} · ${ratingLabel(entry.rating)}`));
        row.appendChild(when);
        row.appendChild(el('div', 'text', entry.note));
        notes.appendChild(row);
    });
    if (written.length === 0) {
        notes.appendChild(el('p', 'empty', 'Nothing written in this period.'));
    } else if (written.length > MAX_NOTES_SHOWN) {
        notes.appendChild(el('p', 'label more', `Showing the latest ${MAX_NOTES_SHOWN} of ${written.length} notes. Choose a shorter period to narrow them down.`));
    }
}

function renderLogs(today) {
    const container = document.getElementById('logs');
    container.innerHTML = '';
    if (state.tasks.length === 0) {
        container.appendChild(el('p', 'empty', 'Nothing is being counted yet.'));
        return;
    }
    for (const task of state.tasks) {
        const row = el('div', 'log');
        row.appendChild(el('span', 'name', task.name));
        row.appendChild(el('span', 'label', `Done ${task.log.length} ${task.log.length === 1 ? 'time' : 'times'}`));

        const interval = averageInterval(task.log);
        const parts = [];
        if (task.last_done) {
            const days = Math.max(0, daysBetween(parseLocalDate(task.last_done), today));
            parts.push(`Last on ${shortDate(parseLocalDate(task.last_done))}${days ? `, ${pluralDays(days)} ago` : ', today'}`);
        } else {
            parts.push('Never done');
        }
        if (interval !== null) parts.push(`about every ${pluralDays(Math.round(interval))}`);
        row.appendChild(el('span', 'detail', parts.join(' · ')));
        container.appendChild(row);
    }
}

function renderRecord() {
    const today = startOfToday();
    const summary = recordSummary(state.habits, state.period, today, Object.keys(state.days));

    document.getElementById('record-title').textContent = PERIOD_TITLES[state.period];
    document.getElementById('record-range').textContent = summary.range.days === 1
        ? longDate(today)
        : `${longDate(summary.range.from)} to ${longDate(summary.range.to)}`;
    document.querySelectorAll('#periods button').forEach(button =>
        button.setAttribute('aria-pressed', String(button.dataset.period === state.period)));
    document.querySelectorAll('#sorts button').forEach(button => {
        const active = button.dataset.sort === state.sort.key;
        button.setAttribute('aria-pressed', String(active));
        button.textContent = SORT_LABELS[button.dataset.sort] + (active ? (state.sort.descending ? ' ↓' : ' ↑') : '');
    });

    renderFigures(summary);
    renderRatings(summary, today);
    renderChart(summary);
    renderWeekdays(summary);
    renderEntries(summary, today);
    renderLogs(today);
}

// ---------- page ----------

function currentView() {
    return location.hash === '#/record' ? 'record' : 'today';
}

function render() {
    const view = currentView();
    document.getElementById('view-today').hidden = view !== 'today';
    document.getElementById('view-record').hidden = view !== 'record';
    document.querySelectorAll('.masthead a').forEach(link => {
        if (link.dataset.view === view) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
    });
    if (view === 'today') renderToday();
    else renderRecord();
}

document.getElementById('habit-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const habitInput = document.getElementById('habit-input').value.trim();
    if (habitInput) {
        addHabit(habitInput);
        document.getElementById('habit-input').value = '';
    }
});

document.getElementById('task-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const taskInput = document.getElementById('task-input').value.trim();
    if (taskInput) {
        addTask(taskInput);
        document.getElementById('task-input').value = '';
    }
});

document.getElementById('day-prev').addEventListener('click', () => showDay(addDays(state.day, -1)));
document.getElementById('day-next').addEventListener('click', () => {
    if (state.day < startOfToday()) showDay(addDays(state.day, 1));
});
document.getElementById('day-today').addEventListener('click', () => showDay(startOfToday()));

document.getElementById('day-note').addEventListener('input', noteChanged);
document.getElementById('day-note').addEventListener('blur', flushNote);
// Don't lose the last few words if the page is closed straight after typing
window.addEventListener('pagehide', () => {
    if (pendingNote.date === null) return;
    fetch(`/days/${pendingNote.date}`, { method: 'PUT', keepalive: true, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: document.getElementById('day-note').value }) });
});

// Either Edit button turns editing on for both lists: reordering, renaming and deleting
document.querySelectorAll('.edit-toggle').forEach(toggle => {
    toggle.addEventListener('click', () => {
        const editing = document.body.classList.toggle('editing');
        document.querySelectorAll('.edit-toggle').forEach(button => {
            button.setAttribute('aria-pressed', String(editing));
            button.textContent = editing ? 'Done editing' : button.dataset.label;
        });
    });
});

document.getElementById('periods').addEventListener('click', (e) => {
    const period = e.target.dataset.period;
    if (!period) return;
    state.period = period;
    saveSetting('period', period);
    render();
});

document.getElementById('sorts').addEventListener('click', (e) => {
    const key = e.target.dataset.sort;
    if (!key) return;
    // Clicking the current sort flips it; a new one starts highest-first (A to Z for names)
    state.sort = key === state.sort.key
        ? { key, descending: !state.sort.descending }
        : { key, descending: key !== 'name' };
    saveSetting('sort', state.sort);
    render();
});

// ---------- light / dark ----------
// With no saved choice the page follows the device; the toggle pins one or the other on this device.

const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

function currentTheme() {
    return document.documentElement.dataset.theme || (systemDark.matches ? 'dark' : 'light');
}

function renderThemeToggle() {
    const other = currentTheme() === 'dark' ? 'light' : 'dark';
    const toggle = document.getElementById('theme-toggle');
    toggle.textContent = other === 'dark' ? 'Dark' : 'Light';
    toggle.setAttribute('aria-label', `Switch to ${other} mode`);
    // Colour the phone browser's own bars to match the page
    document.querySelector('meta[name="theme-color"]').content =
        getComputedStyle(document.documentElement).getPropertyValue('--paper').trim();
}

document.getElementById('theme-toggle').addEventListener('click', () => {
    const theme = currentTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    saveSetting('theme', theme);
    renderThemeToggle();
});
systemDark.addEventListener('change', renderThemeToggle);
renderThemeToggle();

window.addEventListener('hashchange', async () => {
    await flushNote();
    render();
});

let resizeTimer = null;
window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
        if (currentView() === 'record') render();
    }, 150);
});

// Hover details for anything carrying a data-tip attribute
const tip = document.getElementById('tip');
document.addEventListener('pointermove', (e) => {
    const target = e.target.closest ? e.target.closest('[data-tip]') : null;
    if (!target) {
        tip.hidden = true;
        return;
    }
    tip.textContent = target.getAttribute('data-tip');
    tip.hidden = false;
    const box = tip.getBoundingClientRect();
    tip.style.left = `${Math.max(8, Math.min(e.clientX + 12, window.innerWidth - box.width - 8))}px`;
    tip.style.top = `${e.clientY - box.height - 12 < 8 ? e.clientY + 16 : e.clientY - box.height - 12}px`;
});
document.addEventListener('pointerleave', () => { tip.hidden = true; });

// Initial load
let shownDate = localDateString(new Date());
render();
fetchHabits();
fetchTasks();
fetchDays();

// A page left open overnight moves on to the new day by itself
setInterval(() => {
    const now = localDateString(new Date());
    if (now !== shownDate) {
        // Follow the new day unless a past day is on screen or a note is being typed
        const typing = document.activeElement === document.getElementById('day-note') || pendingNote.date !== null;
        if (localDateString(state.day) === shownDate && !typing) state.day = startOfToday();
        shownDate = now;
        fetchHabits();
        fetchTasks();
        fetchDays();
    }
}, 60 * 1000);
