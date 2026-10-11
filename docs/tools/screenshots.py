"""Take the help-site screenshots from a running demo_server.py (pip install playwright first).

    python docs/tools/screenshots.py [--out docs/img]

Set CHROMIUM=/path/to/chrome to use a browser Playwright didn't download.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "http://127.0.0.1:8765"
PHONE = {"width": 390, "height": 844}
DESK = {"width": 1280, "height": 860}


def shot(page: Page, out: Path, name: str, full: bool = False, el: str | None = None) -> None:
    page.wait_for_timeout(400)
    target = page.locator(el).first if el else page
    target.screenshot(path=str(out / f"{name}.png"), **({} if el else {"full_page": full}))
    print("wrote", name)


def wizard(page: Page, out: Path) -> None:
    page.goto(f"{BASE}/setup")
    page.fill("#name", "Maya")
    page.click("text=Done a few")
    page.fill("#weekly_hours", "5")
    shot(page, out, "setup-1-about-you")
    page.click("#next")
    page.fill("#race_date", "2026-12-13")
    page.fill("#start_date", "2026-10-05")
    page.click("text=Olympic")
    page.locator(".plan-option").filter(has_text="Olympic").first.click()
    page.fill("#goal", "finish")
    shot(page, out, "setup-2-race", full=True)
    page.click("#next")
    page.locator("[name=week_start][value='0']").check()
    for d in range(7):
        box = page.locator(f"[name=available_days][value='{d}']")
        box.set_checked(d in (1, 2, 3, 5, 6))
    page.select_option("#long_ride_day", "5")
    page.select_option("#long_run_day", "6")
    page.select_option("#brick_day", "3")
    for d in range(7):
        page.locator(f"[name=pool_days][value='{d}']").set_checked(d in (1, 3))
    shot(page, out, "setup-3-week", full=True)
    page.click("#next")
    page.wait_for_function("!document.querySelector('#preview').textContent.includes('Working it out')")
    shot(page, out, "setup-4-fit", full=True)
    page.click("#next")
    page.wait_for_timeout(800)
    page.locator("[name=look][value='bigday']").check()
    shot(page, out, "setup-5-review", full=True)
    page.click("#confirm")
    page.wait_for_url(f"{BASE}/**")
    page.wait_for_timeout(800)


def set_look(page: Page, look: str) -> None:
    page.goto(BASE)
    page.locator(f"form.looks button[value='{look}']").first.click()
    page.wait_for_load_state()


def today(page: Page, out: Path) -> None:
    for look in ("bigday", "lanes", "chat"):
        set_look(page, look)
        shot(page, out, f"today-{look}", full=True)
    set_look(page, "bigday")
    page.locator("#today button", has_text="Done, felt hard").first.click()
    page.wait_for_timeout(800)
    shot(page, out, "today-after-checkin", full=True)
    page.locator("#today button", has_text="Change my answer").first.click()
    page.wait_for_timeout(600)


def calendar(page: Page, out: Path, phone: Page) -> None:
    page.goto(f"{BASE}/calendar")
    shot(page, out, "calendar-desktop")
    page.locator("[hx-get='/ui/day/2026-10-15']:visible").first.click()
    page.wait_for_timeout(800)
    shot(page, out, "calendar-day-panel", el="#panel")
    phone.goto(f"{BASE}/calendar")
    shot(phone, out, "calendar-phone", full=True)


def garmin(page: Page, out: Path) -> None:
    page.goto(f"{BASE}/garmin")
    shot(page, out, "garmin-connect")
    page.fill("input[type=email], input[name=email]", "maya@example.com")
    page.fill("input[type=password]", "not-a-real-password")
    page.locator("form[action='/garmin/connect'] button[type=submit]").click()
    page.wait_for_load_state()
    page.locator("form[action='/garmin/send'] button").click()
    page.wait_for_load_state()
    page.wait_for_selector("#garmin-week .wk")
    shot(page, out, "garmin-sent")
    shot(page, out, "garmin-week", el="#garmin-week")
    page.locator("#garmin-week .tick").nth(0).check()
    page.locator("#garmin-week button", has_text="Delete selected").click()
    page.wait_for_timeout(800)
    shot(page, out, "garmin-delete-confirm", el="#garmin-week")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "img"))
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
        phone = browser.new_page(viewport=PHONE, device_scale_factor=2)
        desk = browser.new_page(viewport=DESK, device_scale_factor=2)
        wizard(phone, out)
        today(phone, out)
        calendar(desk, out, phone)
        garmin(phone, out)
        browser.close()


if __name__ == "__main__":
    main()
