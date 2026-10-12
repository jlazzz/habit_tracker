"""Browser checks for the Today / Record redesign. Run with tests/e2e/run.sh"""
import datetime
import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
TZ = "America/Toronto"
# 22:30 local on Sun Oct 11 == 02:30 UTC Oct 12
NOW = datetime.datetime(2026, 10, 12, 2, 30, tzinfo=datetime.timezone.utc)
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


def seed():
    """Three habits with known shapes so the expected numbers can be worked out by hand."""
    # Read: started 100 days ago, done every day of the last 30 except 5 and 6 days ago, nothing before
    read = api("POST", "/habits", {"name": "Read", "created": day(99)})["id"]
    for back in range(30):
        if back not in (5, 6):
            api("PUT", f"/habits/{read}/history/{day(back)}", {"done": True})
    # Run: started 100 days ago, done on every Monday-of-week pattern: every 7th day back from yesterday,
    # plus a solid block 40..59 days ago
    run = api("POST", "/habits", {"name": "Run", "created": day(99)})["id"]
    for back in list(range(1, 30, 7)) + list(range(40, 60)):
        api("PUT", f"/habits/{run}/history/{day(back)}", {"done": True})
    # Stretch: started 10 days ago, done on the last 3 days before today
    stretch = api("POST", "/habits", {"name": "Stretch", "created": day(9)})["id"]
    for back in (1, 2, 3):
        api("PUT", f"/habits/{stretch}/history/{day(back)}", {"done": True})
    t = api("POST", "/tasks", {"name": "Water mom's plants"})["id"]
    for back in (30, 20, 10, 2):
        api("PATCH", f"/tasks/{t}", {"last_done": day(back)})
    api("POST", "/tasks", {"name": '<img src=x onerror="alert(1)">'})
    return read, run, stretch


