"""Browser checks for colour, the light/dark toggle and phone layout. Run with tests/e2e/run.sh"""
import datetime
import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
TZ = "America/Toronto"
NOW = datetime.datetime(2026, 10, 12, 2, 30, tzinfo=datetime.timezone.utc)
TODAY = datetime.date(2026, 10, 11)
failures = []
LIGHT_BG, DARK_BG = "rgb(244, 239, 230)", "rgb(21, 19, 15)"
BLUE, BLUE_DARK = "rgb(39, 64, 111)", "rgb(163, 184, 232)"


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
    names = ["Read", "Run", "Meditate for twenty minutes before breakfast every single day"]
    for i, name in enumerate(names):
        hid = api("POST", "/habits", {"name": name, "created": day(200)})["id"]
        for back in range(0 if i < 2 else 1, 200, i + 2):
            api("PUT", f"/habits/{hid}/history/{day(back)}", {"done": True})
    t = api("POST", "/tasks", {"name": "Water mom's plants"})["id"]
    api("PATCH", f"/tasks/{t}", {"last_done": day(2)})
    t = api("POST", "/tasks", {"name": "Call the dentist about the appointment that keeps moving"})["id"]
    for back in range(0, 60):
        if back % 4:
            api("PUT", f"/days/{day(back)}", {"rating": back % 3 + 1})
    api("PUT", f"/days/{day(1)}", {"note": "A long note about the day that should wrap across several lines on a phone without pushing the page sideways."})


def bg(page):
    return page.eval_on_selector("body", "e => getComputedStyle(e).backgroundColor")


