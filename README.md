# Competitor Ads Scraper

Nástroj pro týdenní monitoring reklamní aktivity konkurence na českém pojišťovacím trhu.
Každý týden scrapuje **Google Ads Transparency Center** a **Facebook Ad Library** pro
seznam českých pojišťoven a srovnávačů, porovná výsledky s minulým týdnem a vygeneruje
český Markdown report. Ten pak slouží jako vstup pro tvorbu čtivého HTML reportu.

Projekt má dvě části:

1. **`competitive-intel/`** – samotný scraper (Python + Playwright + Tesseract OCR),
   který produkuje `reports/report_YYYY-MM-DD.md`.
2. **`SKILL.md`** – navazující skill `monitoring-konkurence`, který z Markdown reportu
   vytvoří strukturovanou strategickou analýzu v HTML.

---

## Jak to funguje

```
Google Ads Transparency Center  ┐
                                ├─►  competitive-intel  ─►  report_YYYY-MM-DD.md  ─►  skill (SKILL.md)  ─►  HTML report
Facebook Ad Library             ┘        (scraper)              (Markdown)              (analýza)            (výstup)
```

- **Scraping** – Playwright ovládá prohlížeč, obchází consent/cookie dialogy a sbírá
  reklamy. U Google bannerů (obrázky bez textu) běží **OCR** přes Tesseract.
- **Zpracování** – filtrování nepojistných produktů a šumu, deduplikace kreativ
  (Google podle `creative_id`, Facebook fuzzy podle textu) a diff proti snapshotu
  z minulého týdne.
- **Report** – český Markdown se sekcemi „Konkurenti se změnami" a „Beze změny", plus
  volitelná sekce „Naše komunikace" s vlastní aktivitou Directu jako referencí.

Podrobná architektura, implementační detaily a changelog jsou v
[`competitive-intel/CLAUDE.md`](competitive-intel/CLAUDE.md).

---

## Struktura repozitáře

```
competitor_ads_scraper/
├── competitive-intel/          # scraper
│   ├── main.py                 # CLI entrypoint, smyčka přes konkurenty
│   ├── config/
│   │   ├── competitors.yaml    # sledovaní inzerenti (+ vlastní brand)
│   │   └── exclude_keywords.yaml
│   ├── scrapers/               # google_scraper.py, facebook_scraper.py
│   ├── processing/             # filter.py, deduplicator.py, diff.py
│   ├── reporter.py             # generátor Markdown reportu
│   ├── debug_scrape.py         # diagnostika
│   ├── requirements.txt
│   ├── run_scraper.bat         # spouštěč (Windows)
│   ├── setup_scheduler.ps1     # nastavení plánovače (Windows)
│   └── CLAUDE.md               # referenční dokumentace nástroje
├── SKILL.md                    # navazující skill pro HTML report
├── .gitignore
└── README.md
```

> Složky `storage/` (snapshoty a OCR cache), `logs/` a `reports/` vznikají za běhu
> a jsou v `.gitignore` – do repa se necommitují.

---

## Instalace

Vyžaduje **Python 3.14** (nebo kompatibilní).

```bash
pip install -r competitive-intel/requirements.txt
python -m playwright install chromium
```

**Tesseract OCR** je nutný pro čtení textu z Google bannerů (jazyky `ces` + `eng`):

- Windows: <https://github.com/UB-Mannheim/tesseract/wiki> – při instalaci vyber
  češtinu a angličtinu a přidej cestu k `tesseract.exe` do PATH.

Scraper hledá Tesseract v `C:\Program Files\Tesseract-OCR\` a
`%LOCALAPPDATA%\Programs\Tesseract-OCR\`. Při instalaci jinam doplň cestu v
`scrapers/google_scraper.py` (`_candidates`).

---

## Spuštění

```bash
cd competitive-intel
python main.py                    # všichni konkurenti
python main.py --competitor koop  # jen jeden (test)
python main.py --dry-run          # bez uložení snapshotu
```

- Report: `competitive-intel/reports/report_YYYY-MM-DD.md`
- Log běhu: `competitive-intel/logs/run_YYYY-MM-DD.log`

Na Windows lze místo příkazu spustit `competitive-intel/run_scraper.bat`.

> ⚠️ Předpoklad je **jeden běh týdně** – diff i snapshoty na tom spoléhají.
> Doporučuje se spouštět v popředí (headed prohlížeč + interaktivní prompt u
> pomalých konkurentů). Detaily viz `CLAUDE.md`.

---

## Tvorba HTML reportu

Vygenerovaný Markdown report je vstupem pro skill `monitoring-konkurence`
(`SKILL.md`), který z něj sestaví strategickou analýzu a vyplní pevnou HTML šablonu.
Skill filtruje nepojistné produkty a šum, interpretuje aktivitu inzerentů a řeší
strukturu výstupních sekcí. Šablona (`assets/`) a popis sekcí (`references/`) nejsou
součástí tohoto repa – žijí u skillu.
