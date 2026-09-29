import logging
import re
import time
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

INFLUENCER_RE = re.compile(r"placen[aá]\s+spolupráce|paid\s+partnership", re.I)
DATE_RE = re.compile(
    r"b[eě]ž[ií]\s+od|started\s+running\s+on|za[čc][aá]tek|spušt[eě]no",
    re.I,
)
UI_NOISE_RE = re.compile(
    r"^(odebrat|remove|see\s+ad\s+details|zobrazit\s+reklamu"
    r"|see\s+more|zobrazit\s+více|sponzorováno|sponsored"
    r"|výsledky|results|načítání|loading)$",
    re.I,
)
# Šum specifický pro nový EU-transparency layout. Matchuje i řádky s navazujícím
# obsahem (např. "ID knihovny: 123…"), proto NEkončí na $.
EU_NOISE_RE = re.compile(
    r"^(id\s+knihovny|library\s+id|transparentnost\s+v\s+eu"
    r"|zobrazit\s+podrobnosti|see\s+ad\s+details"
    r"|(ne)?aktivní|(in)?active"
    r"|~?\s*\d+\s*výsled|\d+\s*results?|výsledky"
    r"|filtry|filters|seřadit|třídit|sort\b|klíčové\s+slovo|keyword"
    r"|zobrazení\s+podle\s+data|jazyk:)\b",
    re.I,
)
# Kotvy pro walk-up extrakci karet.
ANCHOR_DATE_SRC = r"b[eě]ž[ií]\s+od|started\s+running"
ANCHOR_LIBID_SRC = r"id\s+knihovny|library\s+id"


def _build_url(template: str) -> str:
    date_to = date.today() - timedelta(days=1)
    date_from = date_to - timedelta(days=7)
    return (
        template
        .replace("DATE_TO", date_to.strftime("%Y-%m-%d"))
        .replace("DATE_FROM", date_from.strftime("%Y-%m-%d"))
    )


