# manufacturer-scraper

Scrapes hardware/software news & updates from printer-manufacturer newsrooms
and publishes them to **HubSpot as CMS blog posts**.

Currently supported manufacturers:

| Manufacturer | Source | Method |
|---|---|---|
| Canon | [cpp.canon/news](https://cpp.canon/news/) | WordPress REST API |
| Fujifilm | [fujifilm.com/fb/en/news](https://www.fujifilm.com/fb/en/news) | HTML + article-page enrichment |
| Kyocera | [europe.kyocera.com/news](https://europe.kyocera.com/news/)* | HTML, filtered to printer categories |
| Konica Minolta | [konicaminolta.com newsroom](https://www.konicaminolta.com/global-en/newsroom/release/index.html) | HTML + article-page enrichment |

\* The client's original URL (`/products/printing-devices/news/index.html`)
now redirects to the homepage; this is the current newsroom location.

Each article is stored/published with: **title, summary, image (when
available), announcement date, category, manufacturer, and the original
article URL** (linkback — every HubSpot post ends with a "Read the full
article on the … website" link, plus `source_url`/`manufacturer` custom
properties where the portal supports them).

## Setup (Windows)

```bash
python -m venv .venv
source .venv/Scripts/activate          # Git Bash; PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env                   # then paste your HubSpot private-app token
```

Configure HubSpot (blog id, author, custom properties) — see
[docs/hubspot-setup.md](docs/hubspot-setup.md):

```bash
python -m manufacturer_scraper setup-hubspot   # prints ids to paste into config.yaml
python -m manufacturer_scraper check-hubspot   # health check
```

## Usage

```bash
# See what would be imported, without touching HubSpot or the local store:
python -m manufacturer_scraper run --dry-run

# One source only, first 2 list pages:
python -m manufacturer_scraper run --source canon --max-pages 2

# Staged rollout: push only 1 new article, then inspect it in HubSpot:
python -m manufacturer_scraper run --source canon --limit 1

# Full backfill (raises the per-run page cap):
python -m manufacturer_scraper run --max-pages 30

# Retry articles that failed to push earlier:
python -m manufacturer_scraper run --retry-failed
```

Every run prints a summary table:

```
source                  found   new  seen  pushed  failed    time
-----------------------------------------------------------------
canon                     100   100     0       0       0    6.2s
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
  records every article ever seen and its publish status. Pushed articles are
  never pushed again; failed ones can be retried with `--retry-failed`.
- **Publishing** — articles become HubSpot blog posts backdated to their
  announcement date. Categories become HubSpot tags (created on demand),
  images are imported into the HubSpot file manager, and the original URL is
  embedded as a linkback. Publishing failures are logged and skipped — they
  never abort the run.

## Configuration

- `config.yaml` — all non-secret settings: blog id/author, post state
  (`PUBLISHED` or `DRAFT`), politeness settings, per-source options.
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
`tests/fixtures/README.md`); HubSpot publishing is tested against mocked HTTP.

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
`--max-pages`); scheduled runs then only pick up new items.

## Legal note

The scraper republishes **titles + short summaries + linkback** only — never
full article text — and keeps request volume low. Confirm with each
manufacturer's terms that this usage is acceptable for your client.
