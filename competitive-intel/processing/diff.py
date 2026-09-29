import json
import logging
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.85


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _ad_key(ad: dict) -> str:
    return (ad.get("full_text") or ad.get("raw_text") or "").strip()


def _ad_cid(ad: dict) -> str:
    return (ad.get("creative_id") or "").strip()


def _find_match(ad: dict, pool: list[dict]) -> bool:
    key = _ad_key(ad)
    return any(_similarity(key, _ad_key(other)) >= SIMILARITY_THRESHOLD for other in pool)


def _matches(ad: dict, pool: list[dict]) -> bool:
    """Match primárně podle creative_id (stabilní napříč týdny), fuzzy text jen
    jako fallback, když creative_id chybí (typicky Facebook). Tím se diff
    odpojí od nedeterministického OCR textu, který jinak působí falešné
    new/removed u téže běžící reklamy."""
    cid = _ad_cid(ad)
    if cid:
        return any(_ad_cid(other) == cid for other in pool)
    return _find_match(ad, pool)


class DiffEngine:
    def __init__(self, snapshot_dir: Path):
        self.snapshot_dir = snapshot_dir

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def compare(
        self, slug: str, current: dict[str, list], run_date: date | None = None
    ) -> dict:
        """
        current = {'google': [...], 'facebook': [...]}
        Returns diff with keys: is_first_run, new, removed, unchanged_count,
        suspicious_empty.

        run_date (today) is excluded from the previous-snapshot lookup so that
        re-running on the same day compares against the prior run, not against
        the snapshot this very run already wrote.
        """
        prev = self._load_latest_snapshot(slug, exclude_date=run_date)

        if prev is None:
            return {
                "is_first_run": True,
                "new": {p: ads for p, ads in current.items()},
                "removed": {"google": [], "facebook": []},
                "unchanged_count": {"google": 0, "facebook": 0},
                "suspicious_empty": {"google": False, "facebook": False},
            }

        new_ads: dict[str, list] = {}
        removed_ads: dict[str, list] = {}
        unchanged: dict[str, int] = {}
        suspicious: dict[str, bool] = {}

        for platform in ("google", "facebook"):
            curr_list = current.get(platform, [])
            prev_list = prev.get(platform, [])

            # Facebook URLs filter by ad START date within a sliding 7-day
            # window, so last week's ads are out of scope by construction and
            # would always look "removed" – that is window movement, not a real
            # takedown. Report only newly-started ads, never removals, and do
            # not treat an empty week as suspicious (genuine + login-wall cases
            # are surfaced via the scraper's own warning).
            if platform == "facebook":
                suspicious[platform] = False
                new_ads[platform] = [
                    a for a in curr_list if not _find_match(a, prev_list)
                ]
                removed_ads[platform] = []
                unchanged[platform] = len(curr_list) - len(new_ads[platform])
                continue

            # Google: a long-running ad appears in consecutive weeks, so removals
            # are meaningful. But guard against a failed/blocked scrape
            # masquerading as a removal: nothing now but ads last week is almost
            # certainly a scrape problem, not the competitor pulling every
            # campaign. Report no change and flag it.
            if not curr_list and prev_list:
                suspicious[platform] = True
                new_ads[platform] = []
                removed_ads[platform] = []
                unchanged[platform] = 0
                continue

            # Match podle creative_id (ne podle OCR textu) – viz _matches.
            suspicious[platform] = False
            new_ads[platform] = [a for a in curr_list if not _matches(a, prev_list)]
            removed_ads[platform] = [a for a in prev_list if not _matches(a, curr_list)]
            unchanged[platform] = len(curr_list) - len(new_ads[platform])

        return {
            "is_first_run": False,
            "new": new_ads,
            "removed": removed_ads,
            "unchanged_count": unchanged,
            "suspicious_empty": suspicious,
        }

    def save_snapshot(
        self,
        slug: str,
        run_date: date,
        ads: dict[str, list],
        diff: dict | None = None,
    ):
        google_ads = ads.get("google", [])
        facebook_ads = ads.get("facebook", [])

        # For platforms flagged as suspiciously empty (failed/blocked scrape),
        # carry forward last week's ads instead of persisting an empty list –
        # otherwise next week's diff would lose the history and the false
        # "everything removed" signal would simply be deferred, not avoided.
        suspicious = (diff or {}).get("suspicious_empty", {})
        if suspicious.get("google") or suspicious.get("facebook"):
            prev = self._load_latest_snapshot(slug, exclude_date=run_date) or {}
            if suspicious.get("google"):
                google_ads = prev.get("google", [])
                logger.warning(
                    f"{slug}: Google scrape prázdný – přenáším minulý snapshot beze změny."
                )
            if suspicious.get("facebook"):
                facebook_ads = prev.get("facebook", [])
                logger.warning(
                    f"{slug}: Facebook scrape prázdný – přenáším minulý snapshot beze změny."
                )

        path = self.snapshot_dir / f"{slug}_{run_date.isoformat()}.json"
        payload = {
            "date": run_date.isoformat(),
            "slug": slug,
            "google": google_ads,
            "facebook": facebook_ads,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Snapshot uložen: {path.name}")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_latest_snapshot(
        self, slug: str, exclude_date: date | None = None
    ) -> dict | None:
        pattern = f"{slug}_*.json"
        candidates = sorted(self.snapshot_dir.glob(pattern), reverse=True)
        if exclude_date is not None:
            stamp = exclude_date.isoformat()
            candidates = [c for c in candidates if c.stem.rsplit("_", 1)[-1] != stamp]
        if not candidates:
            return None
        try:
            data = json.loads(candidates[0].read_text(encoding="utf-8"))
            logger.info(f"Načten snapshot: {candidates[0].name}")
            return data
        except Exception as e:
            logger.warning(f"Chyba při čtení snapshotu {candidates[0].name}: {e}")
            return None
