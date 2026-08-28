"""Syncs normalized Articles as rows of a HubSpot HubDB table.

Each article becomes one row (title, manufacturer, published date,
announcement type, summary, source URL). Rows are created in the HubDB
*draft* version and published with a single table-level push-live per
scraper run. A HubL page template renders the live table as the public hub.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC

from manufacturer_scraper.config import Settings
from manufacturer_scraper.hubspot.client import HubSpotClient, HubSpotError
from manufacturer_scraper.models import Article, truncate
from manufacturer_scraper.store import Store

log = logging.getLogger(__name__)

TABLE_LABEL = "Manufacturer News"
MAX_TITLE_LEN = 255
MAX_SUMMARY_LEN = 300
META_TABLE_ID = "hubdb_table_id"

HUBDB_COLUMNS = [
    {"name": "title", "label": "Title", "type": "TEXT"},
    {"name": "manufacturer", "label": "Manufacturer", "type": "TEXT"},
    {"name": "published_date", "label": "Published date", "type": "DATE"},
    {"name": "announcement_type", "label": "Announcement type", "type": "TEXT"},
    {"name": "summary", "label": "Summary", "type": "TEXT"},
    {"name": "source_url", "label": "Source URL", "type": "TEXT"},
]
EXPECTED_COLUMNS = tuple(column["name"] for column in HUBDB_COLUMNS)


class SyncError(RuntimeError):
    pass


@dataclass
class SyncOutcome:
    pushed: int = 0
    failed: int = 0
    error: str | None = None


class HubDbSyncer:
    def __init__(self, client: HubSpotClient, store: Store, settings: Settings) -> None:
        self.client = client
        self.store = store
        self.settings = settings
        self.table_name = settings.hubspot.hubdb_table_name

    # -- table ------------------------------------------------------------

    def ensure_table(self) -> str:
        """Return the HubDB table id, adopting or creating the table as needed."""
        cached_id = self.store.meta_get(META_TABLE_ID)
        if cached_id:
            table = self.client.get_hubdb_table(cached_id)
            if table is not None:
                self._validate_columns(table)
                return str(table.get("id") or cached_id)

        table = self.client.get_hubdb_table(self.table_name)
        if table is not None:
            self._validate_columns(table)
            table_id = str(table.get("id", ""))
            if table_id:
                self.store.meta_set(META_TABLE_ID, table_id)
            return table_id

        created = self.client.create_hubdb_table(
            self.table_name, TABLE_LABEL, HUBDB_COLUMNS
        )
        table_id = str(created.get("id", ""))
        if not table_id:
            raise SyncError(f"HubSpot returned no id for the new table: {created}")
        self.store.meta_set(META_TABLE_ID, table_id)
        # Any cached row ids referenced a table that no longer exists.
        self.store.clear_unpushed_row_ids()
        self.client.publish_hubdb_table(table_id)  # push the empty draft live once
        log.info("Created HubDB table %s (%s)", self.table_name, table_id)
        return table_id

    def _validate_columns(self, table: dict) -> None:
        existing = {column.get("name") for column in table.get("columns", [])}
        missing = [name for name in EXPECTED_COLUMNS if name not in existing]
        if missing:
            raise SyncError(
                f"HubDB table {self.table_name!r} is missing columns: "
                f"{', '.join(missing)}. Add them in HubSpot, or delete the "
                "table and re-run setup-hubspot."
            )

    # -- sync ---------------------------------------------------------------

    def sync_articles(self, articles: Sequence[Article]) -> SyncOutcome:
        """Create draft rows for the articles, then publish the table once.

        Rows whose ids are already cached (from an earlier failed attempt) are
        not created again, so retries never duplicate rows.
        """
        if not articles:
            return SyncOutcome()

        try:
            table_id = self.ensure_table()
        except (HubSpotError, SyncError) as exc:
            error = f"HubDB table unavailable: {exc}"
            self._fail_all(articles, error)
            return SyncOutcome(failed=len(articles), error=error)

        for article in articles:
            if self.store.row_id(article.url):
                continue
            try:
                row = self.client.create_hubdb_row(
                    table_id,
                    self._row_values(article),
                    name=truncate(article.title, MAX_TITLE_LEN),
                )
            except HubSpotError as exc:
                # One bad article must not block the rest of the batch.
                self.store.mark_failed(
                    article.url, f"HubDB row creation failed: {exc} {exc.body}"
                )
                log.error("FAIL %s | %s: %s", article.manufacturer, article.title, exc)
                continue
            self.store.set_row_id(article.url, str(row.get("id", "")))

        batch = [a for a in articles if self.store.row_id(a.url)]
        if not batch:
            return SyncOutcome(failed=len(articles), error="all row creations failed")

        try:
            self.client.publish_hubdb_table(table_id)
        except HubSpotError as exc:
            error = f"HubDB push-live failed: {exc} {exc.body}"
            self._fail_all(batch, error)
            return SyncOutcome(failed=len(batch), error=error)

        for article in batch:
            self.store.mark_pushed(article.url, self.store.row_id(article.url) or "")
            log.info("SYNC %s | %s", article.manufacturer, article.title)

        rowless = len(articles) - len(batch)
        if rowless:
            log.warning("%d article(s) failed row creation and can be retried", rowless)
        return SyncOutcome(pushed=len(batch), failed=rowless)

    # -- row building ---------------------------------------------------------

    def _row_values(self, article: Article) -> dict:
        published = article.published or article.fetched_at
        day = published.astimezone(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        announcement_type = next(
            (category.strip() for category in article.categories if category.strip()),
            "News",
        )
        return {
            "title": truncate(article.title, MAX_TITLE_LEN),
            "manufacturer": article.manufacturer,
            "published_date": int(day.timestamp() * 1000),  # ms at UTC midnight
            "announcement_type": announcement_type,
            "summary": truncate(article.summary or article.title, MAX_SUMMARY_LEN),
            "source_url": article.url,
        }

    # -- helpers ------------------------------------------------------------------

    def _fail_all(self, articles: Sequence[Article], error: str) -> None:
        for article in articles:
            self.store.mark_failed(article.url, error)
