# Design guide

Read this before changing anything the user sees. The owner chose this look on purpose and asked that it stay cohesive, sophisticated and not generic. New UI should look like it was always part of the page.

## The idea

A printed ledger or almanac, not an app dashboard. Warm paper, black ink, thin rules, generous white space, a literary serif for content and a small typewriter-like mono for labels. Things sit on the page separated by rules; nothing floats in a card.

When in doubt, remove decoration. If a new element needs a box, a shadow, an icon or a new colour to be noticed, the layout is wrong.

## Never

- Rounded corners, drop shadows, gradients, glows, blur, cards, pills, badges. (The one round shape is the half-disc on the light/dark toggle.)
- Emoji or icon fonts. Arrows and marks are plain text characters (← → ↑ ↓ ▲ ▼ ·) or small inline SVG.
- New colours. Everything comes from the variables at the top of `static/style.css`.
- A sans-serif. There are two typefaces and both are served locally from `static/fonts/`.
- Anything loaded from the internet: no CDNs, web fonts, analytics or frameworks. The page must work with the internet down.
- Browser `alert` / `confirm` / `prompt`. Confirmation is built into the page.

## Colour

Every colour has one job. Do not borrow a colour for another job.

| Variable | Light | Dark | Job |
| --- | --- | --- | --- |
| `--paper` | `#f4efe6` | `#15130f` | Page ground. The only background. |
| `--ink` | `#1a1814` | `#ece6da` | Text, names, figures, rules that open a section, outlines of controls. |
| `--muted` | `#6b655a` | `#9b9385` | Labels, captions, placeholders, anything secondary. |
| `--rule` / `--faint` | ink at 18% / 9% | ink at 22% / 10% | Hairlines between rows; empty tracks and empty calendar squares. |
| `--primary` | `#27406f` Prussian blue | `#a3b8e8` | Done, chosen or current: ticks, chart bars, filled calendar squares, the selected segment of a control, the current page, section headings, the weekday in the headline. |
| `--accent` | `#b5371b` vermilion | `#e8683f` | Rare. Today's marker, a fully finished day, editing a past day, Delete, the focus ring, error messages. |
| `--bad` `--okay` `--good` | `#a52e18` `#d2a020` `#2e9c86` | `#d9532c` `#c99a2c` `#2f9f84` | The day rating only. |

Rules that follow from this:

- Body text and numbers are always ink or muted, never blue, red or a rating colour. Colour goes on a mark beside the text.
- Roughly: the page is paper and ink, blue is a tenth of it, vermilion is a few pixels.
- A rating is never shown by colour alone. It always has a text label, and its mark fills a third, two thirds or all of its square. Keep that when adding anything that shows ratings.
- Dark mode is not an inversion: each colour has its own chosen dark value. The dark values appear twice in the stylesheet (device preference, and the toggle). Change both.
- Before changing `--primary` or the rating colours, check them for colour-blind separation against each other and against both grounds. The current set was checked with the validator in the `dataviz` skill.

## Type

| Use | Face | Size | Notes |
| --- | --- | --- | --- |
| Headline (the date, the period) | Fraunces 380 | `clamp(44px, 11vw, 84px)` | Tight leading and tracking. One part may be italic and blue. |
| Section heading | Fraunces 400 italic | 26px | Blue. Sits on an ink rule. |
| Names (habits, tasks) | Fraunces | 22 to 30px | Ink. |
| Figures | Fraunces 380 | 30 to 44px | Ink. |
| Body, notes, inputs | Fraunces | 18px | Placeholders are italic and muted. |
| Labels, buttons, captions, chart text | IBM Plex Mono 500 | 11px (9 to 10px inside charts) | Uppercase, letter-spaced `0.12em`, muted unless it is a control. |

Do not add sizes between these. Inputs must stay at 16px or more or phones zoom the page on focus.

## Layout

- One column, 760px at most, centred. Sections are separated by space (64px above a section heading) and a rule, not by boxes.
- Rules: 1px ink opens a section or frames a control; 1px `--rule` separates rows. Nothing else draws a line.
- Corners are square. Controls are outlined in 1px ink.
- Lists are rows between hairlines with the name on the left and the action or figure on the right.

## Components to reuse

Use these classes before inventing a new control.

- `.label` — the small uppercase mono caption.
- `.text-button` — a plain uppercase text action (Add, Rename, Previous day). `.text-button.danger` for Delete.
- `.box-button` — an outlined action that needs more weight (Done today, Undo).
- Segmented control — a row of joined outlined buttons with the chosen one filled blue (`.periods`, `.rating`). Use for a choice among two to five options.
- `.section-head` — italic blue heading on an ink rule, with an optional control or label on the right.
- `.rows` — a list separated by hairlines. `.actions` under a row holds its edit-mode buttons.
- `.add` — an underlined text input with a text button, for adding to a list.
- `.track` — a thin horizontal bar for a share of 100%.
- `renderCalendar()` in `script.js` — the strip or week grid of day squares. Use it for anything shown per day.
- `[data-tip]` — any element with this attribute gets the hover tooltip.

## Behaviour

- **Today is the home page** and ticking is its main job: the whole habit row is the target, the tick box is 44px, and it responds instantly (the save follows).
- **Nothing destructive happens on one press.** Delete asks for a second press within four seconds. Actions that are easy to trigger by accident get an Undo (tasks).
- **Editing is a mode.** Reordering, renaming and deleting are hidden until an Edit button is pressed, so the everyday page stays clean. Every list must have its Edit button right beside it: a user who cannot find Delete will conclude it does not exist.
- **Text saves itself.** No Save buttons. Show a quiet status ("Saving…", "Saved") and never overwrite a box someone is typing in.
- **Errors appear in the banner at the top** using the server's own message. Never fail silently.
- **Remember view choices on the device** (period, sort, theme) with `saveSetting`.
- **Empty states** are one italic muted sentence saying what to do.

## Charts

- One series, one colour: blue on a faint track or faint grid. No legends for a single series; the heading names it.
- Thin marks, a 2px gap between bars, solid hairline grid, labels in muted mono. Label a few points, not every one.
- Every mark has a hover tooltip, and the exact numbers are also on the page as text.
- Too many days for the width become weekly bars. Do not draw bars thinner than about 3px.
- A habit's rate only counts days since the habit started.

## Phones

- Must work from 320px wide with no sideways scrolling. Only a calendar may scroll sideways, inside its own strip.
- Anything tappable is at least 40px tall on a phone (the `pointer: coarse` / `max-width: 560px` block).
- The index numbers and week dots on habit rows are hidden on phones; rows become name plus tick.

## Accessibility

- Real controls: buttons are `<button>`, ticks are checkboxes inside labels, the rating is a radio group, toggles carry `aria-pressed`.
- Visible focus ring (vermilion) on everything focusable.
- Respect `prefers-reduced-motion`. Motion is limited to the tick drawing itself and the progress line.
- User-entered text goes in with `textContent`, never `innerHTML`.

## Checking a change

```bash
pytest                 # backend
tests/e2e/run.sh       # the page, in a headless browser, on a throwaway instance
```

The browser checks cover behaviour, the exact colours, phone widths from 320 to 430px and both themes, and save screenshots to `tests/e2e/shots/`. Passing checks do not prove it looks right: open the screenshots (light, dark, desktop, phone) and look at them before calling a visual change done. Add a check to the matching script for any new behaviour.
