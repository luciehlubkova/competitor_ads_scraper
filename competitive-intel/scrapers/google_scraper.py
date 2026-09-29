import io
import logging
import re
import time
import unicodedata
from pathlib import Path

from playwright.sync_api import Page

logger = logging.getLogger(__name__)


def _normalize(s: str) -> str:
    """Lowercase and strip diacritics so 'ePojištění' == 'epojisteni'."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    import pytesseract
    import os as _os
    if _os.name == "nt":
        _candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            _os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for _path in _candidates:
            if _os.path.exists(_path):
                pytesseract.pytesseract.tesseract_cmd = _path
                break
    pytesseract.get_tesseract_version()  # raises if binary missing
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False


class GoogleScraper:
    # If the light (non-inverted) OCR variant already reads this well, skip the
    # inverted pass – saves a second Tesseract run on the (common) clear ads.
    LIGHT_OK_THRESHOLD = 0.45

    def __init__(
        self,
        page: Page,
        max_scroll_seconds: int = 240,
        max_ocr_seconds: int = 600,
        ocr_cache_path: "Path | str | None" = None,
    ):
        self.page = page
        # Budget for phase 1 (scrolling to discover creatives, no OCR). Scrolling
        # is fast and stops early on "stale", so this is mostly a safety net.
        self.max_scroll_seconds = max_scroll_seconds
        # Separate budget for phase 2 (OCR over the discovered creatives). When
        # this runs out, remaining creatives are kept but without OCR text.
        self.max_ocr_seconds = max_ocr_seconds
        # creative_id -> ocr_text. Persisted to disk so a creative read in an
        # earlier weekly run is never OCR'd again (creative_id is stable, and
        # most ads repeat week to week).
        self._ocr_cache_path = Path(ocr_cache_path) if ocr_cache_path else None
        self._ocr_cache: dict[str, str] = self._load_ocr_cache()
        self._ocr_stats: dict[str, int] = {"tried": 0, "success": 0}
        self._selected_advertiser_id: str | None = None
        self._selected_by_hint: bool = False
        self._explicitly_pinned: bool = False

    def _load_ocr_cache(self) -> dict[str, str]:
        if self._ocr_cache_path and self._ocr_cache_path.exists():
            try:
                import json
                data = json.loads(self._ocr_cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    logger.info(f"[Google] OCR cache načtena: {len(data)} kreativ")
                    return {str(k): str(v) for k, v in data.items()}
            except Exception as e:
                logger.warning(f"[Google] OCR cache nešla načíst: {e}")
        return {}

    def save_ocr_cache(self):
        if not self._ocr_cache_path:
            return
        try:
            import json
            self._ocr_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._ocr_cache_path.write_text(
                json.dumps(self._ocr_cache, ensure_ascii=False), encoding="utf-8"
            )
            logger.info(f"[Google] OCR cache uložena: {len(self._ocr_cache)} kreativ")
        except Exception as e:
            logger.warning(f"[Google] OCR cache nešla uložit: {e}")

    def scrape(self, url: str, competitor_slug: str, name: str = "") -> dict:
        self._ocr_stats = {"tried": 0, "success": 0}  # reset per competitor
        self._selected_advertiser_id = None
        self._selected_by_hint = False
        self._explicitly_pinned = False
        result = {
            "ads": [],
            "declared_count": None,
            "loaded_count": 0,
            "warning": None,
            "error": None,
            "ocr_stats": self._ocr_stats,
            "advertiser_id": None,
            "advertiser_name": "",
            "advertiser_warning": None,
        }

        hints = self._build_hints(name, competitor_slug)

        logger.info(f"[Google] {competitor_slug} → {url}")
        self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        self.page.wait_for_timeout(4_000)

        self._dismiss_consent(competitor_slug)

        self._click_through_to_advertiser(competitor_slug, hints)

        declared = self._get_declared_count()
        result["declared_count"] = declared
        logger.info(f"[Google] {competitor_slug}: deklarováno reklam = {declared}")

        ads = self._scroll_and_collect(declared, competitor_slug)
        result["ads"] = ads
        result["loaded_count"] = len(ads)
        result["advertiser_id"] = self._selected_advertiser_id

        # Verify we landed on the right advertiser: the creative cards carry the
        # advertiser's displayed name. If none of our hint tokens appear in it,
        # we likely picked the wrong advertiser via the fallback link.
        advertiser_name = self._detected_advertiser_name(ads)
        result["advertiser_name"] = advertiser_name
        if self._explicitly_pinned:
            # ID je pinováno přímo v configu → důvěřujeme mu. Značka se může
            # legitimně jmenovat jinak než inzerent (rixo, allianz, epojisteni →
            # Klik.cz & ePojisteni.cz, povinne-ruceni → Suri). Žádné varování.
            logger.info(
                f"[Google] {competitor_slug}: inzerent '{advertiser_name}' "
                f"(ID {self._selected_advertiser_id}, pinováno v configu)"
            )
        elif advertiser_name and hints:
            got = _normalize(advertiser_name)
            if not any(h in got for h in hints):
                warn = (
                    f"{competitor_slug} (Google): vybraný inzerent '{advertiser_name}' "
                    f"(ID {self._selected_advertiser_id}) neodpovídá očekávanému "
                    f"'{name or competitor_slug}' – ověřte správnost, případně doplňte "
                    f"přímé advertiser URL do competitors.yaml."
                )
                result["advertiser_warning"] = warn
                logger.warning(warn)
            else:
                logger.info(
                    f"[Google] {competitor_slug}: inzerent '{advertiser_name}' "
                    f"(ID {self._selected_advertiser_id}, "
                    f"{'hint' if self._selected_by_hint else 'fallback'}) – shoda OK"
                )

        if declared is not None and len(ads) != declared:
            msg = (
                f"{competitor_slug} (Google): deklarováno {declared} reklam, "
                f"načteno {len(ads)}"
            )
            result["warning"] = msg
            logger.warning(msg)

        return result

    @staticmethod
    def _build_hints(name: str, slug: str) -> list[str]:
        """Distinctive lowercase, diacritics-free tokens used to recognise the
        right advertiser. Built from both the friendly name and the slug, with
        any domain TLD stripped (so 'koop.cz' also yields 'koop')."""
        hints: set[str] = set()
        for src in (name, slug):
            n = _normalize(src).replace("-", "")
            if n:
                hints.add(n)
                if "." in n:
                    hints.add(n.split(".", 1)[0])
        return [h for h in hints if len(h) >= 3]

    @staticmethod
    def _detected_advertiser_name(ads: list[dict]) -> str:
        """Most common non-empty advertiser name across creative cards."""
        counts: dict[str, int] = {}
        for ad in ads:
            nm = (ad.get("description") or "").strip()
            if nm:
                counts[nm] = counts.get(nm, 0) + 1
        if not counts:
            return ""
        return max(counts, key=counts.get)

    # ------------------------------------------------------------------
    # Cookie / consent dialog
    # ------------------------------------------------------------------

    # "Přijmout vše", "Souhlasím", "Accept all", "I agree", "Allow all" …
    _CONSENT_RE = re.compile(
        r"p[řr]ijmout\s+v[šs]e|p[řr]ijmout\s+v[šs]echn|souhlas[ií]m"
        r"|accept\s+all|i\s+agree|allow\s+all|povolit\s+v[šs]echn",
        re.I,
    )

    def _dismiss_consent(self, slug: str):
        """Click a cookie/consent accept button if a dialog overlays the page.

        Google's consent prompt is sometimes rendered inside a consent.google.com
        iframe, so we scan both the main page and every child frame.
        """
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
                        self.page.wait_for_timeout(1_200)
                        logger.info(f"[Google] {slug}: consent dialog zavřen.")
                        return
                except Exception:
                    continue

    # ------------------------------------------------------------------
    # Click-through from domain search results → advertiser ads page
    # ------------------------------------------------------------------

    def _click_through_to_advertiser(self, slug: str, hints: list[str]):
        # Already a pinned /advertiser/ URL → no search needed, just record the ID.
        if "/advertiser/" in self.page.url:
            m = re.search(r"/advertiser/(AR\w+)", self.page.url)
            if m:
                self._selected_advertiser_id = m.group(1)
                self._selected_by_hint = True  # explicitly pinned in config
                self._explicitly_pinned = True  # ID z configu = důvěryhodné
            logger.debug(f"[Google] {slug}: již na stránce inzerenta (přímé URL)")
            return

        try:
            # Pick the advertiser whose nearby DOM text matches one of our hint
            # tokens. Both sides are compared with diacritics stripped, so a slug
            # like "epojisteni" matches the displayed name "ePojištění.cz".
            selected = self.page.evaluate(
                """(hints) => {
                    const links = Array.from(
                        document.querySelectorAll('a[href*="/advertiser/"]')
                    );
                    if (!links.length) return null;

                    const norm = (t) => (t || '')
                        .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
                        .toLowerCase();

                    // Strategy 1: a link whose nearby DOM text contains a hint.
                    // Walk up at most 8 ancestors; ignore containers wider than
                    // 800 chars (page-level wrappers that contain everything).
                    for (const link of links) {
                        let el = link;
                        for (let depth = 0; depth < 8; depth++) {
                            if (!el || el === document.body) break;
                            const t = norm(el.textContent);
                            if (t.length < 800 && hints.some(h => t.includes(h))) {
                                return { href: link.href, byHint: true };
                            }
                            el = el.parentElement;
                        }
                    }

                    // Strategy 2: first link as fallback (unverified).
                    return { href: links[0].href, byHint: false };
                }""",
                hints,
            )

            if not selected or not selected.get("href"):
                logger.debug(f"[Google] {slug}: žádný odkaz na inzerenta")
                return

            m = re.search(r"/advertiser/(AR\w+)", selected["href"])
            if not m:
                logger.debug(
                    f"[Google] {slug}: nelze extrahovat advertiser ID z {selected['href']}"
                )
                return

            advertiser_id = m.group(1)
            self._selected_advertiser_id = advertiser_id
            self._selected_by_hint = bool(selected.get("byHint"))
            if not self._selected_by_hint:
                logger.warning(
                    f"[Google] {slug}: hint nenalezen ve výsledcích, použit fallback "
                    f"(první inzerent {advertiser_id}) – výběr nemusí být správný."
                )
            overview_url = (
                f"https://adstransparency.google.com/advertiser/{advertiser_id}"
                f"?region=CZ&preset-date=Last+7+days"
            )
            logger.info(f"[Google] {slug}: navigace na přehled inzerenta {advertiser_id}")
            self.page.goto(overview_url, wait_until="domcontentloaded", timeout=20_000)
            self.page.wait_for_timeout(3_000)

        except Exception as e:
            logger.debug(f"[Google] {slug}: click-through chyba: {e}")

    # ------------------------------------------------------------------
    # Count detection
    # ------------------------------------------------------------------

    def _get_declared_count(self) -> int | None:
        try:
            return self.page.evaluate("""() => {
                const patterns = [
                    /(\\d[\\d\\s,]*) reklam/i,
                    /(\\d[\\d\\s,]*) výsledk/i,
                    /(\\d[\\d\\s,]*) results?/i,
                    /(\\d[\\d\\s,]*) ads?\\b/i,
                ];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const t = walker.currentNode.textContent.trim();
                    if (t.length > 50) continue;
                    for (const pat of patterns) {
                        const m = t.match(pat);
                        if (m) {
                            const n = parseInt(m[1].replace(/[\\s,]/g, ''), 10);
                            if (!isNaN(n) && n > 0 && n < 100000) return n;
                        }
                    }
                }
                return null;
            }""")
        except Exception as e:
            logger.debug(f"Declared count error: {e}")
            return None

    # ------------------------------------------------------------------
    # Scroll + incremental collection (handles virtual scrolling)
    # ------------------------------------------------------------------

    def _scroll_and_collect(self, target: int | None, slug: str) -> list[dict]:
        # Phase 1 – discovery: scroll and collect creative metadata only (no
        # OCR), so the scroll budget is never eaten by OCR. Two buckets because
        # a page is either the rich creative-preview layout or the JS fallback.
        seen_meta: dict[str, dict] = {}   # creative-preview metadata
        seen_js: dict[str, dict] = {}     # JS-fallback ads (text ads, no OCR)
        prev_scroll_y = -1
        stale = 0
        deadline = time.time() + self.max_scroll_seconds
        t_discovery = time.perf_counter()

        for step in range(80):
            if time.time() > deadline:
                logger.warning(
                    f"[Google] {slug}: discovery přerušeno – časový limit "
                    f"{self.max_scroll_seconds}s vypršel, nalezeno "
                    f"{len(seen_meta) + len(seen_js)} kreativ"
                )
                break

            meta = self._extract_creative_meta()
            if meta:
                for info in meta:
                    key = info.get("creativeId") or info.get("imgSrc") or ""
                    if key and key not in seen_meta:
                        seen_meta[key] = info
            else:
                for ad in self._extract_via_js():
                    key = ad.get("image_src") or (ad.get("full_text") or "")[:80]
                    if key and key not in seen_js:
                        seen_js[key] = ad

            logger.debug(
                f"[Google] {slug} scroll={step} "
                f"meta={len(seen_meta)} js={len(seen_js)}"
            )

            # Note: we deliberately do NOT stop once we reach the declared count.
            # That count is parsed heuristically and can be wrong/low, which would
            # cut discovery short. We scroll until the page stops growing (stale)
            # or the limit hits; declared count is only for the mismatch warning.

            try:
                btn = self.page.locator("button, a").filter(
                    has_text=re.compile(
                        r"see\s+all\s+ads|zobrazit\s+v[sš]echny\s+reklamy"
                        r"|načíst\s+další|load\s+more|show\s+more"
                        r"|zobrazit\s+více|načíst\s+vše|show\s+all",
                        re.I,
                    )
                ).first
                if btn.is_visible(timeout=300):
                    btn.click()
                    self.page.wait_for_timeout(2_500)
            except Exception:
                pass

            self.page.evaluate("window.scrollBy(0, 900)")
            self.page.wait_for_timeout(1_600)

            scroll_y = self.page.evaluate("window.scrollY")
            if scroll_y == prev_scroll_y:
                stale += 1
                if stale >= 3:
                    logger.debug(f"[Google] {slug}: no more scroll after {step} steps")
                    break
            else:
                stale = 0
            prev_scroll_y = scroll_y

        discovery_secs = time.perf_counter() - t_discovery

        # Phase 2 – OCR the discovered creatives under their own time budget.
        t_ocr = time.perf_counter()
        ads = self._ocr_collected(list(seen_meta.values()), slug)
        ocr_secs = time.perf_counter() - t_ocr
        ads += list(seen_js.values())

        logger.info(
            f"[čas] {slug} Google: discovery {discovery_secs:.1f}s "
            f"({len(seen_meta) + len(seen_js)} kreativ), OCR {ocr_secs:.1f}s"
        )

        if not ads:
            self._save_debug_html(slug, "google")

        return ads

    def _ocr_collected(self, meta_list: list[dict], slug: str) -> list[dict]:
        """Phase 2: turn discovered creative metadata into ad dicts, running OCR
        until max_ocr_seconds is exhausted. Creatives discovered after the budget
        runs out are still returned, just without OCR text (so the ad count and
        diff stay correct; the OCR readability metric will reflect the gap)."""
        ads: list[dict] = []
        ocr_deadline = time.time() + self.max_ocr_seconds
        budget_hit = 0
        fresh = 0        # creatives OCR'd this run
        cache_hits = 0   # creatives reused from the persistent cache
        tried = 0        # non-video creatives = readability denominator
        success = 0      # non-video creatives that yielded readable text

        for info in meta_list:
            creative_id = info.get("creativeId", "")
            name = info.get("name", "")
            image_src = info.get("imgSrc", "")
            is_video = info.get("isVideo", False)

            if creative_id and creative_id in self._ocr_cache:
                image_text = self._ocr_cache[creative_id]
                cache_hits += 1
            elif is_video:
                image_text = ""  # videa nečteme OCR
            elif time.time() > ocr_deadline:
                image_text = ""
                budget_hit += 1
            else:
                res = self._ocr_creative(creative_id, image_src)
                fresh += 1
                if res is None:
                    # OCR se vůbec nepodařilo spustit (nedostupný obrázek apod.)
                    # – necacheujeme, ať se příští týden zkusí znovu.
                    image_text = ""
                else:
                    image_text = res
                    if creative_id:
                        self._ocr_cache[creative_id] = res

            ad = {
                "ad_type": "video" if is_video else "banner",
                "is_video": is_video,
                "headline": image_text if image_text else (
                    "[video reklama]" if is_video else "[grafická reklama]"
                ),
                "url": "",
                "description": name,
                "cta": "",
                "extensions": [],
                "image_alt": "",
                "image_src": image_src,
                "image_text": "",
                "raw_text": f"{image_text} {name}".strip(),
                "creative_id": creative_id,
            }
            ad = self._normalise(ad)
            if creative_id and creative_id not in ad["full_text"]:
                ad["full_text"] = (ad["full_text"] + f" [{creative_id}]").strip()
            if len(ad.get("full_text", "")) < 5:
                continue
            ads.append(ad)

            if not is_video:
                tried += 1
                if image_text:
                    success += 1

        # Mutate (don't reassign) – scrape() captured a reference to this dict.
        self._ocr_stats["tried"] = tried
        self._ocr_stats["success"] = success

        logger.info(
            f"[Google] {slug}: OCR fáze – {fresh} nově čteno, {cache_hits} z cache"
            + (f", {budget_hit} bez textu (rozpočet)" if budget_hit else "")
        )
        if budget_hit:
            logger.warning(
                f"[Google] {slug}: OCR rozpočet {self.max_ocr_seconds}s vyčerpán – "
                f"{budget_hit} kreativ ponecháno bez přečteného textu."
            )
        return ads

    # ------------------------------------------------------------------
    # Extract currently visible ad cards
    # ------------------------------------------------------------------

    def _extract_creative_meta(self) -> list[dict]:
        """Phase-1 extractor: creative-preview metadata only (NO OCR)."""
        try:
            return self.page.evaluate("""() => {
                return Array.from(document.querySelectorAll('creative-preview')).map(el => {
                    const link = el.querySelector('a[href*="/creative/"]');
                    const href = link ? link.getAttribute('href') : '';
                    const nameEl = el.querySelector('.advertiser-name');
                    const name = nameEl ? nameEl.innerText.trim() : '';
                    const imgEl = el.querySelector('div.html-container img, html-renderer img');
                    const imgSrc = imgEl ? (imgEl.src || '') : '';
                    // Detect video creative: <video> element or common play-button overlays
                    const isVideo = !!(
                        el.querySelector('video') ||
                        el.querySelector('html-renderer video, div.html-container video') ||
                        el.querySelector('[class*="video-player"],[class*="videoPlayer"]') ||
                        el.querySelector('[class*="play-button"],[class*="playButton"],[class*="PlayButton"]')
                    );
                    const m = href.match(/\\/creative\\/(CR\\w+)/);
                    return {
                        creativeId: m ? m[1] : '',
                        href: href,
                        name: name,
                        imgSrc: imgSrc,
                        isVideo: isVideo,
                    };
                }).filter(c => c.creativeId || c.name);
            }""")
        except Exception as e:
            logger.debug(f"creative-preview meta JS eval failed: {e}")
            return []

    def _ocr_creative(self, creative_id: str, image_src: str = "") -> "str | None":
        """Run Tesseract OCR on a creative. Prefers screenshotting the live DOM
        element (best fidelity); if that element is no longer in the DOM (the
        list virtualised it away after a long scroll), falls back to downloading
        the creative image straight from its URL – no DOM dependency.

        Returns:
          - the cleaned text (str) when OCR ran and found text,
          - "" when OCR ran but the creative is graphics-only (no readable text),
          - None when OCR could not even be attempted (no image / OCR disabled),
            so the caller knows NOT to cache the result and to retry next time.
        """
        if not OCR_AVAILABLE or (not creative_id and not image_src):
            return None
        try:
            pil_img = None

            # 1) Live element screenshot (scroll it back into view if needed).
            if creative_id:
                try:
                    locator = self.page.locator("creative-preview").filter(
                        has=self.page.locator(f'a[href*="{creative_id}"]')
                    ).first
                    if locator.count():
                        try:
                            locator.scroll_into_view_if_needed(timeout=2_000)
                        except Exception:
                            pass
                        png = locator.screenshot(timeout=4_000)
                        pil_img = Image.open(io.BytesIO(png))
                except Exception as e:
                    logger.debug(f"OCR screenshot failed for {creative_id}: {e}")

            # 2) Fallback: fetch the creative image directly by URL.
            if pil_img is None and image_src:
                pil_img = self._fetch_image(image_src)

            if pil_img is None:
                return None

            variants = self._preprocess_ocr_variants(pil_img)  # [light, inverted]
            config = "--psm 6 --oem 1"
            best_text, best_score = "", 0.0

            # Try the light variant first; only spend a second Tesseract pass on
            # the inverted variant if the light read was not already good.
            for variant in variants:
                try:
                    raw = self._ocr_high_confidence(variant, config)
                    score = self._text_quality_score(raw)
                    if score > best_score:
                        best_score, best_text = score, raw
                except Exception:
                    continue
                if best_score >= self.LIGHT_OK_THRESHOLD:
                    break

            if best_score < 0.20:
                logger.debug(
                    f"OCR [{creative_id[:20]}]: zahozeno jako grafika (score={best_score:.2f})"
                )
                return ""

            cleaned = self._clean_ocr_text(best_text)
            logger.debug(
                f"OCR [{creative_id[:20]}] score={best_score:.2f}: {cleaned[:80]!r}"
            )
            return cleaned

        except Exception as e:
            logger.debug(f"OCR failed for {creative_id}: {e}")
            return None

    def _fetch_image(self, url: str) -> "Image.Image | None":
        """Download a creative image via the page's request context (shares
        cookies/session) so OCR does not depend on the element still being in
        the DOM."""
        try:
            resp = self.page.request.get(url, timeout=8_000)
            if not resp.ok:
                logger.debug(f"_fetch_image: HTTP {resp.status} pro {url[:80]}")
                return None
            return Image.open(io.BytesIO(resp.body()))
        except Exception as e:
            logger.debug(f"_fetch_image selhalo pro {url[:80]}: {e}")
            return None

    # ------------------------------------------------------------------
    # OCR helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _preprocess_ocr_variants(pil_img: "Image.Image") -> list:
        """Return upscaled + contrast-enhanced image variants.

        Two variants are returned:
          - v_light: for ads with dark text on light background
          - v_dark:  inverted, for ads with white/light text on dark background
        """
        w, h = pil_img.size
        # Upscale to ~300 dpi equivalent (target shortest side ≥ 600 px)
        scale = max(2, int(600 / max(1, min(w, h))))
        scale = min(scale, 4)  # cap at 4× to avoid huge images
        big = pil_img.resize((w * scale, h * scale), Image.LANCZOS)
        gray = big.convert("L")

        # Boost contrast and sharpen
        enhanced = ImageEnhance.Contrast(gray).enhance(2.5)
        sharpened = enhanced.filter(ImageFilter.SHARPEN)

        # Inverted variant for white-on-dark banner ads
        inverted = ImageOps.invert(sharpened)

        return [sharpened, inverted]

    @staticmethod
    def _ocr_high_confidence(img: "Image.Image", config: str, min_conf: int = 50) -> str:
        """Run Tesseract OCR and return only words where Tesseract confidence ≥ min_conf.

        Uses image_to_data (word-level confidence) instead of image_to_string.
        Words below the confidence threshold are silently dropped, eliminating
        OCR noise from logos, decorative fonts, and complex graphics.
        Falls back to plain image_to_string if image_to_data fails.
        """
        try:
            from pytesseract import Output as TessOutput
            from collections import defaultdict

            data = pytesseract.image_to_data(
                img, lang="ces+eng", config=config, output_type=TessOutput.DICT
            )

            # Group high-confidence words by their logical line
            lines: dict = defaultdict(list)
            for i, (word, conf) in enumerate(zip(data["text"], data["conf"])):
                word = (word or "").strip()
                if not word:
                    continue
                try:
                    conf_int = int(conf)
                except (ValueError, TypeError):
                    continue
                if conf_int >= min_conf:
                    key = (
                        data["block_num"][i],
                        data["par_num"][i],
                        data["line_num"][i],
                    )
                    lines[key].append((data["word_num"][i], word))

            result_lines = [
                " ".join(w for _, w in sorted(words))
                for key, words in sorted(lines.items())
                if words
            ]
            return "\n".join(result_lines)

        except Exception:
            # Fallback to regular OCR if image_to_data is unavailable
            return pytesseract.image_to_string(
                img, lang="ces+eng", config=config
            ).strip()

    @staticmethod
    def _text_quality_score(text: str) -> float:
        """Return fraction of characters belonging to plausible Czech/English words (≥3 chars).

        Score close to 1.0 = mostly real text.
        Score close to 0.0 = mostly noise/graphics artefacts.
        """
        if not text:
            return 0.0
        word_chars = sum(
            len(w)
            for w in re.findall(
                r"[a-záéíóúůčďěňřšťžýA-ZÁÉÍÓÚŮČĎĚŇŘŠŤŽÝ]{3,}",
                text,
            )
        )
        total = len(re.sub(r"\s+", "", text))
        return word_chars / total if total else 0.0

    @staticmethod
    def _clean_ocr_text(text: str) -> str:
        """Remove garbage lines; keep lines with sufficient real word content.

        Rules (applied per line):
          - Drop empty lines and lines with no Czech/English words ≥3 chars.
          - Drop lines containing Google ad-template markers (<Rating>, <Distance>, …).
          - Short lines (≤12 non-space chars):
              keep if ≥2 words ≥3 chars, OR ≥1 word ≥7 chars.
          - Longer lines (>12 non-space chars):
              keep if ≥45 % of non-space chars belong to real words AND ≥2 words.
        """
        WORD_RE = re.compile(r"[a-záéíóúůčďěňřšťžýA-ZÁÉÍÓÚŮČĎĚŇŘŠŤŽÝ]{3,}")
        TEMPLATE_RE = re.compile(r"<[A-Za-z][^>]{0,30}>")  # <Rating>, <Distance>, …

        good = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if TEMPLATE_RE.search(line):          # OCR'd Google template markers
                continue
            words = WORD_RE.findall(line)
            if not words:
                continue

            total_ns = len(re.sub(r"\s+", "", line))
            word_chars = sum(len(w) for w in words)

            if total_ns <= 12:
                # Short line: require ≥2 words OR ≥1 long word (≥7 chars)
                if len(words) >= 2 or any(len(w) >= 7 for w in words):
                    good.append(line)
            else:
                # Longer line: require word density ≥45 % and ≥2 words
                if word_chars / total_ns >= 0.45 and len(words) >= 2:
                    good.append(line)

        return "\n".join(good)

    def _extract_via_js(self) -> list[dict]:
        """Fallback JS-based text extraction for non-creative-preview pages."""
        raw = self.page.evaluate("""() => {
            const CARD_SELECTORS = [
                '[class*="creative-card"]',
                '[class*="creativeCard"]',
                'creative-card',
                'creative-preview',
                '[class*="creative-preview"]',
                'mat-card',
                '[data-creative-preview]',
                '[role="listitem"]',
                '[role="article"]',
                '[class*="ad-preview"]',
                '[class*="creative-container"]',
                '[class*="card"]:not(body):not(header):not(nav)',
            ];

            let cards = [];
            for (const sel of CARD_SELECTORS) {
                const found = Array.from(document.querySelectorAll(sel));
                const valid = found.filter(el => {
                    const t = (el.innerText || '').trim();
                    return t.length > 15;
                });
                if (valid.length > 0) {
                    cards = valid;
                    break;
                }
            }

            if (cards.length === 0) {
                const allDivs = Array.from(document.querySelectorAll('div, li, article'));
                cards = allDivs.filter(el => {
                    if (el.children.length < 1) return false;
                    const t = (el.innerText || '').trim();
                    return t.length > 20 && t.length < 2000 &&
                           !['BODY','MAIN','HEADER','FOOTER','NAV'].includes(el.tagName);
                });
                cards = cards.filter(c => !cards.some(o => o !== c && c.contains(o)));
                cards = cards.slice(0, 200);
            }

            return cards.map(card => {
                const imgEl = card.querySelector('img:not([role="presentation"])');
                const hasImage = imgEl !== null;
                const text = (card.innerText || card.textContent || '').trim();
                const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);

                let headline = '', url = '', description = '';
                const extensions = [];

                if (!hasImage) {
                    headline = lines.find(l => l.length > 2 && l.length < 120) || '';
                    const hIdx = lines.indexOf(headline);
                    const rest = lines.slice(hIdx + 1);
                    url = rest.find(l => /\\.(cz|com|sk|eu|net|org)/i.test(l) && l.length < 100) || '';
                    description = rest.filter(l => l !== url && l.length > 5).join(' ');
                    rest.filter(l => l !== url && l !== description && l.length < 60)
                        .forEach(l => extensions.push(l));
                } else {
                    headline = lines[0] || '';
                    description = lines.slice(1).join(' ');
                }

                const btnEl = card.querySelector('button, [role="button"]');
                const cta = btnEl ? (btnEl.innerText || '').trim() : '';

                return {
                    ad_type: hasImage ? 'banner' : 'text',
                    headline,
                    url,
                    description,
                    cta,
                    extensions,
                    image_alt: hasImage ? (imgEl.alt || imgEl.getAttribute('aria-label') || '') : '',
                    image_src: hasImage ? (imgEl.src || imgEl.getAttribute('data-src') || '') : '',
                    image_text: '',
                    raw_text: text,
                };
            });
        }""")

        if not raw:
            return []

        result = []
        for ad in raw:
            ad = self._normalise(ad)
            if len(ad.get("full_text", "")) < 10:
                continue
            result.append(ad)

        return result

    # ------------------------------------------------------------------
    # Debug helpers
    # ------------------------------------------------------------------

    def _save_debug_html(self, slug: str, platform: str):
        try:
            logs_dir = Path("logs")
            logs_dir.mkdir(exist_ok=True)
            html = self.page.content()
            path = logs_dir / f"debug_{platform}_{slug}.html"
            path.write_text(html, encoding="utf-8")
            screenshot_path = logs_dir / f"debug_{platform}_{slug}.png"
            self.page.screenshot(path=str(screenshot_path), full_page=False)
            logger.warning(
                f"[Google] Žádné reklamy nenalezeny! "
                f"HTML uložen do {path}, screenshot do {screenshot_path}"
            )
        except Exception as e:
            logger.debug(f"Debug dump failed: {e}")

    @staticmethod
    def _normalise(ad: dict) -> dict:
        parts = filter(None, [
            ad.get("headline", ""),
            ad.get("url", ""),
            ad.get("description", ""),
            ad.get("image_alt", ""),
            ad.get("image_text", ""),
            " ".join(ad.get("extensions", [])),
        ])
        ad["full_text"] = " ".join(parts).strip()
        ad.setdefault("platform", "google")
        return ad
