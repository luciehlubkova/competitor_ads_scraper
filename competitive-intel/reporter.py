import re
from datetime import date, datetime, timedelta
from pathlib import Path


def _fmt_date(d: date) -> str:
    return f"{d.day}.{d.month}.{d.year}"


def _ad_text_short(ad: dict, max_len: int = 120) -> str:
    text = (
        ad.get("text")
        or ad.get("headline")
        or ad.get("description")
        or ad.get("image_alt")
        or ad.get("raw_text")
        or ""
    ).strip()
    # Collapse all whitespace (incl. newlines) to single spaces – a newline
    # inside a Markdown table cell breaks the table layout (and HTML conversion).
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_len:
        text = text[:max_len].rstrip() + "…"
    # Escape pipe characters so they don't break Markdown tables
    return text.replace("|", "｜")


def _ad_cta(ad: dict) -> str:
    return (ad.get("cta") or "—").strip()


def _ad_date(ad: dict) -> str:
    return (ad.get("start_date") or "—").strip()


def _ad_type_icon(ad: dict) -> str:
    """🎬 for video, 📷 for static image/banner."""
    return "🎬" if ad.get("is_video") else "📷"


def _new_ads_table(ads_google: list, ads_facebook: list) -> str:
    if not ads_google and not ads_facebook:
        return ""
    rows = [
        "| Platforma | Typ | Text reklamy | CTA | Datum |",
        "|-----------|:---:|-------------|-----|-------|",
    ]
    for ad in ads_google:
        rows.append(
            f'| Google | {_ad_type_icon(ad)} | "{_ad_text_short(ad)}" | {_ad_cta(ad)} | — |'
        )
    for ad in ads_facebook:
        rows.append(
            f'| Facebook | {_ad_type_icon(ad)} | "{_ad_text_short(ad)}" | {_ad_cta(ad)} | {_ad_date(ad)} |'
        )
    return "\n".join(rows)


def _removed_ads_table(ads_google: list, ads_facebook: list) -> str:
    if not ads_google and not ads_facebook:
        return ""
    rows = ["| Platforma | Text reklamy |", "|-----------|-------------|"]
    for ad in ads_google:
        rows.append(f'| Google | "{_ad_text_short(ad)}" |')
    for ad in ads_facebook:
        rows.append(f'| Facebook | "{_ad_text_short(ad)}" |')
    return "\n".join(rows)


def _ocr_display(res: dict) -> str | None:
    """OCR čitelnost pro daného konkurenta (společné pro změněné i nezměněné)."""
    comp_ocr = res["google"].get("ocr_stats", {})
    tried = comp_ocr.get("tried", 0)
    success = comp_ocr.get("success", 0)
    if tried <= 0:
        return None
    pct = round(success / tried * 100)
    label = f"{pct} % ({success}/{tried} kreativ)"
    if pct < 90:
        return (
            f"⚠️ **OCR čitelnost: {label}** – část textu z Google reklam "
            f"mohla být přečtena neúplně."
        )
    return f"✅ **OCR čitelnost: {label}**"


def _platform_status(res: dict, diff: dict, platform: str) -> str:
    """Stručný stav platformy pro inzerenta beze změny: aktuální počet reklam,
    nebo upozornění u prázdného/blokovaného scrape (suspicious_empty)."""
    if diff.get("suspicious_empty", {}).get(platform, False):
        return "⚠️ scrape prázdný – přeneseno z min. týdne (ověřte ručně)"
    n = len(res.get(platform, {}).get("ads", []))
    return f"{n} reklam (beze změny)"


