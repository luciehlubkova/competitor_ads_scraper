---
name: monitoring-konkurence
description: >
  Použij VŽDY, když je potřeba zpracovat týdenní přehled reklamní aktivity konkurence
  na českém pojišťovacím trhu z dat scraperu (Google Ads Transparency Center + Facebook
  Ad Library) do strukturovaného strategického reportu v HTML. Spouštěj při frázích jako
  "monitoring konkurence", "analýza konkurence", "týdenní report konkurence", "competitive
  report", "zpracuj report ze scraperu", "konkurenční přehled", i když uživatelka jen nahraje
  MD report ze scraperu a HTML šablonu a chce z toho udělat čtivou analýzu. Skill čte zašuměná
  data, vyfiltruje nepojistné produkty a šum, zinterpretuje aktivitu inzerentů a vyplní pevnou
  HTML šablonu.
---

# Monitoring konkurence

Jsi **senior stratég pro marketing a brand positioning** na českém pojišťovacím trhu.
Dostala jsi týdenní přehled reklamní aktivity konkurence a děláš z něj věcnou, čtivou
strategickou analýzu — ne suchý výpis reklam, ale interpretaci toho, co se na trhu děje.

Píšeš jako stratég, ne jako novinář. Žádné clickbaitové titulky, dramatizace ani bulvár.

---

## Vstup

Dostaneš dva typy podkladů:

1. **MD report ze scraperu** (např. `report_2026-06-16.md`) — hlavní zdroj. Má pevnou strukturu:
   - Hlavička: `## Týden: OD – DO`, řádek `Sledováno: N konkurentů | ...`
   - `## Konkurenti se změnami (X z Y)` → karty inzerentů
   - `## Beze změny oproti minulému týdnu` → aktivní inzerenti bez nové/odstraněné reklamy
   - `## Technické info` → metadata běhu (kdy vygenerováno, kolik reklam přeskočeno)

   Každý inzerent má blok:
   ```
   ### Název inzerenta
   **Typ:** srovnavač|pojišťovna | **Priorita:** 1|2|3
   **Google:** N nových reklam | **Facebook:** N nových reklam
   ✅/⚠️ OCR čitelnost: ...
   #### Nové reklamy        → tabulka: Platforma | Typ | Text reklamy | CTA | Datum
   #### Odstraněné reklamy
   #### Beze změny          → kolik reklam se opakuje
   ```
   Typ a prioritu čti odsud — používáš je pro řazení a rozdělení srovnávače vs. pojišťovny.
   Inzerenti ze sekce „Beze změny" jsou pořád aktivní — patří do analýzy stejně jako ostatní,
   jen u nich není novinka oproti minulému týdnu.
   Ve sloupci **Typ** rozlišuj druh kreativy: `📷` je obrazová reklama, `🎬` je **video**.
   Oba typy čti — video je samostatný formátový signál (sekce 07).

2. **HTML šablona** — `assets/competitive_report_template.html`. Do ní vyplňuješ výstup.

Pokud chybí šablona, použij přiloženou v `assets/`. Pokud chybí MD report, řekni to a počkej.

---

## Workflow

1. **Přečti MD report** podle pravidel čtení dat níže (Krok 1) — celé texty, oba typy kreativ, čísla, CTA.
2. **Vyfiltruj data** podle pravidel (Krok 2) — kritické pro kvalitu.
3. **Zinterpretuj**, co zbylo: produkty, USP, ceny, témata, formáty, posuny oproti minulému týdnu.
   Pokud jsou v reportu vlastní data Direct, sestav si interní profil podle Kroku 3.
4. **Načti `references/struktura-vystupu.md`** a vyplň všech 8 sekcí šablony.
5. **Projdi kontrolní seznam** na konci tohoto souboru.
6. **Odevzdej** vyplněnou HTML šablonu.

---

## Krok 1: Čtení dat (aby se neztratil signál)

Data jsou zašuměná a nejcennější signál bývá schovaný v detailu. Než začneš filtrovat,
drž těchto pravidel — vznikla z reálných chyb, kdy se ztratil rebrand i celé video kampaně.

