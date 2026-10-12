# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A small, locally-hosted habit tracker that runs on a home server. Flask backend, SQLite storage, a single vanilla-JS page with hand-written CSS. No build step, no linter, no frontend dependencies.

## Running

On the home server it runs in Docker:

```bash
docker compose up -d --build   # rebuild and restart after code changes
docker compose logs -f
```

For local development:

```bash
./setup.sh              # creates venv/ and installs requirements.txt
source venv/bin/activate
python app.py
```

Serves on port 5000 on all interfaces either way.

- In Docker the app runs under gunicorn (one worker, four threads) as uid 1000, with `restart: unless-stopped`.
- The Docker database is `./data/data.db` on the host (bind-mounted to `/data`). Local development uses `data.db` in the working directory instead. Both are gitignored.
- `.env` settings for compose: `HABIT_BIND` (address to publish the port on, default `0.0.0.0`), `HABIT_UID` / `HABIT_GID` (default 1000; must own `./data`).
- App env vars: `DB_PATH`, `BACKUP_DIR` (default `backups/` next to the database), `BACKUP_KEEP` (daily backups to keep, default 14, 0 disables).

## Tests

```bash
pip install pytest
pytest
```

`tests/test_app.py` covers the API, the schema migrations, and backups.

```bash
tests/e2e/run.sh             # browser checks, all three scripts
tests/e2e/run.sh layout.py   # just one
```

The browser checks run Playwright in Docker against a throwaway instance on `127.0.0.1:5001`, so they need Docker but nothing installed on the host, and never touch the live container or its data. The first run downloads a browser image of about 2 GB. `core.py` covers Today, Record and the statistics (seeded history with hand-worked expected numbers); `day.py` covers ratings, notes, task undo, reordering and removing habits; `layout.py` covers colour, the theme toggle and phone widths. The clock is faked to 22:30 on 11 Oct 2026 in Toronto, a time when the UTC date is already the next day.

## Layout

- `app.py` — the whole backend: schema, migration, backups, and all routes.
- `templates/index.html` — the single page, holding two views switched by URL hash: Today (`#/today`, the default) and Record (`#/record`).
- `static/script.js` — all frontend logic: date helpers, statistics, and rendering for both views.
- `static/style.css` — all styling. Colours and fonts are CSS variables at the top. The dark values are listed twice on purpose: once for a device that asks for dark, once for `data-theme="dark"` set by the toggle. Change both together.
- `static/fonts/` — Fraunces (variable, roman and italic) and IBM Plex Mono, served locally so the page works without internet.

## The two views

- **Today** is the main page: one row per habit to tick off for the day on screen, a count of how many are done, a Bad / Okay / Good rating and a free-text note for the day, and the "days since" tasks. Previous/next day buttons allow back-filling past days. Up/Down, Rename and Delete are hidden until an Edit button is pressed; there is one beside each list ("Edit habits", "Edit tasks") and either turns editing on for both. A task done today shows Undo instead of Done today.
- **Record** is history and trends for a chosen period (7D, 30D, 90D, 1Y, All): headline figures, the day ratings as a calendar of coloured squares with the notes listed under it, a completion chart (daily bars, weekly above 92 days), a weekday breakdown, and one entry per habit with a calendar of squares, sortable by rate, change, streak, best streak or name. Period and sort are remembered in `localStorage`.

- The masthead has a light/dark toggle. With no saved choice the page follows the device; the toggle pins one on that device (`localStorage`, applied by a small inline script in `<head>` before first paint).
- Phone layout is the `max-width: 560px` block in the stylesheet, plus larger touch targets for coarse pointers. It was checked at 320, 360, 390 and 430 px wide.

## Design

**Read `DESIGN.md` before changing anything the user sees.** It holds the colour roles, type scale, reusable components, behaviour rules and phone requirements. In short: a printed-ledger look (paper, ink, hairline rules, square corners, Fraunces serif plus IBM Plex Mono labels); Prussian blue for what is done, chosen or current; vermilion kept rare; red / yellow / green only for the day rating; no cards, shadows, gradients, emoji, new colours or anything loaded from the internet.

After a UI change, run `tests/e2e/run.sh` and look at the screenshots it saves in `tests/e2e/shots/`.

## API

| Route | Methods | Notes |
| --- | --- | --- |
| `/` | GET | Renders the page |
| `/habits` | GET, POST | GET returns `[{id, name, created, done: ["YYYY-MM-DD", ...]}]`; POST takes `name` and the browser's local date as `created` |
| `/habits/<id>` | PATCH, DELETE | PATCH `{name}` renames |
| `/habits/order` | PUT | Body `{ids: [...]}` with every habit id once, in display order |
| `/habits/<id>/history/<date>` | PUT | Body `{done: true\|false}`; idempotent |
| `/tasks` | GET, POST | "Days since" items: `{id, name, last_done, log: [dates]}` |
| `/tasks/<id>` | PATCH, DELETE | PATCH takes `name` and/or `last_done` (date or null); a date is also added to the log |
| `/tasks/<id>/log/<date>` | DELETE | Undo: removes that day from the log; `last_done` falls back to the previous entry |
| `/days` | GET | `[{date, rating, note}]` for every day that has either |
| `/days/<date>` | PUT | Body may carry `rating` (1 bad, 2 okay, 3 good, null clears) and/or `note`; the field left out is kept |

Errors come back as `{error: "..."}` with 400 / 404 / 409, and the page shows that message.

## Data model

- `habits(id, name UNIQUE, created, position)` — `created` is the first day the habit counts from; `position` is the display order
- `habit_history(habit_id -> habits.id ON DELETE CASCADE, date, PRIMARY KEY(habit_id, date))` — a row means "done that day"; unchecking deletes the row.
- `tasks(id, name UNIQUE, last_done)`
- `task_log(task_id -> tasks.id ON DELETE CASCADE, date, PRIMARY KEY(task_id, date))` — every day a task was done
- `days(date PRIMARY KEY, rating, note)` — a row exists only while the day has a rating or a note
- `PRAGMA user_version` holds the schema version (currently 3). Older databases are migrated step by step on startup, each step after saving a copy to `backups/data-pre-migration-v<N>.db`. Add new schema changes as a new `migrate_vN` step rather than editing the existing ones.

## Things to know before changing code

- Always go through the `db()` context manager: it turns on `PRAGMA foreign_keys`, which SQLite needs per connection for the cascade delete to work.
- `init_db()` and the backup thread start at import time, so set `DB_PATH` before importing `app` (see `load_app` in the tests).
- All dates are the browser's local calendar date, built with `localDateString()`. Do not use `toISOString()` for dates: it gives the UTC date.
- All statistics (streaks, rates, the chart series) are computed in the browser from the full `done` lists, because only the browser knows the viewer's "today". A habit's rate only counts days since it started (`habitStart`), so new habits aren't penalised for days before they existed.
- Ticking a habit updates the row in place and then saves; it only re-fetches if the save fails. A full re-render there would kill the tick animation.
- The day's note saves 700 ms after typing stops, and immediately on leaving the box, changing day or view, or closing the page. `renderDayEntry` never overwrites the box while it has focus or an unsaved edit.
- Build DOM with `createElement` / `textContent`, never `innerHTML` with user-entered names.
- Backups are same-disk copies in `data/backups/`: they protect against a bad migration or accidental deletion, not against losing the disk.
- There is no auth.
