#!/usr/bin/env python3
import argparse
import logging
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

from scrapers.google_scraper import GoogleScraper
from scrapers.facebook_scraper import FacebookScraper
from processing.filter import AdFilter
from processing.deduplicator import deduplicate
from processing.diff import DiffEngine
from reporter import ReportGenerator

ROOT = Path(__file__).parent
REPORTS_DIR = ROOT / "reports"
SNAPSHOT_DIR = ROOT / "storage" / "snapshots"
OCR_CACHE_PATH = ROOT / "storage" / "ocr_cache.json"
LOGS_DIR = ROOT / "logs"


def setup_logging(run_date: date):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    # Windows consoles default to cp1250, which raises UnicodeEncodeError on the
    # box-drawing / arrow / emoji characters we log. Switch stdout to UTF-8 and
    # never let an unencodable glyph break a log line.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    log_file = LOGS_DIR / f"run_{run_date.isoformat()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_config() -> tuple[list, dict]:
    cfg_dir = ROOT / "config"
    with open(cfg_dir / "competitors.yaml", encoding="utf-8") as f:
        competitors = yaml.safe_load(f)["competitors"]
    with open(cfg_dir / "exclude_keywords.yaml", encoding="utf-8") as f:
        keywords = yaml.safe_load(f)
    return competitors, keywords


def cleanup_old_snapshots(logger: logging.Logger):
    cutoff = date.today() - timedelta(days=90)
    for f in SNAPSHOT_DIR.glob("*.json"):
        parts = f.stem.rsplit("_", 1)
        if len(parts) == 2:
            try:
                if date.fromisoformat(parts[1]) < cutoff:
                    f.unlink()
                    logger.info(f"Smazán starý snapshot: {f.name}")
            except ValueError:
                pass


def _check_tesseract(logger: logging.Logger):
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        logger.info("Tesseract OCR dostupný – Google kreativy budou čteny přes OCR.")
    except Exception:
        logger.warning(
            "Tesseract OCR není dostupný! Google banner reklamy nebudou mít text. "
            "Nainstalujte Tesseract: https://github.com/UB-Mannheim/tesseract/wiki"
        )


