"""SQLite-backed state store: dedupe, publish status, HubSpot caches, run audit."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from manufacturer_scraper.models import Article

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    url             TEXT PRIMARY KEY,
    manufacturer    TEXT NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT,
    image_url       TEXT,
    published_at    TEXT,
    categories      TEXT,
    status          TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','pushed','failed')),
    hubspot_post_id TEXT,
    hubspot_slug    TEXT,
    error           TEXT,
    first_seen_at   TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS image_cache (
    url               TEXT PRIMARY KEY,
    hubspot_file_id   TEXT,
    hubspot_file_path TEXT,
    imported_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tag_cache (
    name           TEXT PRIMARY KEY COLLATE NOCASE,
    hubspot_tag_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT,
    finished_at  TEXT,
    source       TEXT,
    dry_run      INTEGER,
    found        INTEGER,
    new          INTEGER,
    pushed       INTEGER,
    failed       INTEGER,
    skipped      INTEGER
);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- article lifecycle ---------------------------------------------------

    def has_seen(self, url: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM articles WHERE url = ?", (url,)).fetchone()
        return row is not None

    def status(self, url: str) -> str | None:
        row = self._conn.execute("SELECT status FROM articles WHERE url = ?", (url,)).fetchone()
        return row["status"] if row else None

    def is_pushed(self, url: str) -> bool:
        return self.status(url) == "pushed"

    def insert_new(self, article: Article) -> None:
        now = _now_iso()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO articles
                (url, manufacturer, title, summary, image_url, published_at,
                 categories, status, first_seen_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
            """,
            (
                article.url,
                article.manufacturer,
                article.title,
                article.summary,
                article.image_url,
                article.published.isoformat() if article.published else None,
                json.dumps(list(article.categories)),
                now,
                now,
            ),
        )
        self._conn.commit()

    def mark_pushed(self, url: str, post_id: str, slug: str) -> None:
        self._conn.execute(
            """
            UPDATE articles
               SET status = 'pushed', hubspot_post_id = ?, hubspot_slug = ?,
                   error = NULL, updated_at = ?
             WHERE url = ?
            """,
            (post_id, slug, _now_iso(), url),
        )
        self._conn.commit()

    def mark_failed(self, url: str, error: str) -> None:
        self._conn.execute(
            "UPDATE articles SET status = 'failed', error = ?, updated_at = ? WHERE url = ?",
            (error[:2000], _now_iso(), url),
        )
        self._conn.commit()

    def failed_articles(self) -> list[Article]:
        rows = self._conn.execute(
            "SELECT * FROM articles WHERE status = 'failed' ORDER BY first_seen_at"
        ).fetchall()
        return [self._row_to_article(row) for row in rows]

    def update_enrichment(self, url: str, summary: str | None, image_url: str | None) -> None:
        self._conn.execute(
            "UPDATE articles SET summary = ?, image_url = ?, updated_at = ? WHERE url = ?",
            (summary, image_url, _now_iso(), url),
        )
        self._conn.commit()

    @staticmethod
    def _row_to_article(row: sqlite3.Row) -> Article:
        published = None
        if row["published_at"]:
            try:
                published = datetime.fromisoformat(row["published_at"])
            except ValueError:
                published = None
        categories = tuple(json.loads(row["categories"])) if row["categories"] else ()
        return Article(
            manufacturer=row["manufacturer"],
            url=row["url"],
            title=row["title"],
            published=published,
            categories=categories,
            summary=row["summary"],
            image_url=row["image_url"],
        )

    # -- caches ----------------------------------------------------------------

    def cached_image(self, url: str) -> tuple[str, str] | None:
        row = self._conn.execute(
            "SELECT hubspot_file_id, hubspot_file_path FROM image_cache WHERE url = ?",
            (url,),
        ).fetchone()
        if row is None:
            return None
        return (row["hubspot_file_id"] or "", row["hubspot_file_path"] or "")

    def cache_image(self, url: str, file_id: str, path: str) -> None:
        self._conn.execute(
            """
            INSERT INTO image_cache (url, hubspot_file_id, hubspot_file_path, imported_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                hubspot_file_id = excluded.hubspot_file_id,
                hubspot_file_path = excluded.hubspot_file_path,
                imported_at = excluded.imported_at
            """,
            (url, file_id, path, _now_iso()),
        )
        self._conn.commit()

    def cached_tag(self, name: str) -> str | None:
        row = self._conn.execute(
            "SELECT hubspot_tag_id FROM tag_cache WHERE name = ?", (name,)
        ).fetchone()
        return row["hubspot_tag_id"] if row else None

    def cache_tag(self, name: str, tag_id: str) -> None:
        self._conn.execute(
            """
            INSERT INTO tag_cache (name, hubspot_tag_id) VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET hubspot_tag_id = excluded.hubspot_tag_id
            """,
            (name, tag_id),
        )
        self._conn.commit()

    def clear_tag_cache(self) -> None:
        self._conn.execute("DELETE FROM tag_cache")
        self._conn.commit()

    # -- audit -------------------------------------------------------------------

    def record_run(
        self,
        *,
        started_at: datetime,
        finished_at: datetime,
        source: str,
        dry_run: bool,
        found: int,
        new: int,
        pushed: int,
        failed: int,
        skipped: int,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO runs (started_at, finished_at, source, dry_run,
                              found, new, pushed, failed, skipped)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                started_at.isoformat(timespec="seconds"),
                finished_at.isoformat(timespec="seconds"),
                source,
                int(dry_run),
                found,
                new,
                pushed,
                failed,
                skipped,
            ),
        )
        self._conn.commit()