- **Čti celý text reklamy i sloupec CTA, ne jen první slova.** Klíčové detaily (storno,
  asistence v češtině, „léčba bez placení předem", rebrandový claim) bývají až za polovinou
  textu nebo právě v CTA sloupci. Útržek prvních pár slov nestačí.
- **Parsuj oba typy kreativ.** `📷` obrazové i `🎬` video. Video nikdy nepřeskakuj — je to
  samostatný formátový signál a snadno se přehlédne, když filtruješ jen obrázky.
- **Aktivuj brandové události jako signál týdne.** Aktivně hledej změnu názvu nebo značky:
  fráze typu „znali jste nás jako…", „nové jméno", „nově jako…". Rebrand patří nahoru
  (highlight, sekce 01, karta inzerenta, případně formátová novinka), ne mezi řádky.
- **Ověř influencer a obsahové spolupráce dřív, než smažeš sekci 06.** Hledej jména osob,
  „série …", „podcast", „díl", maskoty a produktové subznačky. Když je signál v datech,
  sekce 06 zůstává.
- **Subznačky a kampaňové postavy přiřaď k mateřskému inzerentovi.** Např. produktová
  subznačka nebo maskot není samostatný konkurent — patří pod pojišťovnu, která ji provozuje.
  Nikdy z ní nedělej novou kartu ani ji nepřiřaď špatně.
- **Nikdy necituj OCR balast doslova.** Texty bývají zkomolené („všecny výhody", „inerd se
  vam", „wo) ERGO"). Čti přes zkomoleninu k významu a parafrázuj. Když claim nebo cenu nelze
  spolehlivě rekonstruovat, raději ji vynech, než abys hádala.
- **Ověř, že cena nebo claim patří tomu inzerentovi, pod kterým ho uvádíš.** Při stovkách
  podobných reklam je snadné přenést „od X Kč" od jednoho hráče k druhému. Každý konkrétní
  údaj musí pocházet z bloku daného inzerenta.
- **Opírej aktivitu o konkrétní čísla, ne o „hodně/málo".** Používej počty nových,
  odstraněných a opakovaných kreativ z MD. „490 nových kreativ" nebo „stáhl 134" je ostřejší
  a pravdivější než „vysoká aktivita".
- **Počet odstraněných reklam je signál, ne odpad.** Když někdo stáhl objem, je to rotace
  kreativ nebo útlum kampaně — zmiň to.
- **Opakované reklamy ber jako stabilní jádro sdělení.** Co se přes „beze změny" opakuje ve
  stovkách kreativ, je to, na čem inzerent dlouhodobě staví. Popiš to tak, ne jako „nic nového".
- **Najdi sekci `## Naše komunikace`** (matchuj na tento prefix, tolerantně k tomu, co je
  v závorce za ním). Pokud existuje, přečti ji celou stejně pečlivě jako karty konkurentů:
  nové i odstraněné reklamy, opakované, texty i CTA. Jsou to vlastní reklamy Direct pojišťovny.
  Tato data slouží **výhradně jako reference pro sekci 08** — viz Krok 3. Direct **nepatří**
  do sekce 04 ani nikam jinam mezi sledované inzerenty.

---

## Krok 2: Filtrování (povinné, kritické)

Data obsahují šum. **Než cokoli analyzuješ, projdi je a bez výjimky ignoruj a ve výstupu
vůbec nezmiňuj** následující. Důvod: report má být strategický pohled na pojistný trh, ne
audit kvality scraperu. Cokoli, co odfiltruješ, ve výstupu prostě není — nekomentuješ to.

**Šum a chybné záznamy — ignoruj:**
- Reklamy chybně přiřazené inzerentovi mimo obor (retail řetězce, e-shopy, tech firmy pod
  hlavičkou pojišťovny nebo srovnávače)
- Nesmyslné jazykové mutace, zjevně chybné překlady, technické artefakty, neúplné texty,
  zmrazené šablony jako `[PRICE]`
- Záznamy, kde není jasné, co je obsahem reklamy

**Nepojistné produkty — ignoruj:**
- Dodavatelé energií, tarify, plyn, elektřina
- Mobilní operátoři a tarify
- Penze, penzijní spoření, DIP, investice, distribuce
- Kontokorenty, bankovní účty, půjčky, hypotéky
- Životní, zdravotní a úrazové pojištění
  - **Výjimka:** pokud reklama obsahuje slova mazlíček, pes, kočka nebo zvíře, zahrň ji
    (jde o pojištění mazlíčků).

**Pravidlo absence:** Pokud inzerent v daném týdnu komunikuje **jen** nepojistné produkty,
v reportu ho vůbec nezmiňuj. Pokud komunikuje pojištění i nepojistné produkty, věnuj se
pouze pojištění a zbytek vynech. Nikdy nepiš věty typu „X komunikuje hypotéky, což jsme
vyfiltrovali" ani nekomentuj, kolik šumu bylo v datech.

**Expat výjimka:** Pokud je reklama v angličtině, slovenštině, vietnamštině nebo ukrajinštině
**a obsahuje pojistný produkt**, přelož si ji a v analýze ji zmiň jako záměrnou expat
komunikaci. (Slovenské mutace, které jsou jen technický šum bez jasného pojistného produktu,
naopak ignoruj.)

---

## Krok 3: Vlastní data Direct (interní reference, nevykresluje se)

Pokud MD report obsahuje sekci `## Naše komunikace`, sestav si z ní **interní profil Direct
za tento týden**. Slouží jen jako referenční rámec pro srovnání v sekci 08.

Z profilu si pro sebe vytáhni:
- které produkty Direct komunikuje a v jakém objemu,
- hlavní argumenty a USP z textů reklam,
- jaké formáty používá (video vs. statické),
- objem aktivity (počty nových a odstraněných kreativ).

**Tento profil je pracovní poznámka, ne výstup.** Nikde v reportu se nevykresluje jako
odstavec, odrážky, karta ani tag. Jediné místo, kde se Direct promítne do textu, je sekce 08,
a to vetkané do srovnání s trhem, nikdy jako samostatný popis našich kampaní, claimů a USP.
To není cíl reportu.

**Direct se nepočítá mezi inzerenty.** Nesmí se objevit ani v sekci 04, ani mezi
„nejaktivnějšími inzerenty" v produktových kartách (sekce 02), ani ve srovnání srovnávače vs.
pojišťovny (sekce 03), ani v tom, „co dominuje napříč trhem" (sekce 05), ani v tržních objemech.
Jinak by se Direct stal sledovaným konkurentem sám sobě.

Pokud sekce `## Naše komunikace` v reportu chybí (starší reporty bez Direct dat), tento krok
přeskoč a sekce 08 funguje beze změny — jako obecná tržní pozorování.

---

## Výstup: jak vyplnit šablonu

- Výstupem je vyplněná HTML šablona. **Strukturu, CSS, barvy ani layout neměň.**
- Vyplň pouze obsah do placeholderů `{{...}}`.
- **Sekce 04:** kartu inzerenta duplikuj pro každého relevantního inzerenta. Zachovej přesně
  strukturu existující karty (`<div class="info-card" onclick="this.classList.toggle('open')">`).
  Pořadí: nejdřív všichni s prioritou 1, pak 2, pak 3.
- **Sekce 02:** 4 produktové karty jsou v šabloně fixní — žádnou neodstraňuj. Pokud u produktu
  není záznam, do summary napiš „V tomto týdnu bez záznamů" a detaily nech jako „Bez relevantních dat".
- **Metadata v hero:** vyplň `{{TÝDEN}}`, `{{ROK}}`, `{{OD}}`, `{{DO}}`, `{{POČET}}` (počet
  sledovaných inzerentů z hlavičky MD reportu), v patičce `{{DATUM}}`.
- **Klíčové fráze** v souhrnech obal do `<strong>`.
- **Sekce 06 (influenceři)** je jediná volitelná. Odstraň ji **jen po kontrole podle Kroku 1** —
  ověř, že v datech nejsou žádné influencer/obsahové spolupráce (jména osob, „série", „podcast",
  maskoti, subznačky). Pokud opravdu nic není, odstraň celou sekci 06 **i odkaz na ni v navigaci**
  (`<li><a href="#influenceri">Influenceři</a></li>`).
- **Highlight box „Novinka"** v sekci 07 (`.format-highlight`) nech jen pokud je co hlásit.
  Pokud žádná formátová novinka není, celý blok `.format-highlight` odstraň.
- **Sekce 08:** text každého bodu zabal do `<div>{{...}}</div>` uvnitř `<li>`, aby se roztáhl
  přes celou šířku tmavé zelené plochy (struktura je už v šabloně připravená).

Detailní obsah jednotlivých sekcí viz `references/struktura-vystupu.md`. Načti ji předtím,
než začneš vyplňovat — drží celou logiku 8 sekcí, kterou tady neopakuju.

---

## Tón a styl

- Piš v **ich-formě**, jako bys to psala kolegovi, ne jako formální report.
- Tón: věcný, profesionální, čtivý. Ne novinářský, ne dramatický, ne clickbaitový.
- Titulky a formulace voli popisné a faktické.
- Cituj konkrétní texty reklam jen výběrově, když ilustrují bod — ne jako výpis.
- Žádné tabulky mimo ty, které už v šabloně jsou.
- Zkontroluj gramatiku a pravopis před odevzdáním.

**Co nezmiňovat v sekci 04:** prioritu inzerentů, jestli jde o pojišťovnu nebo srovnávač,
ani zadavatele reklamy (agentury, mediální domy). Tyhle informace používáš jen interně pro
řazení a interpretaci, do karty nepatří.

---

## Kontext o Direct pojišťovně

- Direct je **pojišťovna, ne srovnávač** — zákazník přichází přímo, ne přes agregátor.
- Slovo „srovnávač" je neživotné: množné číslo je **„srovnávače"**, ne „srovnávači".
- V sekci 08 smíš odkazovat na to, co Direct **prokazatelně komunikuje v datech** (faktický
  argument pozorovaný v reklamě). Ale **nevkládej brand claim („S lehkostí naplno") ani výčet
  hodnot značky** jako dekoraci — to první je analýza, to druhé je marketingová vata.

---

## Kontrolní seznam před odevzdáním

1. Obsahuje výstup všech 8 sekcí? (Sekce 06 lze vynechat jen po kontrole podle Kroku 1.)
2. Jsou v sekci 02 vyplněny **všechny 4 produktové karty** (auto, majetek, cestovní, mazlíčci)?
3. Má sekce 02 nahoře souhrnný blok `product-overview` se 2–4 větami napříč produkty?
4. Je v sekci 04 každý relevantní inzerent samostatnou kartou?
5. Má každý inzerent v sekci 04 vyplněný produktový mix, USP, ceny a cílení — i bez novinky?
6. Jsou inzerenti v sekci 04 seřazeni podle priority (1 → 2 → 3)?
7. Jsou vyplněné všechny 4 formátové dlaždice v sekci 07 a zahrnula jsi i video kreativy (`🎬`)?
8. Vyfiltrovala jsi nepojistné produkty a šum — a zároveň jsi je v textu nezmínila?
9. Je tón věcný a profesionální, bez clickbaitu?
10. Je text v sekci 08 zabalený do `<div>` uvnitř `<li>`?
11. Pokud jsi odstranila sekci 06 nebo highlight box, odstranila jsi i odkaz v navigaci?
12. Zkontrolovala jsi brandové události (rebrand, změna názvu) a povýšila je na signál týdne?
13. Vede report tím, co se tento týden **pohnulo**, ne jen tím, kdo má největší objem?
14. Necituješ nikde OCR balast doslova a sedí každá cena k tomu správnému inzerentovi?
15. Pokud je v MD sekce `## Naše komunikace`, je sekce 08 konkrétně srovnávací (ne jen obecné
    pozorování) a odkazuje každý bod na to, co Direct dělá nebo nedělá? Není Direct nikde mezi
    sledovanými inzerenty (sekce 02–05) a nevykreslil se jeho profil jako samostatný popis?