def main():
    parser = argparse.ArgumentParser(description="Competitive Intelligence Scraper")
    parser.add_argument("--competitor", help="Slug konkurenta pro single-run test")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape bez uložení snapshotu",
    )
    args = parser.parse_args()

    today = date.today()
    setup_logging(today)
    logger = logging.getLogger("main")
    _check_tesseract(logger)

    REPORTS_DIR.mkdir(exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    cleanup_old_snapshots(logger)

    competitors, keywords_config = load_config()

    if args.competitor:
        competitors = [c for c in competitors if c["slug"] == args.competitor]
        if not competitors:
            logger.error(f"Konkurent '{args.competitor}' nenalezen v config/competitors.yaml")
            sys.exit(1)

    ad_filter = AdFilter(keywords_config)
    diff_engine = DiffEngine(SNAPSHOT_DIR)

    results: dict = {}
    errors: list[str] = []
    google_warnings: list[str] = []
    total_skipped = 0
    total_ocr_tried = 0
    total_ocr_success = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="cs-CZ",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        # Google má dvě oddělené fáze s vlastními rozpočty:
        #   max_scroll_seconds = jen objevení kreativ (scroll, bez OCR) – rychlé
        #   max_ocr_seconds    = čtení textu z kreativ (Tesseract) – škáluje s počtem
        # Worst case Google ≈ 240 + 600 s; Facebook nemá OCR, takže čistý scroll.
        google_scraper = GoogleScraper(
            page,
            max_scroll_seconds=240,
            max_ocr_seconds=600,
            ocr_cache_path=OCR_CACHE_PATH,
        )
        facebook_scraper = FacebookScraper(page, max_scroll_seconds=360)

        # Per-fázové měření času – součet přes všechny konkurenty (viz [čas] logy).
        time_totals = {"google": 0.0, "facebook": 0.0, "diff": 0.0}

        for idx, competitor in enumerate(competitors):
            slug = competitor["slug"]
            comp_start = time.time()
            logger.info(f"─── {slug} ({idx + 1}/{len(competitors)}) ───")

            comp_result = {
                "competitor": competitor,
                "google": {"ads": [], "error": None, "warning": None},
                "facebook": {"ads": [], "error": None},
                "diff": None,
                "influencer_notes": [],
            }

            # ── Google ──────────────────────────────────────────────────
            t_google = time.perf_counter()
            try:
                g = google_scraper.scrape(
                    competitor["google_url"], slug, name=competitor.get("name", "")
                )
                filtered, skipped = ad_filter.filter(g["ads"], competitor_slug=slug)
                total_skipped += skipped
                deduped = deduplicate(filtered)
                ocr_stats = g.get("ocr_stats", {"tried": 0, "success": 0})
                total_ocr_tried += ocr_stats.get("tried", 0)
                total_ocr_success += ocr_stats.get("success", 0)
                comp_result["google"] = {
                    "ads": deduped,
                    "error": None,
                    "warning": g.get("warning"),
                    "declared_count": g.get("declared_count"),
                    "loaded_count": g.get("loaded_count"),
                    "ocr_stats": ocr_stats,
                    "advertiser_id": g.get("advertiser_id"),
                    "advertiser_name": g.get("advertiser_name"),
                }
                if g.get("warning"):
                    google_warnings.append(g["warning"])
                if g.get("advertiser_warning"):
                    google_warnings.append(g["advertiser_warning"])
            except Exception as exc:
                msg = f"{slug} (Google): {exc}"
                logger.error(msg, exc_info=True)
                errors.append(msg)
                comp_result["google"]["error"] = str(exc)
            google_secs = time.perf_counter() - t_google
            time_totals["google"] += google_secs

            # ── Facebook ─────────────────────────────────────────────────
            fb_url = competitor.get("facebook_url")
            facebook_secs = 0.0
            t_facebook = time.perf_counter()
            if fb_url:
                try:
                    fb = facebook_scraper.scrape(fb_url, slug)
                    filtered, skipped = ad_filter.filter(fb["ads"], competitor_slug=slug)
                    total_skipped += skipped
                    deduped = deduplicate(filtered)
                    comp_result["facebook"] = {
                        "ads": deduped,
                        "error": None,
                        "warning": fb.get("warning"),
                    }
                    if fb.get("warning"):
                        google_warnings.append(fb["warning"])
                    # Collect influencer flagged ads
                    for ad in deduped:
                        if ad.get("is_influencer"):
                            label = (ad.get("headline") or ad.get("text") or "")[:80]
                            comp_result["influencer_notes"].append(label)
                except Exception as exc:
                    msg = f"{slug} (Facebook): {exc}"
                    logger.error(msg, exc_info=True)
                    errors.append(msg)
                    comp_result["facebook"]["error"] = str(exc)
            facebook_secs = time.perf_counter() - t_facebook
            time_totals["facebook"] += facebook_secs

            # ── Diff ─────────────────────────────────────────────────────
            current_ads = {
                "google": comp_result["google"]["ads"],
                "facebook": comp_result["facebook"]["ads"],
            }
            t_diff = time.perf_counter()
            comp_result["diff"] = diff_engine.compare(slug, current_ads, run_date=today)
            diff_secs = time.perf_counter() - t_diff
            time_totals["diff"] += diff_secs
            logger.info(
                f"[čas] {slug}: Google {google_secs:.1f}s | Facebook {facebook_secs:.1f}s "
                f"| diff {diff_secs:.1f}s"
            )

            # Surface scrapes that came back empty against a non-empty history –
            # these are flagged as scrape problems, not as the competitor
            # pulling all campaigns (see DiffEngine.compare).
            for platform, is_suspicious in comp_result["diff"].get(
                "suspicious_empty", {}
            ).items():
                if is_suspicious:
                    msg = (
                        f"{slug} ({platform.capitalize()}): 0 reklam, ale minulý týden "
                        f"jich bylo víc – pravděpodobně chyba scrape (ne stažení kampaní), "
                        f"ověřte ručně."
                    )
                    logger.warning(msg)
                    google_warnings.append(msg)

            if not args.dry_run:
                diff_engine.save_snapshot(slug, today, current_ads, comp_result["diff"])

            results[slug] = comp_result

            # ── Kontrola času – prompt při pomalém konkurentu ────────────
            comp_elapsed = time.time() - comp_start
            comp_mins = comp_elapsed / 60
            if comp_elapsed > 15 * 60 and idx < len(competitors) - 1:
                remaining = len(competitors) - idx - 1
                logger.warning(
                    f"{slug}: zpracování trvalo {comp_mins:.1f} min "
                    f"(zbývá {remaining} konkurentů)"
                )
                print(
                    f"\n⏱  {slug} trvalo {comp_mins:.0f} minut – zřejmě hodně reklam."
                    f"\n   Zbývá {remaining} konkurentů.",
                    flush=True,
                )
                try:
                    ans = input("   Pokračovat? [Y/n]: ").strip().lower()
                except EOFError:
                    ans = "y"
                if ans == "n":
                    logger.info("Uživatel přerušil run – pokračování zrušeno.")
                    print("Run přerušen. Report bude vygenerován z dosud načtených dat.")
                    break

            # Průběžné uložení OCR cache (crash-safe – při přerušení se práce neztratí).
            google_scraper.save_ocr_cache()

            # ── Pause between competitors ─────────────────────────────────
            if idx < len(competitors) - 1:
                wait = random.uniform(3, 5)
                logger.info(f"Čekám {wait:.1f}s …")
                time.sleep(wait)

        google_scraper.save_ocr_cache()
        browser.close()

    # ── Souhrn času ────────────────────────────────────────────────────────
    n = len(results) or 1
    logger.info(
        f"[čas] SOUHRN přes {len(results)} konkurentů: "
        f"Google {time_totals['google']:.0f}s (∅ {time_totals['google']/n:.1f}s) | "
        f"Facebook {time_totals['facebook']:.0f}s (∅ {time_totals['facebook']/n:.1f}s) | "
        f"diff {time_totals['diff']:.0f}s"
    )

    # ── Report ───────────────────────────────────────────────────────────
    reporter = ReportGenerator(REPORTS_DIR)
    report_path = reporter.generate(
        results,
        today,
        total_skipped,
        errors,
        google_warnings,
        ocr_stats={"tried": total_ocr_tried, "success": total_ocr_success},
    )
    logger.info(f"Report uložen: {report_path}")
    print(f"\nHotovo. Report: {report_path}")


if __name__ == "__main__":
    main()