class FacebookScraper:
    def __init__(self, page: Page, max_scroll_seconds: int = 360):
        self.page = page
        self.max_scroll_seconds = max_scroll_seconds

    def scrape(self, url_template: str, competitor_slug: str) -> dict:
        result = {"ads": [], "error": None, "warning": None}
        url = _build_url(url_template)
        logger.info(f"[Facebook] {competitor_slug} → {url}")

        self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        self.page.wait_for_timeout(5_000)

        self._dismiss_consent(competitor_slug)

        login_warning = self._detect_login_wall(competitor_slug)
        if login_warning:
            result["warning"] = login_warning

        self._scroll_and_load(competitor_slug)

        ads = self._extract_ads(competitor_slug)
        result["ads"] = ads
        logger.info(f"[Facebook] {competitor_slug}: načteno {len(ads)} reklam")
        return result

    # ------------------------------------------------------------------
    # Cookie / consent dialog + login wall detection
    # ------------------------------------------------------------------

    # "Povolit všechny soubory cookie", "Allow all cookies", "Accept all" …
    _CONSENT_RE = re.compile(
        r"povolit\s+v[šs]echn|p[řr]ijmout\s+v[šs]e|allow\s+all"
        r"|accept\s+all|only\s+allow\s+essential|odmítnout",
        re.I,
    )

    def _dismiss_consent(self, slug: str):
        """Click a cookie/consent button if Facebook shows a consent dialog."""
        contexts = [self.page] + list(self.page.frames)
        for ctx in contexts:
            for getter in (
                lambda c: c.get_by_role("button", name=self._CONSENT_RE).first,
                lambda c: c.locator("button, [role=button], a").filter(
                    has_text=self._CONSENT_RE
                ).first,
            ):
                try:
                    btn = getter(ctx)
                    if btn.is_visible(timeout=800):
                        btn.click()
                        self.page.wait_for_timeout(1_500)
                        logger.info(f"[Facebook] {slug}: consent dialog zavřen.")
                        return
                except Exception:
                    continue

    def _detect_login_wall(self, slug: str) -> str | None:
        """Return a warning string if the Ad Library is hidden behind a login wall.

        Anonymous access to the Ad Library is sometimes blocked by a login
        modal/redirect; without this check that situation looks like
        "0 reklam" instead of "scrape se nepovedl".
        """
        try:
            if "login" in self.page.url or "/checkpoint" in self.page.url:
                msg = f"{slug} (Facebook): přesměrováno na přihlášení ({self.page.url})"
                logger.warning(msg)
                return msg
            login_form = self.page.locator(
                "input[name='email'], input[name='pass'], form[action*='login']"
            ).first
            if login_form.is_visible(timeout=800):
                msg = f"{slug} (Facebook): zobrazena přihlašovací zeď – data nemusí být kompletní"
                logger.warning(msg)
                return msg
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------

    def _scroll_and_load(self, slug: str = ""):
        deadline = time.time() + self.max_scroll_seconds
        prev_y, stale = -1, 0
        for _ in range(80):
            if time.time() > deadline:
                logger.warning(
                    f"[Facebook] {slug}: scroll přerušen – časový limit "
                    f"{self.max_scroll_seconds}s vypršel"
                )
                break
            self.page.evaluate("window.scrollBy(0, 900)")
            self.page.wait_for_timeout(1_800)
            y = self.page.evaluate("window.scrollY")
            if y == prev_y:
                stale += 1
                if stale >= 3:
                    break
            else:
                stale = 0
            prev_y = y

    # ------------------------------------------------------------------
    # Ad extraction – try multiple strategies in order
    # ------------------------------------------------------------------

    def _extract_ads(self, slug: str) -> list[dict]:
        # Strategy 1: role="article" (most reliable if Facebook uses it)
        ads = self._try_article_selector()
        if ads:
            logger.info(f"[Facebook] {slug}: extrakce přes [role=article] → {len(ads)} záznamů")
            return ads

        # Strategy 2: walk up from date leaf nodes (starý layout s "Běží od")
        ads = self._try_date_walkup()
        if ads:
            logger.info(f"[Facebook] {slug}: extrakce přes date-walkup → {len(ads)} záznamů")
            return ads

        # Strategy 3: walk up from "ID knihovny"/"Library ID" (nový EU-transparency
        # layout – karty nezobrazují "Běží od", datum je schované pod detailem).
        ads = self._try_library_id_walkup()
        if ads:
            logger.info(
                f"[Facebook] {slug}: extrakce přes library-id walkup (EU layout) "
                f"→ {len(ads)} záznamů"
            )
            return ads

        # Nothing found
        self._save_debug(slug)
        return []

    # ── Strategy 1: [role="article"] ────────────────────────────────────

    def _try_article_selector(self) -> list[dict]:
        article_locators = self.page.locator('[role="article"]').all()
        if not article_locators:
            return []

        ads = []
        for loc in article_locators:
            try:
                # Use inner_text() first; fall back to textContent via evaluate
                try:
                    text = loc.inner_text(timeout=1_000)
                except Exception:
                    text = loc.evaluate("el => el.textContent") or ""

                ad = self._parse_card_text(text, loc)
                if ad:
                    ads.append(self._normalise(ad))
            except Exception as e:
                logger.debug(f"Article card error: {e}")

        return ads

    # ── Strategy 2: walk up from date span elements ─────────────────────
    # Key insight from DOM inspection: dates are in <span> elements.
    # Walk UP from each span until the parent's textContent contains 2+ dates
    # → at that point we've crossed the single-ad boundary, so return the
    #   previous element (which is the individual ad card).

    def _try_date_walkup(self) -> list[dict]:
        """Starý layout: karty mají viditelné 'Běží od' / 'Started running'."""
        return self._items_to_ads(self._walkup_collect(ANCHOR_DATE_SRC))

    def _try_library_id_walkup(self) -> list[dict]:
        """Nový EU-transparency layout: 'Běží od' chybí, ale každá karta má
        'ID knihovny' / 'Library ID'. Kotvíme walk-up na tento marker."""
        return self._items_to_ads(self._walkup_collect(ANCHOR_LIBID_SRC))

    def _walkup_collect(self, anchor_src: str) -> list[dict]:
        """Najdi karty: od každého <span> obsahujícího kotvu (anchor_src) jdi
        nahoru po DOM, dokud rodič neobsahuje 2+ výskyty kotvy → tehdy jsme
        překročili hranici jedné reklamy a předchozí prvek je samotná karta.

        Kotva se předává jako zdroj regexu (data, single backslash), datum a
        video se extrahují vždy stejně bez ohledu na použitou kotvu.
        """
        raw = self.page.evaluate(
            """(anchorSrc) => {
            const ANCHOR   = new RegExp(anchorSrc, 'i');
            const ANCHOR_G = new RegExp(anchorSrc, 'ig');
            const PARTNER_RE = /placen[aá]\\s+spolupráce|paid\\s+partnership/i;
            // Šum obalu stránky (nav/header/footer). Když se objeví v textu předka,
            // překročili jsme hranici karty i bez druhé kotvy → důležité pro stránky
            // s JEDINOU reklamou, kde se počet kotev nikdy nezvýší na 2.
            const CHROME_RE = /knihovna\\s+reklam|stav\\s+syst[eé]mu|reporty\\s+knihovny|ad\\s+library\\s+api|brandovan[yý]\\s+obsah|©\\s*meta/i;

            const anchorSpans = Array.from(document.querySelectorAll('span')).filter(el => {
                const t = (el.textContent || '').trim();
                return t.length > 0 && t.length < 150 && ANCHOR.test(t);
            });

            function findCard(anchorEl) {
                let prev = anchorEl;
                let el   = anchorEl.parentElement;
                while (el && el !== document.body) {
                    const t = el.textContent || '';
                    const cnt = (t.match(ANCHOR_G) || []).length;
                    // Hranice karty: předek má 2+ kotvy (multi-ad kontejner),
                    // je obří, NEBO už obsahuje šum obalu stránky (single-ad případ).
                    if (cnt > 1 || t.length > 12000 || CHROME_RE.test(t)) {
                        return (prev.textContent || '').trim().length > 50 ? prev : null;
                    }
                    prev = el;
                    el   = el.parentElement;
                }
                // Dosažen body bez překročení hranice (typicky jediná reklama na
                // stránce) → vrať poslední rozumný předek místo zahození reklamy.
                return (prev.textContent || '').trim().length > 50 ? prev : null;
            }

            const seen  = new Set();
            const cards = [];
            for (const span of anchorSpans) {
                const card = findCard(span);
                if (card && !seen.has(card)) {
                    seen.add(card);
                    cards.push(card);
                }
            }

            return cards.map(card => {
                const raw = ((card.innerText || '').trim() ||
                             (card.textContent || '').trim());
                const imgEl = card.querySelector('img:not([role="presentation"])');

                // Datum spuštění (jen starý layout; EU layout ho na kartě nemá → '')
                const dm = raw.match(
                    /(?:b[eě]ž[ií]\\s+od|started\\s+running\\s+on)\\s+([\\d\\s.\\/]+\\d{4})/i
                );

                // Video: <video> element NEBO trvání "0:10 / 1:23"
                const DURATION_RE = /\\d{1,2}:\\d{2}\\s*\\/\\s*\\d{1,2}:\\d{2}/;
                const hasVideoEl = card.querySelector('video') !== null;
                const durationMatch = raw.match(DURATION_RE);
                const isVideo = hasVideoEl || durationMatch !== null;
                const videoDuration = durationMatch
                    ? durationMatch[0].split('/')[1].trim()
                    : '';

                return {
                    raw_text:       raw,
                    image_alt:      imgEl ? (imgEl.alt || imgEl.getAttribute('aria-label') || '') : '',
                    image_src:      imgEl ? (imgEl.src || '') : '',
                    is_influencer:  PARTNER_RE.test(raw),
                    start_date:     dm ? dm[1].trim() : '',
                    is_video:       isVideo,
                    video_duration: videoDuration,
                };
            });
        }""",
            anchor_src,
        )
        return raw or []

    def _items_to_ads(self, raw: list[dict]) -> list[dict]:
        """Společný převod nasbíraných DOM položek na strukturované reklamy."""
        ads = []
        for item in raw:
            ad = self._parse_card_text(item["raw_text"], None)
            if not ad:
                continue
            ad["image_alt"] = item.get("image_alt", "")
            ad["image_src"] = item.get("image_src", "")
            ad["is_influencer"] = item.get("is_influencer", False)
            ad["is_video"] = item.get("is_video", False)
            ad["video_duration"] = item.get("video_duration", "")
            # Override ad_type if video detected
            if ad["is_video"]:
                ad["ad_type"] = "video"
            ads.append(self._normalise(ad))

        return ads

    # ------------------------------------------------------------------
    # Parse raw card text into structured fields
    # ------------------------------------------------------------------

    def _parse_card_text(self, text: str, locator) -> dict | None:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            return None

        # Start date
        date_idx = next((i for i, l in enumerate(lines) if DATE_RE.search(l)), -1)
        start_date = ""
        if date_idx >= 0:
            m = re.search(
                r"(\d{1,2}[.\/ ]\d{1,2}[.\/ ]\d{2,4}|\d{4}-\d{2}-\d{2}"
                r"|\d{1,2}\.\s*\d{1,2}\.\s*\d{4})",
                lines[date_idx],
            )
            start_date = m.group(1) if m else ""

        # Influencer
        is_influencer = bool(INFLUENCER_RE.search(text))

        # Image alt (if we have a locator)
        image_alt, image_src = "", ""
        if locator:
            try:
                img = locator.locator("img:not([role='presentation'])").first
                if img.count():
                    image_alt = img.get_attribute("alt") or ""
                    image_src = img.get_attribute("src") or ""
            except Exception:
                pass

        # Content lines (excluding date line, UI noise a EU-layout šum)
        content = [
            l for i, l in enumerate(lines)
            if i != date_idx
            and not UI_NOISE_RE.match(l)
            and not EU_NOISE_RE.match(l)
        ]

        if not content:
            return None

        # Main text: longest line or first >10 chars
        main_text = max(content, key=len) if content else ""
        if len(main_text) < 5:
            return None

        # Try to identify headline and description from remaining lines
        rest = [l for l in content if l != main_text]
        headline = next((l for l in rest if 5 < len(l) < 150), "")
        rest2 = [l for l in rest if l != headline]
        description = next((l for l in rest2 if 5 < len(l) < 300), "")

        # CTA: short line that looks like a button label
        # Exclude video duration strings like "0:10 / 1:23"
        DURATION_LINE_RE = re.compile(r"^\d{1,2}:\d{2}\s*/\s*\d{1,2}:\d{2}$")
        cta_candidates = [
            l for l in content
            if 2 < len(l) < 40 and not DATE_RE.search(l) and not DURATION_LINE_RE.match(l)
        ]
        cta = cta_candidates[-1] if cta_candidates else ""

        return {
            "ad_type": "banner" if image_alt or image_src else "text",
            "text": main_text,
            "headline": headline,
            "description": description,
            "image_alt": image_alt,
            "image_src": image_src,
            "cta": cta,
            "start_date": start_date,
            "is_influencer": is_influencer,
            "raw_text": text,
        }

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------

    def _save_debug(self, slug: str):
        try:
            logs_dir = Path("logs")
            logs_dir.mkdir(exist_ok=True)
            path = logs_dir / f"debug_facebook_{slug}.html"
            path.write_text(self.page.content(), encoding="utf-8")
            ss = logs_dir / f"debug_facebook_{slug}.png"
            self.page.screenshot(path=str(ss))
            logger.warning(
                f"[Facebook] Žádné reklamy nenalezeny! HTML: {path}, screenshot: {ss}"
            )
        except Exception as e:
            logger.debug(f"Debug dump failed: {e}")

    @staticmethod
    def _normalise(ad: dict) -> dict:
        parts = filter(None, [
            ad.get("text", ""),
            ad.get("headline", ""),
            ad.get("description", ""),
            ad.get("image_alt", ""),
            ad.get("cta", ""),
        ])
        ad["full_text"] = " ".join(parts).strip()
        ad.setdefault("platform", "facebook")
        return ad
