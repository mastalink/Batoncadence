"""Foreground browser acceptance and sanitized captures for redesign slice 4 (Ask for something).

Requires the optional playwright package and installed Chromium. No gateway is
started: the two /api/ask routes are answered in the browser by the real planner
(mco.ask_plan), so the shipped bundle's clicks and fetches are what is tested.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mco import ask_plan  # noqa: E402

OUT = ROOT / "design/redesign-v1/evidence-s4"
REQUEST = "Research open PRs, run tests, if green draft release notes and ask me to publish."


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    requests = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for name, viewport, theme in [("desktop-light", {"width": 1280, "height": 900}, "light"),
                                          ("phone-dark", {"width": 390, "height": 844}, "dark")]:
                context = browser.new_context(viewport=viewport, color_scheme=theme, reduced_motion="reduce")
                try:
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.add_init_script("localStorage.setItem('bitcadence_page','ask'); localStorage.setItem('bitcadence_conn',JSON.stringify({url:'http://fixture.test',token:'fixture'}));")

                    def intercept(route):
                        request = route.request
                        path = urlsplit(request.url).path
                        requests.append((request.method, path, request.post_data))
                        body = json.loads(request.post_data) if request.post_data else {}
                        if path == "/api/ask/plan":
                            plan = ask_plan.apply_tweaks(
                                ask_plan.draft_plan(body["request"], body.get("role") or "claude"),
                                remove=body.get("remove"), ask_end=body.get("ask_at_end"), repeat=body.get("repeat") or "")
                            data = {"plan": plan}
                        elif path == "/api/ask/start":
                            plan = ask_plan.apply_tweaks(
                                ask_plan.draft_plan(body["request"], body.get("role") or "claude"),
                                remove=body.get("remove"), ask_end=body.get("ask_at_end"), repeat=body.get("repeat") or "")
                            data = {"success": True, "run": "fixture", "jobs": {}, "repeat": (plan["repeat"] or {}).get("words")}
                        else:
                            data = []
                        route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

                    page.route("http://fixture.test/**", intercept)
                    page.goto((ROOT / "src/mco/static/console.html").as_uri())
                    page.get_by_role("heading", name="Ask for something", exact=True).first.wait_for()
                    page.get_by_label("What should happen?").wait_for()
                    page.get_by_text("Connected. Your helpers are ready.", exact=True).wait_for(state="hidden", timeout=10000)
                    assert page.get_by_role("button", name="Draft a plan").is_disabled()
                    page.get_by_label("What should happen?").fill(REQUEST)
                    page.screenshot(path=str(OUT / f"ask-write-{name}.png"), full_page=True)
                    page.get_by_role("button", name="Draft a plan").click()
                    page.get_by_role("heading", name="Here's the plan").wait_for()
                    items = page.get_by_role("listitem")
                    assert items.count() == 4, items.count()
                    plan_text = page.locator(".ask-view").inner_text()
                    assert "If everything passes" in plan_text and "Ask you before publishing" in plan_text
                    for needle in ("{", "}", "YAML", "depends_on", "step-1", "mco_tok_"):
                        assert needle not in plan_text, needle
                    for label in ("Remove a step", "Always ask me at the end", "Make it repeat", "Approve and start"):
                        assert page.get_by_role("button", name=label).bounding_box()["height"] >= 48, label

                    page.get_by_role("button", name="Remove a step").click()
                    page.get_by_role("button", name="Remove this step: Run tests").click()
                    page.get_by_role("button", name="Approve and start").wait_for()  # back from "Working..."
                    assert page.get_by_role("listitem").count() == 3, page.locator(".ask-view").inner_text()
                    page.get_by_role("button", name="Always ask me at the end").click()
                    page.get_by_role("button", name="Asking you at the end: on").wait_for()
                    page.get_by_role("button", name="Make it repeat").click()
                    page.get_by_role("button", name="Every Friday at 9 AM", exact=True).click()
                    page.get_by_text("Repeats: Every Friday at 9:00 AM").first.wait_for()
                    # The page itself must fit the screen (the app shell's own header is not part of this slice).
                    assert page.locator(".ask-view").evaluate(
                        "(e) => [...e.querySelectorAll('*')].every(c => c.getBoundingClientRect().right <= window.innerWidth + 1)"), page.locator(".ask-view").evaluate(
                        "(e) => [...e.querySelectorAll('*')].filter(c => c.getBoundingClientRect().right > window.innerWidth + 1).map(c => c.tagName + ' ' + Math.round(c.getBoundingClientRect().right) + ' ' + c.textContent.slice(0, 30))")
                    page.screenshot(path=str(OUT / f"ask-plan-{name}.png"), full_page=True)
                    (OUT / f"ask-plan-{name}.txt").write_text(page.locator(".ask-view").inner_text(), encoding="utf-8")

                    page.get_by_role("button", name="Approve and start").click()
                    page.get_by_role("heading", name="Approved. Starting now.").wait_for()
                    done = page.locator(".ask-view").inner_text()
                    assert "It will also repeat: Every Friday at 9:00 AM." in done
                    page.screenshot(path=str(OUT / f"ask-approved-{name}.png"), full_page=True)
                    (OUT / f"ask-approved-{name}.txt").write_text(done, encoding="utf-8")
                    start = [json.loads(body) for method, path, body in requests if path == "/api/ask/start"][-1]
                    assert start["remove"] == ["step-2"] and start["ask_at_end"] is True
                    assert start["repeat"] == "every Friday at 9 AM" and start["request"] == REQUEST
                    assert not errors, errors
                    page.get_by_role("button", name="Ask for something else").click()
                    page.get_by_label("What should happen?").wait_for()
                    print(f"{name}: production Ask -> plan -> approve; remove, ask-me, repeat, tap targets and plain words passed")
                finally:
                    context.close()
        finally:
            browser.close()
    assert not any("/flow" in path for _, path, _ in requests)


if __name__ == "__main__":
    main()
