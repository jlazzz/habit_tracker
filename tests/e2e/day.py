"""Browser checks for day ratings/notes, task undo and habit reordering. Run with tests/e2e/run.sh"""
import datetime
import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
TZ = "America/Toronto"
NOW = datetime.datetime(2026, 10, 12, 2, 30, tzinfo=datetime.timezone.utc)  # 22:30 local, Sun Oct 11
TODAY = datetime.date(2026, 10, 11)
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if not cond else ""))
    if not cond:
        failures.append(name)


def api(method, path, payload=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        return json.loads(res.read())


def day(back):
    return (TODAY - datetime.timedelta(days=back)).isoformat()


def days():
    return {d["date"]: d for d in api("GET", "/days")}


with sync_playwright() as p:
    browser = p.chromium.launch()
    for name in ("Read", "Run", "Stretch"):
        api("POST", "/habits", {"name": name, "created": day(40)})
    task = api("POST", "/tasks", {"name": "Water mom's plants"})["id"]
    api("PATCH", f"/tasks/{task}", {"last_done": day(9)})
    api("PATCH", f"/tasks/{task}", {"last_done": day(2)})

    context = browser.new_context(timezone_id=TZ, locale="en-US", viewport={"width": 1000, "height": 1400})
    page = context.new_page()
    errors, alerts = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("dialog", lambda d: (alerts.append(d.message), d.dismiss()))
    page.clock.install(time=NOW)
    page.goto(BASE)
    page.wait_for_selector("#habit-list label")
    page.wait_for_selector("#rating button")

    def settle():
        page.clock.run_for(900)
        page.wait_for_timeout(150)

    # ---------- rating ----------
    buttons = page.locator("#rating button")
    check("three rating choices", [b.inner_text().strip().lower() for b in buttons.all()] == ["bad", "okay", "good"])
    check("nothing chosen at first", [b.get_attribute("aria-checked") for b in buttons.all()] == ["false"] * 3)
    buttons.nth(2).click()
    page.wait_for_selector("#rating button[aria-checked=true]")
    check("choosing Good saves 3 for the local date", days() == {day(0): {"date": day(0), "rating": 3, "note": ""}}, str(days()))
    check("Good shows as chosen", [b.get_attribute("aria-checked") for b in buttons.all()] == ["false", "false", "true"])
    buttons.nth(2).click()
    page.wait_for_function("!document.querySelector('#rating button[aria-checked=true]')")
    check("pressing it again clears the rating", days() == {})
    buttons.nth(0).click()
    page.wait_for_selector("#rating button[aria-checked=true]")
    buttons.nth(1).click()
    page.wait_for_function("document.querySelectorAll('#rating button')[1].getAttribute('aria-checked') === 'true'")
    check("changing rating replaces it", days()[day(0)]["rating"] == 2)
    colors = [page.evaluate("i => getComputedStyle(document.querySelectorAll('#rating .mark i')[i]).backgroundColor", i) for i in range(3)]
    heights = [page.evaluate("i => document.querySelectorAll('#rating .mark i')[i].getBoundingClientRect().height", i) for i in range(3)]
    check("marks are red, yellow, green", colors == ["rgb(165, 46, 24)", "rgb(210, 160, 32)", "rgb(46, 156, 134)"], str(colors))
    check("marks also differ by height (bad < okay < good)", heights[0] < heights[1] < heights[2], str(heights))

    # ---------- note ----------
    note = page.locator("#day-note")
    h0 = note.bounding_box()["height"]
    note.click()
    page.keyboard.type("Slept badly. <b>it's</b> \"fine\"")
    check("status says saving while typing", page.inner_text("#note-status").lower().startswith("saving"), page.inner_text("#note-status"))
    check("not saved on every keystroke", days()[day(0)]["note"] == "")
    settle()
    check("saved shortly after typing stops", days()[day(0)] == {"date": day(0), "rating": 2, "note": "Slept badly. <b>it's</b> \"fine\""}, str(days()))
    check("status says saved", page.inner_text("#note-status").lower() == "saved", page.inner_text("#note-status"))
    page.keyboard.press("Enter")
    page.keyboard.type("Second line\nThird line\nFourth line")
    check("box grows with the text", note.bounding_box()["height"] > h0 + 40, f"{h0} -> {note.bounding_box()['height']}")
    check("typing isn't interrupted by saves", note.input_value().endswith("Fourth line"))

    # leaving the day straight after typing still saves, under the right date
    page.click("#day-prev")
    page.wait_for_function("document.getElementById('day-label').innerText.toLowerCase() === 'yesterday'")
    check("half-typed note saved when leaving the day", days()[day(0)]["note"].endswith("Fourth line"), str(days()[day(0)]))
    check("yesterday starts blank", note.input_value() == "" and page.locator("#rating button[aria-checked=true]").count() == 0)
    note.click()
    page.keyboard.type("Yesterday was better")
    page.click("#day-today")
    page.wait_for_function("document.getElementById('day-label').innerText.toLowerCase() === 'today'")
    d = days()
    check("note typed on yesterday is stored on yesterday", d[day(1)] == {"date": day(1), "rating": None, "note": "Yesterday was better"} and d[day(0)]["note"].startswith("Slept badly"), str(d))
    check("today's note is back in the box", note.input_value().startswith("Slept badly") and note.input_value().endswith("Fourth line"))
    page.reload()
    page.wait_for_selector("#rating button[aria-checked=true]")
    page.wait_for_function("document.getElementById('day-note').value.length > 0")
    check("rating and note survive a reload", page.locator("#rating button[aria-checked=true]").inner_text().strip().lower() == "okay" and note.input_value().startswith("Slept badly"))
    note.click()
    page.keyboard.press("Control+a")
    page.keyboard.press("Delete")
    note.blur()
    page.wait_for_timeout(200)
    check("clearing the note keeps the rating", days()[day(0)] == {"date": day(0), "rating": 2, "note": ""}, str(days().get(day(0))))

    # ---------- task undo ----------
    row = page.locator("#task-list .task").first
    check("task starts 2 days ago", row.locator(".since b").inner_text() == "2" and row.locator("button").inner_text().lower() == "done today")
    row.locator("button").click()
    page.wait_for_function("document.querySelector('#task-list .since b').innerText === 'Today'")
    check("after Done today the button is Undo", row.locator("button").inner_text().lower() == "undo")
    t = api("GET", "/tasks")[0]
    check("done today logged", t["last_done"] == day(0) and t["log"] == [day(9), day(2), day(0)], str(t))
    page.reload()
    page.wait_for_selector("#task-list .task")
    check("Undo is still offered after a reload", row.locator("button").inner_text().lower() == "undo")
    row.locator("button").click()
    page.wait_for_function("document.querySelector('#task-list .since b').innerText === '2'")
    t = api("GET", "/tasks")[0]
    check("undo restores the previous date and log", t["last_done"] == day(2) and t["log"] == [day(9), day(2)], str(t))
    check("button is Done today again", row.locator("button").inner_text().lower() == "done today")

    # ---------- reorder ----------
    def order():
        return [n.inner_text() for n in page.locator("#habit-list .name-text").all()]
    check("move buttons hidden until editing", not page.locator("button[aria-label$=' down']").first.is_visible())
    page.click("#edit-toggle")
    items = page.locator("#habit-list li")
    check("first can't move up, last can't move down", items.nth(0).locator("button[aria-label$=' up']").is_disabled() and items.nth(2).locator("button[aria-label$=' down']").is_disabled()
          and not items.nth(0).locator("button[aria-label$=' down']").is_disabled())
    items.nth(0).locator("button[aria-label$=' down']").click()
    page.wait_for_function("document.querySelector('#habit-list .name-text').innerText === 'Run'")
    check("move down", order() == ["Run", "Read", "Stretch"], str(order()))
    items.nth(2).locator("button[aria-label$=' up']").click()
    page.wait_for_function("document.querySelectorAll('#habit-list .name-text')[1].innerText === 'Stretch'")
    items.nth(1).locator("button[aria-label$=' up']").click()
    page.wait_for_function("document.querySelector('#habit-list .name-text').innerText === 'Stretch'")
    check("move up twice", order() == ["Stretch", "Run", "Read"], str(order()))
    check("order saved on the server", [h["name"] for h in api("GET", "/habits")] == ["Stretch", "Run", "Read"])
    check("row numbers follow the new order", [n.inner_text() for n in page.locator("#habit-list .index").all()] == ["01", "02", "03"])
    page.reload()
    page.wait_for_selector("#habit-list label")
    check("order survives a reload", order() == ["Stretch", "Run", "Read"], str(order()))
    page.fill("#habit-input", "Newest")
    page.click("text=Add habit")
    page.wait_for_function("document.querySelectorAll('#habit-list label').length === 4")
    check("a new habit goes last", order() == ["Stretch", "Run", "Read", "Newest"], str(order()))

    # ---------- removing a habit, from the button beside the list ----------
    top = page.locator("#edit-habits")
    check("an Edit habits button sits right above the list", top.is_visible() and top.inner_text().lower() == "edit habits"
          and top.bounding_box()["y"] < page.locator("#habit-list").bounding_box()["y"])
    check("Delete is hidden until editing", not page.locator("#habit-list button.danger").first.is_visible())
    top.click()
    check("both edit buttons switch together", top.inner_text().lower() == "done editing" and page.inner_text("#edit-toggle").lower() == "done editing"
          and top.get_attribute("aria-pressed") == "true" and page.get_attribute("#edit-toggle", "aria-pressed") == "true")
    check("Delete is now shown on every habit", all(b.is_visible() for b in page.locator("#habit-list button.danger").all()) and page.locator("#habit-list button.danger").count() == 4)
    newest = api("GET", "/habits")[3]["id"]
    api("PUT", f"/habits/{newest}/history/{day(0)}", {"done": True})
    remove = page.locator("#habit-list li").nth(3).locator("button.danger")
    remove.click()
    remove.click()
    page.wait_for_function("document.querySelectorAll('#habit-list label').length === 3")
    check("habit removed from the list and the server", order() == ["Stretch", "Run", "Read"] and [h["name"] for h in api("GET", "/habits")] == ["Stretch", "Run", "Read"])
    page.fill("#habit-input", "Newest")
    page.click("text=Add habit")
    page.wait_for_function("document.querySelectorAll('#habit-list label').length === 4")
    check("its history went with it", api("GET", "/habits")[3]["done"] == [])
    top.click()
    check("leaving edit mode restores both labels", top.inner_text().lower() == "edit habits" and page.inner_text("#edit-toggle").lower() == "edit tasks"
          and not page.locator("#habit-list button.danger").first.is_visible())

    # ---------- Record: ratings over time ----------
    # today okay (set above), yesterday note only; then a known pattern over the last 30 days
    pattern = {2: 3, 3: 3, 4: 1, 5: 2, 6: 3, 8: 1, 12: 3, 20: 2, 29: 1}
    for back, rating in pattern.items():
        api("PUT", f"/days/{day(back)}", {"rating": rating})
    api("PUT", f"/days/{day(4)}", {"note": "Argument at work.\nWent to bed early."})
    api("PUT", f"/days/{day(12)}", {"note": "Best day in weeks"})
    api("PUT", f"/days/{day(150)}", {"rating": 3, "note": "Long ago"})
    page.goto(BASE + "/#/record")
    page.reload()
    page.wait_for_selector("#rating-calendar svg")
    page.click("#periods >> text=30D")

    def legend():
        return [" ".join(s.inner_text().split()).lower() for s in page.locator("#rating-legend > span").all()]
    # 30d: good = 2,3,6,12 -> 4 ; okay = today,5,20 -> 3 ; bad = 4,8,29 -> 3 ; unrated = 30 - 10 = 20
    check("30d legend counts", legend() == ["good 4", "okay 3", "bad 3", "not rated 20"], str(legend()))
    cal = page.locator("#rating-calendar")
    check("30d: a square per day", cal.locator(".cell").count() == 30)
    check("30d: coloured bars per rating", [cal.locator(f".fill-{n}").count() for n in (1, 2, 3)] == [3, 3, 4])
    fills = {n: page.evaluate("n => getComputedStyle(document.querySelector('#rating-calendar .fill-' + n)).fill", n) for n in (1, 2, 3)}
    check("red / yellow / green", fills == {1: "rgb(165, 46, 24)", 2: "rgb(210, 160, 32)", 3: "rgb(46, 156, 134)"}, str(fills))
    hs = {n: float(cal.locator(f".fill-{n}").first.get_attribute("height")) for n in (1, 2, 3)}
    check("bar height also encodes the rating", hs[1] < hs[2] < hs[3], str(hs))
    tips = [c.get_attribute("data-tip") for c in cal.locator(".cell").all()]
    check("tooltips name the rating", tips[-1] == "Sun 11 Oct · okay" and tips[-2] == "Sat 10 Oct · not rated" and tips[-5] == "Wed 7 Oct · bad" and tips[0] == "Sat 12 Sep · bad", f"{tips[0]} | {tips[-5]} | {tips[-2]} | {tips[-1]}")
    cal.locator(".cell").nth(27).hover()
    check("hover works on a coloured square", page.is_visible("#tip") and page.inner_text("#tip") == "Fri 9 Oct · good", page.inner_text("#tip"))

    notes = [[x for x in n.inner_text().split("\n") if x.strip()] for n in page.locator("#notes .note").all()]
    check("notes listed newest first with their rating", [n[0].lower() for n in notes] == ["sat 10 oct · not rated", "wed 7 oct · bad", "tue 29 sep · good"], str(notes))
    check("note text is shown literally with line breaks", notes[1][1:] == ["Argument at work.", "Went to bed early."] and notes[0][1] == "Yesterday was better", str(notes))
    check("no markup injected from notes", page.locator("#notes b, #notes img").count() == 0)
    page.screenshot(path="/shots/ratings-30.png", full_page=True)

    page.click("#periods >> text=7D")
    # 7d = today..6 ago: good 2,3,6 ; okay today,5 ; bad 4 ; unrated 1
    check("7d legend counts", legend() == ["good 3", "okay 2", "bad 1", "not rated 1"], str(legend()))
    check("7d notes", page.locator("#notes .note").count() == 2)
    page.click("#periods >> text=90D")
    check("90d: week grid with all rated days", cal.locator(".cell").count() == 90 and sum(cal.locator(f".fill-{n}").count() for n in (1, 2, 3)) == 10)
    page.screenshot(path="/shots/ratings-90.png", full_page=True)
    page.click("#periods >> text=All")
    check("all time reaches back to the oldest rated day", page.inner_text("#record-range") == "14 May 2026 to 11 October 2026" and legend()[0] == "good 5", f"{page.inner_text('#record-range')} {legend()}")
    check("oldest note shown under all time", page.locator("#notes .note").last.inner_text().strip().endswith("Long ago"))

    # ---------- phone, dark ----------
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(400)
    for period in ("30D", "All"):
        page.click(f"#periods >> text={period}")
        page.wait_for_timeout(100)
        sw, cw = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        check(f"phone: no sideways scroll on record {period}", sw <= cw, f"{sw} > {cw}")
    page.click("#periods >> text=30D")
    page.screenshot(path="/shots/ratings-phone.png", full_page=True)
    page.click("text=Today")
    page.wait_for_selector("#rating button")
    page.click("#edit-toggle")
    sw, cw = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    check("phone: no sideways scroll on today while editing", sw <= cw, f"{sw} > {cw}")
    page.screenshot(path="/shots/today2-phone.png", full_page=True)
    page.click("#edit-toggle")
    page.set_viewport_size({"width": 1000, "height": 1400})
    page.screenshot(path="/shots/today2-desktop.png", full_page=True)
    page.emulate_media(color_scheme="dark")
    page.click("text=Record")
    page.wait_for_selector("#rating-calendar svg")
    dark = {n: page.evaluate("n => getComputedStyle(document.querySelector('#rating-calendar .fill-' + n)).fill", n) for n in (1, 2, 3)}
    check("dark mode uses its own rating colours", dark == {1: "rgb(217, 83, 44)", 2: "rgb(201, 154, 44)", 3: "rgb(47, 159, 132)"}, str(dark))
    page.screenshot(path="/shots/ratings-dark.png", full_page=True)

    check("no script alerts, no page errors", alerts == [] and errors == [], f"{alerts} {errors}")
    browser.close()

print(f"\n{len(failures)} failed: {failures}" if failures else "\nall passed")
sys.exit(1 if failures else 0)