class ReportGenerator:
    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir

    def generate(
        self,
        results: dict,
        run_date: date,
        total_skipped: int,
        errors: list[str],
        google_warnings: list[str],
        ocr_stats: dict | None = None,
    ) -> Path:
        date_to = run_date - timedelta(days=1)
        date_from = date_to - timedelta(days=7)

        # Odděl vlastní brand (Direct) od konkurentů — různé zpracování v reportu
        own_brand = {k: v for k, v in results.items() if v["competitor"].get("type") == "vlastní"}
        competitors_only = {k: v for k, v in results.items() if v["competitor"].get("type") != "vlastní"}

        first_run_count = sum(
            1 for r in competitors_only.values() if r["diff"]["is_first_run"]
        )
        total = len(competitors_only)  # vlastní brand se do počtu nepočítá
        if first_run_count == 0:
            first_run_label = "ne"
        elif first_run_count == total:
            first_run_label = "ano (první běh)"
        else:
            first_run_label = f"částečně – {first_run_count} z {total} konkurentů poprvé"

        changed, unchanged = self._split_results(competitors_only)

        lines = []

        # ── Header ──────────────────────────────────────────────────────
        lines += [
            "# Competitive Intelligence Report",
            f"## Týden: {_fmt_date(date_from)} – {_fmt_date(date_to)}",
            f"Sledováno: {len(competitors_only)} konkurentů | Google Ads Transparency Center + Facebook Ad Library  ",
            f"První screening: {first_run_label}",
            "",
            "---",
            "",
        ]

        # ── Own brand (Direct pojišťovna) ────────────────────────────────
        if own_brand:
            lines.append("## Naše komunikace (Direct pojišťovna)")
            lines.append(
                "Vlastní reklamní aktivita Direct pojišťovny v tomto týdnu — "
                "slouží jako referenční kontext pro srovnání s konkurencí."
            )
            lines.append("")
            for slug, res in own_brand.items():
                comp = res["competitor"]
                diff = res["diff"]
                new_g = diff["new"].get("google", [])
                new_fb = diff["new"].get("facebook", [])
                rem_g = diff["removed"].get("google", [])
                unch_g = diff["unchanged_count"].get("google", 0)
                unch_fb = diff["unchanged_count"].get("facebook", 0)
                ocr_display = _ocr_display(res)
                lines += [
                    f"### {comp['name']}",
                    f"**Google:** {len(new_g)} nových reklam | **Facebook:** {len(new_fb)} nových reklam",
                ]
                if ocr_display:
                    lines.append(ocr_display)
                lines.append("")
                if new_g or new_fb:
                    lines.append("#### Nové reklamy")
                    table = _new_ads_table(new_g, new_fb)
                    if table:
                        lines.append(table)
                    lines.append("")
                if rem_g:
                    lines.append("#### Odstraněné reklamy")
                    lines.append(f"Google: −{len(rem_g)} kreativ oproti minulému týdnu.")
                    lines.append("")
                total_unch = unch_g + unch_fb
                if total_unch:
                    lines.append("#### Beze změny")
                    lines.append(f"{total_unch} reklam se opakuje z minulého týdne.")
                    lines.append("")
                lines.append("---")
                lines.append("")

        # ── Competitors with changes ─────────────────────────────────────
        lines.append(f"## Konkurenti se změnami ({len(changed)} z {len(competitors_only)})")
        lines.append("")

        for slug, res in changed:
            comp = res["competitor"]
            diff = res["diff"]

            new_g = diff["new"].get("google", [])
            new_fb = diff["new"].get("facebook", [])
            rem_g = diff["removed"].get("google", [])
            rem_fb = diff["removed"].get("facebook", [])
            unch_g = diff["unchanged_count"].get("google", 0)
            unch_fb = diff["unchanged_count"].get("facebook", 0)

            # OCR quality for this competitor
            ocr_display = _ocr_display(res)

            first_run_tag = " _(první screening)_" if diff.get("is_first_run") else ""
            lines += [
                f"### {comp['name']}{first_run_tag}",
                f"**Typ:** {comp['type']} | **Priorita:** {comp['priority']}  ",
                f"**Google:** {len(new_g)} nových reklam | **Facebook:** {len(new_fb)} nových reklam",
            ]
            if ocr_display:
                lines.append(ocr_display)

            lines.append("")

            # New ads
            if new_g or new_fb:
                lines.append("#### Nové reklamy")
                table = _new_ads_table(new_g, new_fb)
                if table:
                    lines.append(table)
                lines.append("")

            # Influencer note
            influencer_notes = res.get("influencer_notes", [])
            if influencer_notes:
                lines.append(f"> ⚠ Influencer spolupráce: {'; '.join(influencer_notes[:3])}")
                lines.append("")

            # Removed ads — u Google jen počtem (dynamické search reklamy
            # rotují kreativní variace, plná tabulka OCR textů jen nafukuje
            # report a nemá výpovědní hodnotu). Facebook removed je vždy [].
            if rem_g or rem_fb:
                lines.append("#### Odstraněné reklamy")
                if rem_g:
                    lines.append(
                        f"Google: −{len(rem_g)} kreativ oproti minulému týdnu."
                    )
                if rem_fb:
                    table = _removed_ads_table([], rem_fb)
                    if table:
                        lines.append(table)
                lines.append("")

            # Unchanged
            total_unch = unch_g + unch_fb
            if total_unch:
                lines.append(f"#### Beze změny")
                lines.append(f"{total_unch} reklam se opakuje z minulého týdne.")
                lines.append("")

            lines.append("---")
            lines.append("")

        # ── Competitors without changes ──────────────────────────────────
        # Zobrazujeme i inzerenty beze změny, aby výstup vždy obsahoval informaci
        # o KAŽDÉM sledovaném inzerentovi (aktuální počty + OCR + případná varování).
        lines.append(f"## Beze změny oproti minulému týdnu ({len(unchanged)} z {len(competitors_only)})")
        lines.append(
            "Tito inzerenti jsou aktivní, ale nemají žádnou novou ani odstraněnou "
            "reklamu oproti minulému týdnu."
        )
        lines.append("")

        for slug, res in unchanged:
            comp = res["competitor"]
            diff = res["diff"]
            lines += [
                f"### {comp['name']} — _beze změny_",
                f"**Typ:** {comp['type']} | **Priorita:** {comp['priority']}  ",
                f"**Google:** {_platform_status(res, diff, 'google')} | "
                f"**Facebook:** {_platform_status(res, diff, 'facebook')}",
            ]
            ocr_display = _ocr_display(res)
            if ocr_display:
                lines.append(ocr_display)
            gw = res["google"].get("warning")
            if gw:
                lines.append(f"> ⚠ {gw}")
            lines.append("")
            lines.append("---")
            lines.append("")

        # ── Technical info ───────────────────────────────────────────────
        # Overall OCR quality line
        ocr_summary = ""
        if ocr_stats and ocr_stats.get("tried", 0) > 0:
            t = ocr_stats["tried"]
            s = ocr_stats["success"]
            pct = round(s / t * 100)
            ocr_summary = f"{pct} % ({s}/{t} kreativ)"
            if pct < 90:
                ocr_summary += " ⚠️ pod 90 %"

        lines += [
            "## Technické info",
            f"- Vygenerováno: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            f"- Přeskočeno (neg. klíčová slova): {total_skipped} reklam",
            f"- OCR čitelnost Google kreativ: {ocr_summary if ocr_summary else 'N/A'}",
            f"- Chyby načítání: {', '.join(errors) if errors else 'žádné'}",
            f"- Varování (počet reklam Google / consent / přihlášení): "
            f"{', '.join(google_warnings) if google_warnings else 'žádné'}",
        ]

        content = "\n".join(lines)
        path = self.reports_dir / f"report_{run_date.isoformat()}.md"
        path.write_text(content, encoding="utf-8")
        return path

    # ------------------------------------------------------------------

    def _split_results(self, results: dict):
        changed, unchanged = [], []
        for slug, res in results.items():
            diff = res["diff"]
            new_total = sum(len(v) for v in diff["new"].values())
            rem_total = sum(len(v) for v in diff["removed"].values())
            if new_total > 0 or rem_total > 0 or diff["is_first_run"]:
                changed.append((slug, res))
            else:
                unchanged.append((slug, res))
        return changed, unchanged
