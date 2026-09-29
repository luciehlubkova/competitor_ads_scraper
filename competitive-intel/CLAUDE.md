# Competitive Intelligence Scraper – Handoff

## Co tento nástroj dělá

Každý týden scrapuje Google Ads Transparency Center a Facebook Ad Library pro seznam českých pojišťoven a srovnávačů, porovná výsledky s minulým týdnem a vygeneruje český Markdown report (`reports/report_YYYY-MM-DD.md`). Report následně slouží jako vstup pro generování týdenního HTML reportu v chatu.

> Tento soubor je **trvalá reference**. Datované změny jsou v sekci [Changelog](#changelog) na konci.

---

## ⚠️ Na co dát pozor při příštím běhu

1. **První ostrý běh s novým diffem (creative_id) i novým reporterem proběhl 2026-06-08 – OK.** Diff Googlu se od 2026-06-08 porovnává podle `creative_id`, ne podle OCR textu (viz [Diff a snapshoty](#diff-a-snapshoty)). Report 23 KB, OCR 96 %, bez chyb. Reporter (opravené tabulky, zkrácené „odstraněné") ověřen i živě.
2. **Porovnávej jen proti baseline 2026-06-03 a novějším.** Snapshoty z 2026-05-27 a starší pocházejí ze starší verze scraperu a mají nekonzistentní počty (např. rixo 173 vs. 27 kreativ) → diff proti nim hlásí falešně velké změny. Není to chyba nového kódu.
3. **`creative_id` je stabilní – potvrzeno týdenním během 2026-06-08.** Většina konkurentů měla 0–5 nových Google kreativ a desítky „beze změny" → Google `creative_id` NErotuje týden co týden. Jediná výjimka byla `ergo-cestovni` (40 nových, „0 z cache") = reálný refresh kampaně Erga, ne systémová rotace. Sleduj dál, ale strategie diffu podle `creative_id` je ověřená.
4. **Velikost reportu** by měla být řádově **jednotky až nižší desítky KB** (starý formát měl 283 KB). Pokud je výrazně větší, ověř, že se uplatnilo zkrácení „odstraněných" na počet a že OCR negeneruje balast (filtr OCR garbage zatím **není** nasazený – viz [Backlog](#backlog)).
5. **Spouštěj v popředí** (headed prohlížeč + interaktivní prompt u pomalých konkurentů, viz [Časové rozpočty](#časové-rozpočty)).
6. Standardní kontroly po běhu jsou v [Checklistu](#checklist-po-běhu).

---

## Spuštění

```powershell
Set-Location "C:\Users\lucie.hlubkova\OneDrive - Direct\Dokumenty\AI\Sledování konkurence\Claude code output\competitive-intel"
& "C:\Program Files\Python314\python.exe" main.py                   # všichni konkurenti
& "C:\Program Files\Python314\python.exe" main.py --competitor koop # jen jeden (test)
& "C:\Program Files\Python314\python.exe" main.py --dry-run         # bez uložení snapshotu
```

- Reports: `reports/report_YYYY-MM-DD.md`
- Logy běhu: `logs/run_YYYY-MM-DD.log`

> ⚠️ Předpoklad: **jeden běh týdně**. Diff i snapshoty na to spoléhají (viz [Diff a snapshoty](#diff-a-snapshoty)).

---

## Závislosti & setup (pouze jednou)

```powershell
& "C:\Program Files\Python314\python.exe" -m pip install -r requirements.txt
& "C:\Program Files\Python314\python.exe" -m playwright install chromium
```

### Tesseract OCR

Nainstalováno v `C:\Users\lucie.hlubkova\AppData\Local\Programs\Tesseract-OCR\` (verze 5.5.0, jazyky `ces`+`eng`).
Kód hledá Tesseract na dvou cestách (`scrapers/google_scraper.py`, `_candidates`): `C:\Program Files\Tesseract-OCR\…` a `%LOCALAPPDATA%\Programs\Tesseract-OCR\…`. Při přeinstalaci jinam doplň cestu tam.

---

## Architektura

```
competitive-intel/
├── main.py                    # CLI entrypoint, loop přes konkurenty, měření času
├── config/
│   ├── competitors.yaml       # 23 konkurentů (name, slug, type, priority, google_url, facebook_url)
│   └── exclude_keywords.yaml  # always_skip + conditional_skip(pet_exception) + competitor_skip
├── scrapers/
│   ├── google_scraper.py      # Playwright scraper, 2fázový (discovery + OCR), výběr inzerenta, consent
│   └── facebook_scraper.py    # Playwright scraper, 3 extrakční strategie, consent + login zeď
├── processing/
│   ├── filter.py              # negativní klíčová slova (+ competitor_skip)
│   ├── deduplicator.py        # dedup: creative_id autoritativní, jinak 85% SequenceMatcher
│   └── diff.py                # porovnání s minulým snapshotem (creative_id match, suspicious_empty)
├── reporter.py                # český Markdown report
├── debug_scrape.py            # diagnostika (mimo produkční běh)
├── storage/
│   ├── snapshots/             # JSON snapshoty reklam (90 dní)
│   └── ocr_cache.json         # perzistentní OCR cache creative_id→text (napříč týdny)
├── logs/                      # logy + debug HTML/PNG při problémech
└── reports/                   # výstupní Markdown reporty
```

---

## Klíčové implementační detaily

### Google – výběr správného inzerenta

URL `?domain=koop.cz` přistane na **stránce s výsledky hledání**, ne na profilu inzerenta. `_click_through_to_advertiser(slug, hints)`:

1. Pokud URL už obsahuje `/advertiser/AR…` (pinováno v configu), hledání se přeskočí.
2. Jinak ze stránky výsledků vybere inzerenta, jehož okolní DOM text obsahuje některý **hint**. Porovnání je **bez diakritiky** (NFD + odstranění háčků na obou stranách, JS i Python `_normalize`), takže slug `epojisteni` trefí „ePojištění.cz".
3. Hinty staví `_build_hints(name, slug)` z pole `name` i `slug` (a navíc bez TLD).
4. Když se hint netrefí → **fallback = první odkaz** + WARNING do logu.

**Po scrapu se ověří shoda inzerenta:** z kreativ (`.advertiser-name` → ad `description`) se zjistí jméno inzerenta a porovná s očekávaným. Když nesedí, `advertiser_warning` jde do reportu. **Mismatch ≠ nutně chyba** – u domén může legitimně inzerovat agentura (žádoucí). Ber to jako „ověř", ne „oprav".

**Pinovaní inzerenti varování nehlásí:** když URL obsahuje přímé `/advertiser/AR…`, nastaví se `self._explicitly_pinned = True` a kontrola shody se přeskočí (jen INFO log) – ID z configu je z definice důvěryhodné a značka se může jmenovat jinak než inzerent (např. `povinne-ruceni` → „Suri Insurance Group").

**Domain vs. pinování:** default je `domain=` hledání, **NE** pinování konkrétního `/advertiser/AR…` ID – za značku může reklamy běžet **agentura** a pinování by ji minulo. Pinuj jen problémové případy. Pinovaná URL **musí mít `&preset-date=Last+7+days`**, jinak se rozbije týdenní okno:
```yaml
google_url: "https://adstransparency.google.com/advertiser/AR03360675260440510465?region=CZ&preset-date=Last+7+days"
```
Aktuálně pinováno: `rixo`, `allianz`, `epojisteni` (AR15456379553500364801 = Klik.cz & ePojisteni.cz, sdílí účet s `klik`), `povinne-ruceni` (AR01018163778958655489 = Suri Insurance Group, sdílí účet se `suri`). **U dvojic `epojisteni`↔`klik` a `povinne-ruceni`↔`suri` se Google data záměrně překrývají** (jeden inzerent, dvě značky); FB zůstává oddělený (různá `view_all_page_id`). Agenturní mismatche (uniqa→Basta digital, cpp→Socialsharks, pvzp→Němec & partners, kb→Dentsu) ponechány (domain= preferován).

**Interpretace počtu:** „Google: N reklam" = počet **kreativních variací**, ne kampaní. Google v záhlaví profilu počítá reklamní *jednotky* (Koop „1 reklama"), ale grid renderuje ~40 variací té jednotky (dynamické search reklamy). Scraper sbírá variace → ~40. **40 není strop ani bug** (ověřeno agresivním scrollem; slavia 47). FB nuly (csobpoj, srovnejto, povinne-ruceni, pillow) jsou **reálné** (FB hlásí „Kritériím hledání neodpovídají žádné reklamy").

### OCR pipeline (Google bannery) – 2 fáze + cache

Reklamy jsou obrázky; text se čte přes Tesseract. **Scroll a OCR jsou oddělené fáze s vlastními rozpočty:**

- **Fáze 1 – discovery** (`_scroll_and_collect`, `max_scroll_seconds=240`): scrolluje a sbírá jen **metadata** kreativ (`creative_id`, obrázek, video?) přes `_extract_creative_meta` – **žádné OCR**. Zastaví se na „stale" nebo limitu.
- **Fáze 2 – OCR** (`_ocr_collected`, `max_ocr_seconds=600`): projede kreativy a čte text. Když rozpočet dojde, kreativy **zůstanou v reportu bez textu** + WARNING (počet reklam i diff zůstanou správné – diff je na OCR nezávislý, viz Diff).

**Čtení jedné kreativy** (`_ocr_creative`): 4vrstvý pipeline (3–4× upscale, grayscale, kontrast 2,5×, doostření; confidence filtr `image_to_data` min_conf=50; řádkový filtr). **Short-circuit**: zkusí světlou variantu; invertovanou (druhý průchod) jen když skóre < `LIGHT_OK_THRESHOLD=0.45`. Skóre < 0.20 → `[grafická reklama]`.

- **Screenshot vs. URL:** primárně screenshot živého elementu (`scroll_into_view_if_needed`); když element po scrollu není v DOM, stáhne obrázek z URL (`_fetch_image`). Návrat: text / `""` (grafika bez textu) / `None` (nešlo spustit – necachuje se).
- **Perzistentní cache** `storage/ocr_cache.json` (creative_id→text): načte se při startu, ukládá po **každém** konkurentovi. Cache hit = OCR se nespustí. V ustáleném provozu se OCR čte jen u **nových** kreativ.

**OCR čitelnost v reportu:** počítá se v `_ocr_collected` přes všechny **ne-video** kreativy (`tried`/`success`). `✅` ≥90 %, jinak `⚠️`. Log fáze 2 ukáže `X nově čteno, Y z cache`.

### Facebook Ad Library

Extrakce zkouší **tři strategie v pořadí** (`_extract_ads`), první neprázdná vyhrává:

1. **`[role="article"]`** (`_try_article_selector`) – nejspolehlivější, pokud je FB používá (většinou ne).
2. **date-walkup** (`_try_date_walkup`) – **starý layout**: najdi `<span>` s „Běží od"/„Started running", jdi nahoru po DOM dokud rodič neobsahuje 2+ kotvy → předchozí element = jedna reklama.
3. **library-id walkup** (`_try_library_id_walkup`) – **nový EU-transparency layout**: karty už nezobrazují „Běží od" (datum je pod „Zobrazit podrobnosti"), zato mají „**ID knihovny**"/„Library ID". Walk-up kotví na tento marker.

Obě walk-up strategie sdílejí generický `_walkup_collect(anchor_src)` + `_items_to_ads()`. Datum a video se extrahují stejně bez ohledu na kotvu (v EU layoutu zůstane `start_date` prázdné – nevadí, FB diff `start_date` nepoužívá, `removed` je vždy `[]`). `EU_NOISE_RE` čistí šum nového layoutu.

**Hranice karty ve `findCard`** (walk-up nahoru) se pozná třemi způsoby: (a) předek obsahuje 2+ kotvy = multi-ad kontejner, (b) předek je obří (>12000 zn.), (c) předek obsahuje šum obalu stránky `CHROME_RE` („Knihovna reklam", „© Meta"…). Bod (c) + fallback „při dosažení `body` vrať poslední rozumný předek" jsou **nutné pro stránky s jedinou reklamou** (počet kotev tam nevyskočí na 2).

> ⚠️ **FB „0 reklam":** než to řešíš jako login zeď nebo špatný `view_all_page_id`, zkontroluj `logs/debug_facebook_{slug}.html` – pokud obsahuje „Sponzorováno"/„ID knihovny", reklamy tam **jsou** a jde o chybu extrakce (typicky nový layout, na který kotva nesedí). **Pinování advertiser linku FB neřeší** (to je mechanika Googlu).

- **Detekce login zdi** (`_detect_login_wall`): při přesměrování na přihlášení vrátí `warning` do reportu (místo tichých „0 reklam").

### Filtrování klíčových slov

- `always_skip` – vždy přeskočit (životní, důchodové…).
- `conditional_skip` (zdravotní, úrazové) – přeskočit, POKUD neobsahuje `pet_exception` (psi, kočky, mazlíčci…).
- `competitor_skip` – slova platná jen pro daného konkurenta (např. `kbpojistovna`: Dentsu Media Services, www.kb.cz, kontokorent…).

---

## Consent / cookie dialogy

Oba scrapery po načtení stránky volají `_dismiss_consent` – zavře cookie/consent dialog na hlavní stránce **i ve všech iframech** (Google consent bývá v `consent.google.com` iframu). Bez toho overlay překryje obsah → tiché „0 reklam".

---

## Časové rozpočty

| Scraper | Rozpočet | Význam |
|---------|----------|--------|
| Google  | `max_scroll_seconds=240` | fáze 1 (discovery, scroll bez OCR) |
| Google  | `max_ocr_seconds=600` | fáze 2 (OCR) |
| Facebook| `max_scroll_seconds=360` | čistý scroll (FB nemá OCR) |

Autoritativní hodnoty se nastavují v `main.py` při vytvoření scraperů. Worst case Google ≈ 14 min, +FB ≈ 6 min. Po dokončení každého konkurenta `main.py` zkontroluje celkový čas – pokud > 15 min, zobrazí interaktivní prompt `Pokračovat? [Y/n]`. Proto spouštěj v popředí.

---

## Diff a snapshoty

`processing/diff.py`, `DiffEngine.compare(slug, current, run_date)`:

- **Google match podle `creative_id`** (`_matches`, od 2026-06-08): nová/odstraněná reklama se určuje podle `creative_id`, **ne podle OCR textu**. `creative_id` je stabilní napříč týdny, kdežto OCR text je nedeterministický (stejná kreativa se přečte pokaždé jinak) a jako klíč by působil falešné new/removed. Fuzzy text (85 % SequenceMatcher) se použije už **jen jako fallback**, když `creative_id` chybí.
- **Facebook match podle textu** (fuzzy 85 %): FB kreativy `creative_id` **nemají**, takže tam fuzzy zůstává. FB `removed` je natvrdo `[]` (viz níže).
- **První běh** (žádný snapshot) → vše je „nové".
- **Druhý běh téhož dne**: `_load_latest_snapshot(slug, exclude_date=run_date)` vyloučí dnešní snapshot → porovnává se proti **minulému týdnu**, ne proti vlastnímu dnešnímu zápisu.
- **Google `suspicious_empty`**: když je teď 0 reklam, ale minulý snapshot měl >0 → **nehlásí se jako odstraněné** (chyba scrape ≠ stažení kampaní), `save_snapshot` přenese minulá data, do reportu jde varování „ověřte ručně". (Díky `creative_id` matchi je tento guard po opravě potřeba jen pro úplnou nulu – částečné OCR selhání už diff neovlivní.)
- **Facebook `removed` je vždy `[]`**: FB URL filtruje podle `start_date` ve 7denním okně, takže reklamy z minulého týdne jsou mimo okno a vypadaly by jako „odstraněné" (to je jen posun okna). FB hlásí jen **nově spuštěné** reklamy; FB selhání se řeší přes login-wall warning.
- Snapshoty `storage/snapshots/{slug}_{YYYY-MM-DD}.json`, mazány po 90 dnech.

V reportu: header „První screening" ukazuje **počet** konkurentů poprvé (`ne` / `ano (první běh)` / `částečně – N z M`), u konkrétního konkurenta značka `_(první screening)_`.

### Struktura reportu (reporter.py)

Report má **dvě sekce** a vždy obsahuje **všech 23** inzerentů:

1. **„Konkurenti se změnami (N z M)"** – plný detail. Sem jde konkurent s `new>0` nebo `removed>0` nebo první screening (`_split_results`). Obsahuje:
   - tabulku **Nové reklamy** (Platforma / Typ / Text / CTA / Datum),
   - **Odstraněné reklamy**: u Googlu **jen počtem** (`Google: −N kreativ oproti minulému týdnu.`) – plná tabulka OCR textů jen nafukovala report a u rotujících variací nemá výpovědní hodnotu; FB je stejně vždy `[]`,
   - počet beze změny, OCR čitelnost, případně influencer poznámku.
2. **„Beze změny oproti minulému týdnu (N z M)"** – kompaktní blok pro každého ostatního: `Typ/Priorita`, `Google/Facebook: X reklam (beze změny)`, OCR čitelnost, varování. U `suspicious_empty` hláška „⚠️ scrape prázdný – přeneseno z min. týdne".

**Formátování textu reklam** (`_ad_text_short`): sjednocuje všechny bílé znaky včetně newline na jednu mezeru (newline uvnitř buňky by rozbil Markdown tabulku i převod do HTML), pak ořez na 120 zn. a escapování `|` → `｜`.

Sdílené helpery: `_ocr_display(res)`, `_platform_status(res, diff, platform)`. Aktuální počty z `len(res[platform]["ads"])`.

---

## Detekce video reklam

- **Google:** `<video>` element nebo play-button overlay v `<creative-preview>` → `is_video`, text `[video reklama]`. Videa se neOCRují a nepočítají do OCR čitelnosti.
- **Facebook:** `<video>` element nebo regex `\d:\d{2} / \d:\d{2}` (duration). Duration se nezapisuje do CTA.
- **V reportu:** sloupec **Typ** 🎬 = video, 📷 = statický obrázek.

---

## Dedup

`processing/deduplicator.py`: dva záznamy se **stejným** `creative_id` = duplikát, s **různým** = různé reklamy (fuzzy text se přeskočí). Fuzzy 85 % SequenceMatcher se použije jen když `creative_id` chybí (Facebook). Tím se grafické reklamy bez OCR textu (placeholder `[grafická reklama]`) neslévají do jedné. (Diff používá stejnou logiku – viz [Diff a snapshoty](#diff-a-snapshoty).)

---

## Časté problémy

| Problém | Příčina | Řešení |
|---------|---------|--------|
| Google: 0 reklam | Consent overlay / chybí Tesseract / zastaralé selektory | Mrkni do `logs/` (debug HTML/PNG), spusť `debug_scrape.py google` |
| Google: varování „inzerent neodpovídá očekávanému" | Hint nenašel shodu → fallback (často agentura) | Ověř ručně; pokud špatně, dopinuj přímé `AR…` URL |
| Google: `OCR čitelnost < 90 %` | Změna designu reklam, nebo vyčerpaný OCR rozpočet | Zkontroluj log (`OCR rozpočet vyčerpán`?), screenshoty v `logs/`, případně zvyš `max_ocr_seconds` |
| Google: 0 reklam, ale minulý týden víc | Pravděpodobně chyba scrape | Diff to NEhlásí jako odstraněné; ověř ručně (warning v reportu) |
| Report: skoro vše „nové" každý týden | Google možná rotuje `creative_id` | Ověř na 2 po sobě jdoucích snapshotech; pokud rotují, revidovat klíč diffu (viz pozn. nahoře) |
| Facebook: 0 reklam | Login zeď / nový layout / změna DOM | Mrkni do `logs/debug_facebook_{slug}.html`: „Sponzorováno"/„ID knihovny" = reklamy tam jsou → chyba extrakce. Login zeď hlásí warning. |
| `TimeoutError` | Pomalé připojení / změna UI | Zvyš timeout v `goto()` |
| `UnicodeEncodeError: cp1250` | (vyřešeno) `setup_logging` přepíná stdout na UTF-8 | – |

### Debug skript

```powershell
& "C:\Program Files\Python314\python.exe" debug_scrape.py google
& "C:\Program Files\Python314\python.exe" debug_scrape.py facebook
```

---

## Checklist po běhu

1. `logs/run_YYYY-MM-DD.log`:
   - řádky `[čas]` a `[čas] SOUHRN` → kde se tráví čas,
   - `OCR fáze – … z cache` → jak zabírá cache (časem by mělo přibývat „z cache"),
   - varování o inzerentech (agentura / mismatch) → koho případně dopinovat.
2. `reports/report_YYYY-MM-DD.md` – sekce „Varování", „OCR čitelnost", velikost (mělo by být řádově jednotky–desítky KB).
3. Porovnej počty změn s očekáváním – pokud je „nových" extrémně mnoho, viz pozn. o rotaci `creative_id` nahoře.
4. `storage/ocr_cache.json` vzniká/roste – nechat být, zrychluje další běhy.

---

## Backlog (neimplementováno)

Návrhy z analýzy, které zatím **nejsou** v kódu (detaily v `../navrh-reseni.md`):

- **B3 – filtr OCR garbage**: polorozpadlý OCR text („nich 7 dní X v Reklamy") stále může projít do reportu jako text reklamy. Filtr „vypadá to jako smysluplný text" doporučeno nasadit a kalibrovat až po pár ostrých bězích s novým diffem.
- **B5 – sloupec Datum**: u Googlu vždy „—" → zvážit odstranění; u FB označit jako datum spuštění (může být starší než sledovaný týden).
- **C4/E3 – interpretační poznámky v reportu**: „Google počet = kreativní variace, ne kampaně" + vysvětlení, proč FB nemá „odstraněné".
- **D1 – neinteraktivní režim** (`--no-prompt`/`--headless`): nutné pro plánované spouštění (Task Scheduler / GitHub Actions). Dnes brání headed prohlížeč + interaktivní prompt.
- **E1 – `influencer_notes`**: ověřit, kde se plní (možná mrtvá větev v reporteru).

---

## Changelog

### 2026-06-08 (živý týdenní běh)
- **První ostrý týdenní běh s novým `creative_id` diffem + reporterem.** Všech 23 konkurentů, exit 0, žádné chyby. Report 23 KB, OCR 96 % (886/920). Baseline = snapshoty 06-02/06-03.
- **Potvrzeno: `creative_id` nerotuje** – většina konkurentů 0–5 nových / desítky beze změny. Jediný odlehlík `ergo-cestovni` (40 nových, 0 z cache) = reálný refresh kampaně, ne rotace klíče.
- **Pozorování k ověření:** (a) `kbpojistovna` Google 0 reklam → `suspicious_empty` přeneslo min. týden, ověřit ručně (inzerent = Dentsu); (b) `srovnejto` `domain=srovnejto.cz` přistálo na `Klik.cz & ePojisteni.cz` (AR15456379553500364801) → trojice srovnejto=klik=epojisteni sdílí Google účet (CLAUDE.md dosud dokumentoval jen pár epojisteni↔klik).

### 2026-06-08 (změny kódu)
- **A1 – Google diff podle `creative_id`** (`diff.py`): přidány `_ad_cid` + `_matches`; Google new/removed se počítá podle `creative_id`, ne podle OCR textu. Odstraňuje falešné změny způsobené nedeterministickým OCR. FB beze změny (fuzzy text, nemá `creative_id`). Ověřeno: 06-02↔06-03 (totožné `creative_id`) → 0 změn.
- **B1 – collapse newline v buňkách** (`reporter.py`, `_ad_text_short`): `re.sub(r"\s+", " ", text)` před ořezem → víceřádkový OCR text už nerozbije Markdown/HTML tabulku.
- **A3 – odstraněné Google reklamy jen počtem** (`reporter.py`): místo plné tabulky OCR textů jen `Google: −N kreativ oproti minulému týdnu.`. Report z testovacích dat klesl z 283 KB na ~9 KB.

### 2026-06-02
- **Facebook nový EU-transparency layout** – přidána 3. extrakční strategie `_try_library_id_walkup` (kotva „ID knihovny"), walk-up vyčleněn do `_walkup_collect` + `_items_to_ads()`, přidán `EU_NOISE_RE`. Date-walkup zůstal primární → fungující konkurenti nedotčeni.
- **Single-ad fix** – `findCard` dostal `CHROME_RE` hranici + fallback na `body`. Ověřeno živě: allianz 0→3, top-pojisteni 0→4, pvzp 0→3, maxima 0→1, kbpojistovna 0→1. csobpoj/pillow/povinne-ruceni/srovnejto reálně 0.
- **Report obsahuje VŠECHNY inzerenty** – sekce „Beze změny oproti minulému týdnu" s kompaktním blokem pro každého. Helpery `_ocr_display`, `_platform_status`.
- **Google piny dořešeny** – `epojisteni` → AR15456379553500364801, `povinne-ruceni` → AR01018163778958655489. Přidán flag `_explicitly_pinned`.
- **Ověřena interpretace dat** – Google „N reklam" = kreativní variace; FB nuly reálné.

### 2026-06-01
- Consent/cookie dialogy (Google i FB, vč. iframů) + detekce FB login zdi.
- Guard `suspicious_empty` (Google) + carry-forward snapshotu proti falešnému „removed".
- Dedup podle `creative_id` (grafické reklamy bez OCR se neslévají).
- Diff jen proti jinému dni (`exclude_date`).
- Facebook `removed` = vždy `[]` (posun okna).
- Výběr inzerenta bez diakritiky + name hint + verifikace shody.
- Scroll a OCR odděleny do dvou fází (240 + 600 s).
- Perzistentní OCR cache + short-circuit invertované varianty.
- stdout UTF-8 (konec `UnicodeEncodeError`).
- Měření času `[čas]` (dočasné pro profilaci – až nebude potřeba, přepnout na DEBUG).

### 2026-05-27
- První plně funkční full run všech 23 konkurentů (OCR 100 %, bez chyb).
