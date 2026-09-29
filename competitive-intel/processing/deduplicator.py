from difflib import SequenceMatcher

SIMILARITY_THRESHOLD = 0.85


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def deduplicate(ads: list[dict]) -> list[dict]:
    unique: list[dict] = []
    for ad in ads:
        cid = (ad.get("creative_id") or "").strip()
        text = (ad.get("full_text") or ad.get("raw_text") or "").strip()
        is_dup = False
        for kept in unique:
            kcid = (kept.get("creative_id") or "").strip()
            # Stable creative IDs are authoritative: same ID = duplicate,
            # different IDs = genuinely distinct creatives. Skip fuzzy text
            # matching here, otherwise image-only ads whose text is just the
            # "[grafická reklama]" placeholder collapse into a single entry.
            if cid and kcid:
                if cid == kcid:
                    is_dup = True
                    break
                continue
            ktext = (kept.get("full_text") or kept.get("raw_text") or "").strip()
            if _similarity(text, ktext) >= SIMILARITY_THRESHOLD:
                is_dup = True
                break
        if not is_dup:
            unique.append(ad)
    return unique
