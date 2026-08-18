# manufacturer-scraper

Scrapes hardware/software news & updates from printer-manufacturer newsrooms
and syncs them into a **HubSpot HubDB table**, rendered by a single
filterable **hub page** (one HubSpot page template, included in `docs/`).

Currently supported manufacturers:

| Manufacturer | Source | Method |
|---|---|---|
| Canon | [cpp.canon/news](https://cpp.canon/news/) | WordPress REST API |
| Fujifilm | [fujifilm.com/fb/en/news](https://www.fujifilm.com/fb/en/news) | HTML + article-page enrichment |
| Kyocera | [europe.kyocera.com/news](https://europe.kyocera.com/news/)* | HTML, filtered to printer categories |
| Konica Minolta | [konicaminolta.com newsroom](https://www.konicaminolta.com/global-en/newsroom/release/index.html) | HTML + article-page enrichment |

\* The client's original URL (`/products/printing-devices/news/index.html`)
now redirects to the homepage; this is the current newsroom location.

Each article is synced with: **title, manufacturer, announcement date,
announcement type (category), short summary, and the original article URL** —
the hub page shows all of these as cards, and the
"Read more" button opens the original article on the manufacturer's site.
Visitors can filter the feed by manufacturer, announcement type, and time
period (last 30/90 days, this year, all time).

## Setup (Windows)

```bash
python -m venv .venv
source .venv/Scripts/activate          # Git Bash; PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env                   # then paste your HubSpot private-app token
```

Configure HubSpot (HubDB table + one-time hub page) — see
[docs/hubspot-setup.md](docs/hubspot-setup.md):

```bash
python -m manufacturer_scraper setup-hubspot   # creates/adopts the HubDB table
python -m manufacturer_scraper check-hubspot   # health check
```

> HubDB requires **Marketing Hub Professional** or **CMS Professional**.

## Usage

```bash
# See what would be imported, without touching HubSpot or the local store:
python -m manufacturer_scraper run --dry-run

# One source only, first 2 list pages:
python -m manufacturer_scraper run --source canon --max-pages 2

# Staged rollout: sync only 1 new article, then inspect it in HubSpot:
python -m manufacturer_scraper run --source canon --limit 1

# Full backfill (raises the per-run page cap):
python -m manufacturer_scraper run --max-pages 30

# Retry articles that failed to sync earlier:
python -m manufacturer_scraper run --retry-failed
```

Every run prints a summary table:

```
source                  found   new  seen  pushed  failed    time
-----------------------------------------------------------------
canon                     100   100     0       0       0    6.2s
hubdb-sync                  0   100     0     100       0    2.1s
...
```

## How it works

- **Scraping** — each manufacturer is a module in
  `manufacturer_scraper/sources/` implementing one interface
  (`iter_articles` for list pages, `enrich` for detail pages). List pages are
  fetched newest-first and pagination stops as soon as a full page consists of
  already-seen articles. Requests are polite: browser User-Agent, ~1.5 s
  delay with jitter, retries with backoff on 429/5xx.
- **Kyocera scope** — Kyocera's Europe newsroom covers all divisions; only
  items tagged `Printers / Multifunctionals` or `Printing Devices` are
  imported (configurable under `sources.kyocera.include_categories`).
- **Dedupe/state** — a local SQLite database (`scraper_state.db`, gitignored)
  records every article ever seen and its sync status. Synced articles are
  never synced again; failed ones can be retried with `--retry-failed`.
- **Publishing** — after all sources are scraped, new articles are written as
  **rows of the HubDB table** and published with a single table-level publish
  per run. The hub page (`docs/hub-page-template.html`) renders the live
  table with manufacturer / type / time-period filters and links each card to
  the original article. Sync failures are logged and retried later — they
  never abort the run.

## Configuration

- `config.yaml` — all non-secret settings: HubDB table name, politeness
  settings, per-source options.
- `.env` — `HUBSPOT_ACCESS_TOKEN` only (gitignored).

## Adding a new manufacturer

1. Create `manufacturer_scraper/sources/<name>.py` subclassing
   `BaseSource` (`sources/base.py`): implement `iter_articles()` and, if the
   list page lacks summary/image, `enrich()`.
2. Register the class in `manufacturer_scraper/sources/__init__.py`
   (`ALL_SOURCES`).
3. Add a `sources.<name>:` block to `config.yaml`.
4. Capture a fixture of the list page into `tests/fixtures/` and add parser
   tests (see `tests/test_canon.py` et al.).

## Tests

```bash
pytest -q
```

Parser tests run against real pages captured from the live sites (see
`tests/fixtures/README.md`); HubSpot syncing is tested against mocked HTTP.

## Scheduling

**Windows Task Scheduler** — use the `run.bat` wrapper (it switches to the
repo directory so relative paths resolve):

```bat
schtasks /Create /TN "ManufacturerScraper" /SC DAILY /ST 06:30 ^
  /TR "C:\Users\JJTG\Documents\GitHub\manufacturer-scraper\run.bat"
```

**cron** (if hosted elsewhere):

```
30 6 * * * cd /opt/manufacturer-scraper && .venv/bin/python -m manufacturer_scraper run >> logs/run.log 2>&1
```

The first run backfills history (subject to `scraping.max_pages` /
`--max-pages`); scheduled runs then only pick up new items. Don't run two
instances concurrently — they could create duplicate HubDB rows.

By default `scraping.min_year: current` limits the import to articles
published this year, so adding a source with a deep archive doesn't flood
HubDB with years of back-catalog. Set a fixed year to reach further back,
or remove the option to import everything. Articles without a published
date are always imported. A source block can override the global value —
e.g. `sources.predictive_insight.min_year: null` disables the filter for
that one (small) archive.

## Legal note

The scraper republishes **titles + short summaries + a link to the original
article** only — never full article text — and keeps request volume low.
Confirm with each manufacturer's terms that this usage is acceptable for your
client.