with sync_playwright() as p:
    browser = p.chromium.launch()
    read, run, stretch = seed()

    context = browser.new_context(timezone_id=TZ, locale="en-US", viewport={"width": 1000, "height": 1300})
    page = context.new_page()
    external, errors, alerts = [], [], []
    page.on("request", lambda r: external.append(r.url) if not r.url.startswith(BASE) else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "409" not in m.text else None)
    page.on("dialog", lambda d: (alerts.append(d.message), d.dismiss()))
    page.clock.install(time=NOW)
    page.goto(BASE)
    page.wait_for_selector("#habit-list label")
    page.evaluate("document.fonts.ready")

    # ---------- Today ----------
    check("no outside requests", external == [], str(external))
    check("local fonts loaded", page.evaluate("document.fonts.check('20px Fraunces') && document.fonts.check('11px \"IBM Plex Mono\"')"))
    check("today view is the landing page", page.is_visible("#view-today") and not page.is_visible("#view-record"))
    check("headline is the local day", page.inner_text("#day-title").split() == ["Sunday,", "11", "October"], page.inner_text("#day-title"))
    check("label says Today", page.inner_text("#day-label").lower() == "today")
    rows = page.locator("#habit-list label.habit")
    check("three habits listed", rows.count() == 3)
    check("tally 1 of 3", page.get_attribute("#tally", "aria-label") == "1 of 3 habits done", page.get_attribute("#tally", "aria-label"))
    check("Read is ticked, others not", [rows.nth(i).locator("input").is_checked() for i in range(3)] == [True, False, False])
    check("streak caption", rows.nth(0).locator(".label").inner_text().lower() == "streak 5 days · best 23", rows.nth(0).locator(".label").inner_text())
    check("next-day disabled on today", page.is_disabled("#day-next") and not page.is_visible("#day-today"))

    # tick by clicking the row itself
    rows.nth(1).locator(".name").click()
    page.wait_for_function("document.querySelector('#tally .count').innerText === '2\'")
    check("clicking the row ticks it for the local date", day(0) in api("GET", "/habits")[1]["done"])
    check("row marked done + streak updates", "done" in rows.nth(1).get_attribute("class")
          and rows.nth(1).locator(".label").inner_text().lower() == "streak 2 days · best 20", rows.nth(1).locator(".label").inner_text())
    rows.nth(2).locator(".tick").click()
    page.wait_for_function("document.getElementById('tally').className.includes('complete')")
    check("all done -> tally 3 of 3", page.get_attribute("#tally", "aria-label") == "3 of 3 habits done")
    check("progress bar full", page.eval_on_selector("#progress-bar", "e => e.style.width") == "100%")
    page.screenshot(path="/shots/today-desktop.png", full_page=True)
    rows.nth(2).locator(".tick").click()
    rows.nth(1).locator(".tick").click()
    page.wait_for_function("document.querySelector('#tally .count').innerText === '1\'")
    page.wait_for_timeout(300)
    h = api("GET", "/habits")
    check("unticking removes today", day(0) not in h[1]["done"] and day(0) not in h[2]["done"])

    # keyboard
    rows.nth(1).locator("input").focus()
    page.keyboard.press("Space")
    page.wait_for_function("document.querySelector('#tally .count').innerText === '2\'")
    page.keyboard.press("Space")
    page.wait_for_function("document.querySelector('#tally .count').innerText === '1\'")
    check("space bar toggles a focused habit", True)

    # past days
    page.click("#day-prev")
    check("yesterday view", page.inner_text("#day-label").lower() == "yesterday" and page.inner_text("#day-title").split() == ["Saturday,", "10", "October"])
    check("yesterday's ticks", [rows.nth(i).locator("input").is_checked() for i in range(3)] == [True, True, True])
    for _ in range(4):
        page.click("#day-prev")
    check("5 days ago view", page.inner_text("#day-label").lower() == "5 days ago" and page.get_attribute("#tally", "aria-label") == "0 of 3 habits done", page.get_attribute("#tally", "aria-label"))
    rows.nth(0).locator(".tick").click()
    page.wait_for_function("document.querySelector('#tally .count').innerText === '1\'")
    page.wait_for_timeout(200)
    check("back-filling a past day stores that date", day(5) in api("GET", "/habits")[0]["done"])
    rows.nth(0).locator(".tick").click()
    page.wait_for_timeout(300)
    check("and can be undone", day(5) not in api("GET", "/habits")[0]["done"])
    page.click("#day-today")
    check("return to today", page.inner_text("#day-label").lower() == "today" and page.is_disabled("#day-next"))

    # tasks
    tasks = page.locator("#task-list .task")
    check("task shows days since", tasks.nth(0).locator(".since b").inner_text() == "2" and tasks.nth(0).locator(".since .label").inner_text().lower() == "days ago")
    check("never-done task", tasks.nth(1).locator(".since").inner_text() == "Never")
    check("HTML in names is literal text", tasks.nth(1).locator(".name").inner_text() == '<img src=x onerror="alert(1)">' and page.locator("#task-list img").count() == 0)
    tasks.nth(1).locator("text=Done today").click()
    page.wait_for_function("document.querySelectorAll('#task-list .task')[1].querySelector('.since').innerText === 'Today'")
    t = api("GET", "/tasks")
    check("done-today logs the local date", t[1]["last_done"] == day(0) and t[1]["log"] == [day(0)], str(t[1]))

    # edit mode: rename + delete + add
    check("row actions hidden until editing", not page.locator("#habit-list .actions").first.is_visible())
    page.click("#edit-toggle")
    check("row actions shown when editing", page.locator("#habit-list .actions").first.is_visible())
    page.locator("#habit-list li").nth(2).locator("text=Rename").click()
    page.keyboard.type("Stretching")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelectorAll('#habit-list .name')[2].innerText === 'Stretching'")
    h = api("GET", "/habits")[2]
    check("rename keeps id, history and ticks nothing", h["id"] == stretch and h["name"] == "Stretching" and h["done"] == [day(3), day(2), day(1)], str(h))
    page.fill("#habit-input", "Stretching")
    page.click("text=Add habit")
    page.wait_for_selector("#error:not([hidden])")
    check("duplicate shows an error", page.inner_text("#error") == "Habit already exists")
    page.fill("#habit-input", "Temp")
    page.click("text=Add habit")
    page.wait_for_function("document.querySelectorAll('#habit-list label').length === 4")
    check("new habit starts today (local)", api("GET", "/habits")[3]["created"] == day(0), str(api("GET", "/habits")[3]))
    delete = page.locator("#habit-list li").nth(3).locator("button.danger")
    delete.click()
    check("delete needs a second click", len(api("GET", "/habits")) == 4 and delete.inner_text().lower() == "click again to delete")
    delete.click()
    page.wait_for_function("document.querySelectorAll('#habit-list label').length === 3")
    check("deleted on confirm", len(api("GET", "/habits")) == 3)
    page.click("#edit-toggle")

    # ---------- Record ----------
    page.click("text=Record")
    page.wait_for_selector("#entries .entry")
    check("record view shown", page.is_visible("#view-record") and not page.is_visible("#view-today"))
    check("defaults to 30 days", page.inner_text("#record-title") == "Last 30 days" and page.inner_text("#record-range") == "12 September 2026 to 11 October 2026", page.inner_text("#record-range"))

    def figures():
        return [[x for x in f.inner_text().split("\n") if x.strip()] for f in page.locator(".figure").all()]

    def entries():
        out = []
        for e in page.locator(".entry").all():
            out.append((e.locator(".name").inner_text(), " ".join(e.locator(".rate").evaluate("n => [...n.childNodes].map(c => c.textContent)")), e.locator("p.label").inner_text().lower()))
        return out

    # 30d by hand: Read 28/30, Run 5/30 (1,8,15,22,29 days ago), Stretching 3/10 -> 36/70 = 51%
    # previous 30d (30..59 ago): Read 0/30, Run 20/30, Stretching not started -> 20/60 = 33% -> +18
    f = figures()
    check("30d completion", f[0][1] == "51%" and "▲ 18 pts" in f[0][2], str(f[0]))
    check("30d check-offs", f[1][1] == "36" and f[1][2] == "of 70 possible", str(f[1]))
    # perfect days: days where all active done: 1,2,3 days ago all three; 8,15,22,29 ago (before Stretching started at 9 ago? 8 ago is after) ->
    # 8 ago: Stretching active, not done -> no. 15, 22, 29 ago: Read+Run only, both done -> yes. Total 6.
    check("30d perfect days", f[2][1] == "4" and f[2][2] == "of 30 days", str(f[2]))
    e = entries()
    check("default sort is rate, highest first", [x[0] for x in e] == ["Read", "Stretching", "Run"], str(e))
    check("Read entry numbers", e[0][1] == "93% ▲ 93 pts" and e[0][2] == "28 of 30 days · streak 5 · best 23", str(e[0]))
    check("Stretching counts only since it started", e[1][1] == "30%" and e[1][2] == "3 of 10 days · streak 3 · best 3", str(e[1]))
    check("Run entry numbers", e[2][1] == "17% ▼ 50 pts" and e[2][2] == "5 of 30 days · streak 1 · best 20", str(e[2]))

    # sorting
    def order():
        return [x.inner_text() for x in page.locator(".entry .name").all()]
    page.click("#sorts >> text=Rate")
    check("clicking again reverses", order() == ["Run", "Stretching", "Read"], str(order()))
    page.click("#sorts >> text=Name")
    check("sort by name A-Z", order() == ["Read", "Run", "Stretching"], str(order()))
    page.click("#sorts >> text=Best")
    check("sort by best streak", order() == ["Read", "Run", "Stretching"], str(order()))
    page.click("#sorts >> text=Streak")
    check("sort by current streak", order() == ["Read", "Stretching", "Run"], str(order()))
    page.click("#sorts >> text=Change")
    check("sort by change, no-data last", order() == ["Read", "Run", "Stretching"], str(order()))
    page.click("#sorts >> text=Change")
    check("reversed change still keeps no-data last", order() == ["Run", "Read", "Stretching"], str(order()))
    check("active sort is marked", page.locator("#sorts button[aria-pressed=true]").inner_text().lower() == "change ↑")

    # chart 30d
    check("30 daily bars slots", page.locator("#chart .hit").count() == 30)
    tips = [h.get_attribute("data-tip") for h in page.locator("#chart .hit").all()]
    check("chart values", tips[-1] == "Sun 11 Oct · 1 of 3 (33%)" and tips[-2] == "Sat 10 Oct · 3 of 3 (100%)" and tips[0] == "Sat 12 Sep · 2 of 2 (100%)", f"{tips[0]} | {tips[-2]} | {tips[-1]}")
    page.locator("#chart .hit").nth(28).hover()
    check("hover shows tooltip", page.is_visible("#tip") and page.inner_text("#tip") == "Sat 10 Oct · 3 of 3 (100%)", page.inner_text("#tip"))
    page.screenshot(path="/shots/record-30-desktop.png", full_page=True)

    # weekday: Run's pattern lands on one weekday (1 day ago = Saturday)
    wd = {w.locator(".label").inner_text().lower(): w.get_attribute("data-tip") for w in page.locator(".weekday").all()}
    check("weekday breakdown has 7 rows", list(wd) == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], str(list(wd)))
    check("best weekday is Saturday", figures()[3][1] == "Sat", str(figures()[3]))

    # calendars 30d: strip of 30 cells for Read, 10 for Stretching
    cal = page.locator(".entry[data-habit='Read'] .cell")
    check("30d calendar: a square per counted day", cal.count() == 30 and page.locator(".entry[data-habit='Stretching'] .cell").count() == 10)
    check("30d calendar: done squares", page.locator(".entry[data-habit='Read'] .cell.on").count() == 28)

    # 7 days: Read 5/7 (5,6 ago missed), Run 1/7, Stretching 3/7 -> 9/21 = 43%
    page.click("#periods >> text=7D")
    f = figures()
    check("7d numbers", page.inner_text("#record-title") == "Last 7 days" and f[0][1] == "43%" and f[1][1] == "9" and f[1][2] == "of 21 possible", str(f[:2]))
    check("7d chart has 7 bars", page.locator("#chart .hit").count() == 7)
    page.screenshot(path="/shots/record-7-desktop.png", full_page=True)

    # 90 days: Read 28/90, Run 25/90, Stretching 3/10 -> 56/190 = 29%
    page.click("#periods >> text=90D")
    f = figures()
    check("90d numbers", f[0][1] == "29%" and f[1][1] == "56" and f[1][2] == "of 190 possible", str(f[:2]))
    check("90d chart is daily", page.locator("#chart .hit").count() == 90 and "per day" in page.inner_text("#chart-unit").lower())
    check("90d calendar is a week grid", page.locator(".entry[data-habit='Read'] .cell").count() == 90)
    page.screenshot(path="/shots/record-90-desktop.png", full_page=True)

    # 1 year: habits only exist for 100 days: Read 28/100, Run 25/100, Stretching 3/10 -> 56/210 = 27%
    page.click("#periods >> text=1Y")
    f = figures()
    check("1y numbers count only days since each habit started", f[0][1] == "27%" and f[1][2] == "of 210 possible" and f[2][2] == "of 100 days", str(f[:3]))
    check("1y chart is weekly", "per week" in page.inner_text("#chart-unit").lower() and 52 <= page.locator("#chart .hit").count() <= 54, str(page.locator("#chart .hit").count()))
    last = page.locator("#chart .hit").last.get_attribute("data-tip")
    check("weekly bucket tooltip", last == "Mon 5 Oct – Sun 11 Oct · 9 of 21 (43%)", last)
    check("1y calendar only draws counted days", page.locator(".entry[data-habit='Read'] .cell").count() == 100)
    page.screenshot(path="/shots/record-1y-desktop.png", full_page=True)

    # all time
    page.click("#periods >> text=All")
    f = figures()
    check("all-time numbers", page.inner_text("#record-range") == "4 July 2026 to 11 October 2026" and f[0][1] == "27%" and f[0][2] == "nothing earlier to compare", f"{page.inner_text('#record-range')} {f[0]}")

    # logs
    logs = [[x for x in l.inner_text().split("\n") if x.strip()] for l in page.locator("#logs .log").all()]
    check("task log: count, last, interval", logs[0][0] == "Water mom's plants" and logs[0][1].lower() == "done 4 times"
          and logs[0][2] == "Last on Fri 9 Oct, 2 days ago · about every 9 days", str(logs[0]))

    # settings persist
    page.click("#periods >> text=90D")
    page.reload()
    page.wait_for_selector("#entries .entry")
    check("period, sort and view survive a reload", page.inner_text("#record-title") == "Last 90 days"
          and page.locator("#sorts button[aria-pressed=true]").inner_text().lower() == "change ↑" and page.is_visible("#view-record"))

    # ---------- phone + dark ----------
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(400)
    for period in ("7D", "30D", "90D", "1Y"):
        page.click(f"#periods >> text={period}")
        page.wait_for_timeout(100)
        sw, cw = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        check(f"phone: no sideways scroll on record {period}", sw <= cw, f"{sw} > {cw}")
    page.screenshot(path="/shots/record-1y-phone.png", full_page=True)
    page.click("text=Today")
    page.wait_for_selector("#habit-list label")
    sw, cw = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    check("phone: no sideways scroll on today", sw <= cw, f"{sw} > {cw}")
    box = page.locator("#habit-list .tick").first.bounding_box()
    check("phone: tick target is at least 44px", box["width"] >= 44 and box["height"] >= 44, str(box))
    page.screenshot(path="/shots/today-phone.png", full_page=True)

    page.emulate_media(color_scheme="dark")
    page.set_viewport_size({"width": 1000, "height": 1300})
    check("dark mode swaps the ground", page.eval_on_selector("body", "e => getComputedStyle(e).backgroundColor") == "rgb(21, 19, 15)")
    page.screenshot(path="/shots/today-dark.png", full_page=True)
    page.click("text=Record")
    page.click("#periods >> text=90D")
    page.wait_for_timeout(200)
    page.screenshot(path="/shots/record-90-dark.png", full_page=True)
    page.emulate_media(color_scheme="light")

    # overnight rollover on Today
    page.click("text=Today")
    page.clock.run_for(2 * 60 * 60 * 1000)
    page.wait_for_function("document.getElementById('day-title').innerText.includes('Monday')")
    check("page left open moves to the new day", page.inner_text("#day-label").lower() == "today" and page.get_attribute("#tally", "aria-label") == "0 of 3 habits done", page.get_attribute("#tally", "aria-label"))

    check("no script alerts, no page errors", alerts == [] and errors == [], f"{alerts} {errors}")
    browser.close()

print(f"\n{len(failures)} failed: {failures}" if failures else "\nall passed")
sys.exit(1 if failures else 0)
