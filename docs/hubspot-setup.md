# HubSpot setup guide

The scraper syncs articles into a **HubDB table**; a single **hub page**
renders that table as a filterable news feed (manufacturer / announcement
type / time period). HubDB and the page are set up once; afterwards the
scraper only adds rows.

> **Plan requirement:** HubDB needs **Marketing Hub Professional** or
> **CMS Professional**.

## 1. Create a private app (access token)

1. In HubSpot: **Settings → Integrations → Private Apps → Create private app**.
2. On the **Scopes** tab, grant:
   - `hubdb` — required (table + rows)
3. Copy the access token into `.env`:
   ```
   HUBSPOT_ACCESS_TOKEN=pat-na1-xxxx…xxxx
   ```

## 2. Create the HubDB table

```bash
python -m manufacturer_scraper setup-hubspot
```

This creates the table `manufacturer_news` (or adopts it if it already
exists), publishes it, and prints a ready-to-paste `config.yaml` snippet.

## 3. Create the hub page (one-time, manual)

The page template ships with this repo: `docs/hub-page-template.html`.

1. In HubSpot: **Marketing → Files and Templates → Design Tools**.
2. **File → New file → Custom template**, paste the whole contents of
   `docs/hub-page-template.html`, and save (e.g. as "Manufacturer News Hub").
   (If you prefer your own theme/layout, copy only the section between the
   `HUB START` / `HUB END` markers into an existing page template.)
3. **Marketing → Website → Website Pages → Create page**, choose the
   "Manufacturer News Hub" template, set a name/slug, and **Publish**.
4. Open the page — the filters and cards render straight from the HubDB table.

> The table name the template reads is set at the top of the template
> (`{% set TABLE = 'manufacturer_news' %}`). Keep it in sync with
> `hubdb_table_name` in `config.yaml`.

## 4. Verify

```bash
python -m manufacturer_scraper check-hubspot
```

All lines should report `[OK]`.

## 5. How publishing works now

- Every scraped article becomes **one HubDB row** (title, manufacturer,
  published date, announcement type, summary, source URL).
- Rows are created in the HubDB *draft* version and published with a single
  table-level publish per scraper run — new articles appear on the hub page
  as soon as a run finishes.
- Failed syncs can be retried with `run --retry-failed`; already-created
  rows are never duplicated.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `HUBSPOT_ACCESS_TOKEN is not set` | Create `.env` from `.env.example` and paste the token |
| `401` from the API | Token expired/revoked — regenerate in the private app settings |
| `403` on HubDB calls | Portal lacks a Professional plan, or the private app is missing the `hubdb` scope |
| "table is missing columns" | Add the listed columns in HubSpot, or delete the table and re-run `setup-hubspot` |
| Hub page shows no rows | The table was never published, or `TABLE` in the template doesn't match `hubdb_table_name` |
| Leftover blog posts from earlier experiments | Delete them manually: Marketing → Website → Blog |