with sync_playwright() as p:
    browser = p.chromium.launch()
    seed()

    # ---------- colour + toggle (desktop, device set to light) ----------
    context = browser.new_context(timezone_id=TZ, locale="en-US", viewport={"width": 1000, "height": 1400}, color_scheme="light")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.clock.install(time=NOW)
    page.goto(BASE)
    page.wait_for_selector("#habit-list label")

    css = lambda sel, prop: page.eval_on_selector(sel, f"e => getComputedStyle(e).{prop}")
    check("follows the device by default (light)", bg(page) == LIGHT_BG and page.get_attribute("html", "data-theme") is None)
    check("toggle offers Dark", page.inner_text("#theme-toggle").strip().lower() == "dark" and page.get_attribute("#theme-toggle", "aria-label") == "Switch to dark mode")
    check("done tick is blue", css("#habit-list .habit.done .tick", "backgroundColor") == BLUE, css("#habit-list .habit.done .tick", "backgroundColor"))
    check("weekday in the headline is blue", css("#day-title em", "color") == BLUE)
    check("section headings are blue", css(".section-head h2", "color") == BLUE)
    check("progress line is blue", css("#progress-bar", "backgroundColor") == BLUE)
    check("body text stays ink", css("#habit-list .habit:not(.done) .name-text", "color") == "rgb(26, 24, 20)")
    page.screenshot(path="/shots/colour-today-light.png", full_page=True)

    page.click("#theme-toggle")
    check("toggle switches to dark", bg(page) == DARK_BG and page.get_attribute("html", "data-theme") == "dark")
    check("toggle now offers Light", page.inner_text("#theme-toggle").strip().lower() == "light")
    check("browser bar colour follows", page.get_attribute("meta[name=theme-color]", "content") == "#15130f")
    page.wait_for_timeout(400)
    check("blue has its dark-mode value", css("#habit-list .habit.done .tick", "backgroundColor") == BLUE_DARK, css("#habit-list .habit.done .tick", "backgroundColor"))
    check("text on a blue tick is still readable (dark check on light blue)", css("#habit-list .habit.done .tick svg", "stroke") == DARK_BG)
    page.screenshot(path="/shots/colour-today-dark.png", full_page=True)

    # the choice must be applied before first paint on the next load
    page.add_init_script("document.addEventListener('DOMContentLoaded', () => { window.__themeAtParse = document.documentElement.dataset.theme || null; })")
    page.reload()
    page.wait_for_selector("#habit-list label")
    check("choice survives a reload", bg(page) == DARK_BG and page.inner_text("#theme-toggle").strip().lower() == "light")
    check("applied before the page paints (no flash)", page.evaluate("window.__themeAtParse") == "dark")
    page.click("text=Record")
    page.wait_for_selector("#entries .entry")
    check("charts recolour with the theme", css("#chart .bar", "fill") == BLUE_DARK and css("#entries .cell.on", "fill") == BLUE_DARK)
    page.screenshot(path="/shots/colour-record-dark.png", full_page=True)
    page.click("#theme-toggle")
    check("toggle back to light on the record page", bg(page) == LIGHT_BG and css("#chart .bar", "fill") == BLUE and css("#periods button[aria-pressed=true]", "backgroundColor") == BLUE)
    page.screenshot(path="/shots/colour-record-light.png", full_page=True)

    # pinned light must beat a device that asks for dark, and vice versa
    page.emulate_media(color_scheme="dark")
    check("pinned light wins over a dark device", bg(page) == LIGHT_BG)
    page.click("#theme-toggle")
    page.emulate_media(color_scheme="light")
    check("pinned dark wins over a light device", bg(page) == DARK_BG)
    context.close()

    # no saved choice + dark device
    context = browser.new_context(timezone_id=TZ, locale="en-US", viewport={"width": 1000, "height": 900}, color_scheme="dark")
    page = context.new_page()
    page.goto(BASE)
    page.wait_for_selector("#habit-list label")
    check("with no choice saved, a dark device gets dark", bg(page) == DARK_BG and page.inner_text("#theme-toggle").strip().lower() == "light")
    page.emulate_media(color_scheme="light")
    page.wait_for_timeout(100)
    check("and follows the device when it changes", bg(page) == LIGHT_BG and page.inner_text("#theme-toggle").strip().lower() == "dark")
    context.close()

    # ---------- phones ----------
    for width, height in ((320, 568), (360, 740), (390, 844), (430, 932)):
        context = browser.new_context(timezone_id=TZ, locale="en-US", viewport={"width": width, "height": height},
                                      device_scale_factor=2, is_mobile=True, has_touch=True, color_scheme="light")
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.clock.install(time=NOW)
        page.goto(BASE)
        page.wait_for_selector("#habit-list label")
        page.wait_for_selector("#rating button")

        def overflow():
            return page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")

        def offscreen():
            # visible elements whose box sticks out past the right edge (ignoring scrollable calendars)
            return page.evaluate("""() => [...document.querySelectorAll('.page *')].filter(e => {
                if (e.closest('.calendar') || e.closest('svg')) return false;
                const r = e.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && (r.right > window.innerWidth + 0.5 || r.left < -0.5);
            }).map(e => e.tagName + '.' + e.className).slice(0, 5)""")

        def small_targets():
            return page.evaluate("""() => [...document.querySelectorAll('button, .masthead a, .habit')].filter(e => {
                const r = e.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && !e.disabled && r.height < 40;
            }).map(e => (e.id || e.className || e.textContent.trim()) + ':' + Math.round(e.getBoundingClientRect().height)).slice(0, 8)""")

        check(f"{width}px today: no sideways scroll", overflow() <= 0, str(overflow()))
        check(f"{width}px today: nothing off screen", offscreen() == [], str(offscreen()))
        check(f"{width}px today: touch targets at least 40px", small_targets() == [], str(small_targets()))
        mast = page.locator(".masthead").bounding_box()
        check(f"{width}px: masthead stays on one line", mast["height"] < 60, str(mast["height"]))
        gap = page.evaluate("document.querySelector('.masthead nav').getBoundingClientRect().left - document.querySelector('.masthead > span').getBoundingClientRect().right")
        check(f"{width}px: masthead name and links don't touch", gap >= 10, str(gap))
        page.screenshot(path=f"/shots/phone-{width}-today.png", full_page=True)

        # tapping works with touch
        first = page.locator("#habit-list label.habit").nth(1)
        was = first.locator("input").is_checked()
        first.locator(".tick").tap()
        page.wait_for_timeout(250)
        check(f"{width}px: tapping a tick toggles it", first.locator("input").is_checked() != was)
        first.locator(".tick").tap()
        page.wait_for_timeout(250)

        page.locator("#edit-toggle").tap()
        check(f"{width}px editing: no sideways scroll", overflow() <= 0, str(overflow()))
        check(f"{width}px editing: nothing off screen", offscreen() == [], str(offscreen()))
        check(f"{width}px editing: touch targets at least 40px", small_targets() == [], str(small_targets()))
        if width == 320:
            page.screenshot(path="/shots/phone-320-editing.png", full_page=True)
        page.locator("#edit-toggle").tap()

        page.locator(".masthead a[data-view=record]").tap()
        page.wait_for_selector("#entries .entry")
        for period in ("7D", "30D", "90D", "1Y", "All"):
            page.locator(f"#periods >> text={period}").tap()
            page.wait_for_timeout(120)
            check(f"{width}px record {period}: no sideways scroll", overflow() <= 0, str(overflow()))
            check(f"{width}px record {period}: nothing off screen", offscreen() == [], str(offscreen()))
        check(f"{width}px record: touch targets at least 40px", small_targets() == [], str(small_targets()))
        scrolled = page.evaluate("(() => { const c = document.querySelector('#entries .calendar'); return [c.scrollWidth > c.clientWidth, Math.abs(c.scrollLeft + c.clientWidth - c.scrollWidth) < 2]; })()")
        check(f"{width}px record: calendars sit at their newest end", scrolled[1], str(scrolled))
        page.locator("#periods >> text=90D").tap()
        page.wait_for_timeout(120)
        page.screenshot(path=f"/shots/phone-{width}-record.png", full_page=True)
        page.locator("#theme-toggle").tap()
        check(f"{width}px: theme toggle works by touch", bg(page) == DARK_BG)
        if width == 390:
            page.screenshot(path="/shots/phone-390-record-dark.png", full_page=True)
        context.close()

    check("no page errors", errors == [], str(errors))
    browser.close()

print(f"\n{len(failures)} failed: {failures}" if failures else "\nall passed")
sys.exit(1 if failures else 0)
