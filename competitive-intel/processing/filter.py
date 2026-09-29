import logging

logger = logging.getLogger(__name__)


class AdFilter:
    def __init__(self, config: dict):
        self.always_skip = [kw.lower() for kw in config.get("always_skip", [])]
        cond = config.get("conditional_skip", {})
        self.conditional_kw = [kw.lower() for kw in cond.get("keywords", [])]
        self.pet_exception = [kw.lower() for kw in cond.get("pet_exception", [])]
        # competitor-specific keywords: {slug: [kw, ...]}
        self.competitor_skip: dict[str, list[str]] = {
            slug: [kw.lower() for kw in kws]
            for slug, kws in config.get("competitor_skip", {}).items()
        }

    def _ad_text(self, ad: dict) -> str:
        return " ".join(filter(None, [
            ad.get("headline", ""),
            ad.get("text", ""),
            ad.get("description", ""),
            ad.get("cta", ""),
            ad.get("image_alt", ""),
            ad.get("image_text", ""),
            " ".join(ad.get("extensions", [])),
            ad.get("raw_text", ""),
        ])).lower()

    def should_skip(self, ad: dict, competitor_slug: str = "") -> bool:
        text = self._ad_text(ad)

        for kw in self.always_skip:
            if kw in text:
                return True

        for kw in self.competitor_skip.get(competitor_slug, []):
            if kw in text:
                return True

        has_pet = any(pw in text for pw in self.pet_exception)
        if not has_pet:
            for kw in self.conditional_kw:
                if kw in text:
                    return True

        return False

    def filter(self, ads: list[dict], competitor_slug: str = "") -> tuple[list[dict], int]:
        kept, skipped = [], 0
        for ad in ads:
            if self.should_skip(ad, competitor_slug):
                skipped += 1
                logger.debug(f"Skipped ad: {ad.get('headline') or ad.get('text', '')[:60]}")
            else:
                kept.append(ad)
        return kept, skipped
