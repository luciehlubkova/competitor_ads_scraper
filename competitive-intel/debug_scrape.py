"""
Diagnostický skript – spusť ho, nechej prohlížeč načíst stránku a
podívej se na výstup. Pomůže nám najít správné DOM selektory.

Spuštění:
    python debug_scrape.py google
    python debug_scrape.py facebook
"""
import sys
from datetime import date, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

Path("logs").mkdir(exist_ok=True)

KOOP_GOOGLE  = "https://adstransparency.google.com/?region=CZ&domain=koop.cz&preset-date=Last+7+days"
date_to   = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
date_from = (date.today() - timedelta(days=8)).strftime("%Y-%m-%d")
KOOP_FB = (
    "https://www.facebook.com/ads/library/?active_status=all&ad_type=all"
    "&content_languages[0]=cs&country=CZ&is_targeted_country=false"
    "&media_type=all&search_type=page&sort_data[direction]=desc"
    f"&sort_data[mode]=total_impressions&start_date[min]={date_from}"
    f"&start_date[max]={date_to}&view_all_page_id=221119377898604"
)

TARGET = sys.argv[1] if len(sys.argv) > 1 else "facebook"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        locale="cs-CZ",
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    page = ctx.new_page()

    url = KOOP_GOOGLE if TARGET == "google" else KOOP_FB
    print(f"\n>>> Načítám: {url}\n")
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(5_000)

    # Pro Google: extrahuj advertiser ID a naviguj na přehledovou URL
    if TARGET == "google" and "/advertiser/" not in page.url:
        import re as _re
        try:
            href = page.evaluate("""() => {
                const links = Array.from(document.querySelectorAll('a[href*="/advertiser/"]'));
                return links.length > 0 ? links[0].href : null;
            }""")
            if href:
                m = _re.search(r"/advertiser/(AR\w+)", href)
                if m:
                    aid = m.group(1)
                    overview = f"https://adstransparency.google.com/advertiser/{aid}?region=CZ&preset-date=Last+7+days"
                    print(f">>> Navigace na přehled inzerenta: {overview}")
                    page.goto(overview, wait_until="domcontentloaded")
                    page.wait_for_timeout(3_000)
                    print(f">>> Aktuální URL: {page.url}")
        except Exception as e:
            print(f">>> Chyba při navigaci: {e}")

    # Scroll jednou dolů
    page.evaluate("window.scrollBy(0, 1200)")
    page.wait_for_timeout(2_000)

    # ── Test selectorů ──────────────────────────────────────────────────
    selectors = [
        '[role="article"]',
        '[role="listitem"]',
        'article',
        'mat-card',
        '[data-testid]',
        '[data-ad-preview]',
        '[class*="creative"]',
        '[class*="adCard"]',
        '[class*="ad-card"]',
        '[class*="card"]',
        '[aria-label]',
        # Facebook specific
        '[class*="x1lliihq"]',
        '[class*="x1n2onr6"]',
        # Google specific
        '[jscontroller]',
        '[jsname]',
    ]

    print("=== POČTY PRVKŮ PODLE SELEKTORU ===")
    hits = {}
    for sel in selectors:
        try:
            n = page.locator(sel).count()
            if n > 0:
                hits[sel] = n
                print(f"  {n:4d}  {sel}")
        except Exception:
            pass

    # ── Vypiš text prvních 3 prvků u nejslibnějšího selektoru ──────────
    best = max(hits, key=lambda s: hits[s]) if hits else None
    if best:
        print(f"\n=== PRVNÍ 3 PRVKY SELEKTORU '{best}' (innerText) ===")
        cards = page.locator(best).all()[:3]
        for i, card in enumerate(cards):
            try:
                txt = card.inner_text()
                print(f"\n--- Prvek {i+1} (délka {len(txt)}) ---")
                print(txt[:600])
            except Exception as e:
                print(f"Prvek {i+1}: chyba – {e}")

    # ── Výstup hledání data (Běží od) ───────────────────────────────────
    print("\n=== PRVKY OBSAHUJÍCÍ 'Běží od' / 'Started running' ===")
    date_els = page.get_by_text(
        import_re := __import__("re").compile(r"Běží od|Started running|Spuštěno", __import__("re").I)
    ).all()
    print(f"  Nalezeno: {len(date_els)} prvků")
    for i, el in enumerate(date_els[:5]):
        try:
            print(f"  [{i+1}] tag={page.evaluate('el => el.tagName', el.element_handle())}  text={el.inner_text()[:80]!r}")
        except Exception as e:
            print(f"  [{i+1}] chyba: {e}")

    # ── Screenshot + HTML dump ──────────────────────────────────────────
    page.screenshot(path=f"logs/debug_{TARGET}_screenshot.png")
    Path(f"logs/debug_{TARGET}.html").write_text(page.content(), encoding="utf-8")
    print(f"\n>>> Screenshot: logs/debug_{TARGET}_screenshot.png")
    print(f">>> HTML dump:  logs/debug_{TARGET}.html")

    input("\n\nStiskni Enter pro zavření prohlížeče…")
    browser.close()
