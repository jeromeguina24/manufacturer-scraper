"""Orchestration: scrape a source, dedupe, enrich, sync to HubDB, report."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from manufacturer_scraper.models import Article, normalize_url, utcnow
from manufacturer_scraper.sources.base import BaseSource
from manufacturer_scraper.store import Store

log = logging.getLogger(__name__)


@dataclass
class SourceResult:
    source: str
    found: int = 0
    new: int = 0
    skipped_seen: int = 0
    pushed: int = 0
    failed: int = 0
    dry_run: bool = False
    duration_s: float = 0.0
    error: str | None = None  # set when the whole source could not be scraped
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime = field(default_factory=utcnow)


def run_source(
    source: BaseSource,
    store: Store | None,
    *,
    dry_run: bool = False,
    max_pages: int | None = None,
    limit: int | None = None,
    dry_run_enrich_limit: int = 3,
) -> SourceResult:
    """Scrape one source.

    New articles are enriched and inserted into the store with status 'new';
    the HubDB sync happens once per run, after all sources (see cmd_run /
    sync_articles).

    - dry_run: no store writes, no HubSpot calls; the first few new articles
      are enriched so the output demonstrates what would be synced.
    - limit: cap on new articles stored this run.
    """
    result = SourceResult(source=source.name, dry_run=dry_run)
    started = time.monotonic()

    def is_seen(url: str) -> bool:
        if store is None:
            return False
        return store.has_seen(normalize_url(url))

    enriched_shown = 0
    for raw in source.iter_articles(max_pages=max_pages, is_seen=is_seen):
        result.found += 1
        article = Article(
            manufacturer=raw.manufacturer,
            url=normalize_url(raw.url),
            title=raw.title,
            published=raw.published,
            categories=raw.categories,
            summary=raw.summary,
            image_url=raw.image_url,
            fetched_at=raw.fetched_at,
        )

        if is_seen(article.url):
            result.skipped_seen += 1
            log.debug("SEEN %s | %s", source.name, article.title)
            continue

        result.new += 1
        if dry_run:
            if enriched_shown < dry_run_enrich_limit:
                article = source.enrich(article)
                enriched_shown += 1
            log.info(
                "NEW  %s | %s | %s%s",
                source.manufacturer,
                article.published.date().isoformat() if article.published else "????-??-??",
                article.title,
                " [image]" if article.image_url else "",
            )
            if article.summary:
                log.info("     summary: %s", article.summary[:160])
            if limit is not None and result.new >= limit:
                break
            continue

        enriched = source.enrich(article)
        store.insert_new(enriched)  # type: ignore[union-attr]
        log.info("NEW  %s | %s", source.manufacturer, article.title)
        if limit is not None and result.new >= limit:
            break

    result.duration_s = time.monotonic() - started
    result.finished_at = utcnow()
    return result


def sync_articles(syncer, articles, *, source_label: str = "hubdb-sync") -> SourceResult:
    """Sync a batch of articles to HubDB and report it as one summary row."""
    result = SourceResult(source=source_label)
    started = time.monotonic()
    outcome = syncer.sync_articles(articles)
    result.new = outcome.pushed + outcome.failed
    result.pushed = outcome.pushed
    result.failed = outcome.failed
    result.error = outcome.error
    result.duration_s = time.monotonic() - started
    result.finished_at = utcnow()
    return result


def retry_failed(
    sources_by_manufacturer: dict[str, BaseSource],
    store: Store,
    syncer,
    *,
    limit: int | None = None,
) -> SourceResult:
    """Re-attempt articles with status='failed' (re-enrich + re-sync)."""
    failed = store.failed_articles()
    if limit is not None:
        failed = failed[:limit]

    batch: list[Article] = []
    for article in failed:
        source = sources_by_manufacturer.get(article.manufacturer)
        enriched = article
        if source is not None:
            try:
                enriched = source.enrich(article)
            except Exception as exc:  # noqa: BLE001 - retry with stale enrichment
                log.warning(
                    "Re-enrich failed for %s (%s); retrying with stored data",
                    article.title,
                    exc,
                )
        store.update_enrichment(enriched.url, enriched.summary, enriched.image_url)
        batch.append(enriched)

    result = sync_articles(syncer, batch, source_label="retry-failed")
    result.found = len(failed)
    return result


def print_summary(results: list[SourceResult]) -> None:
    header = f"{'source':<22}{'found':>7}{'new':>6}{'seen':>6}{'pushed':>8}{'failed':>8}{'time':>8}"
    print()
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.source:<22}{r.found:>7}{r.new:>6}{r.skipped_seen:>6}"
            f"{r.pushed:>8}{r.failed:>8}{r.duration_s:>7.1f}s"
        )
    totals = SourceResult(
        source="TOTAL",
        found=sum(r.found for r in results),
        new=sum(r.new for r in results),
        skipped_seen=sum(r.skipped_seen for r in results),
        pushed=sum(r.pushed for r in results),
        failed=sum(r.failed for r in results),
        duration_s=sum(r.duration_s for r in results),
    )
    print("-" * len(header))
    print(
        f"{totals.source:<22}{totals.found:>7}{totals.new:>6}{totals.skipped_seen:>6}"
        f"{totals.pushed:>8}{totals.failed:>8}{totals.duration_s:>7.1f}s"
    )
    errored = [r for r in results if r.error]
    if errored:
        print("\nSource errors (other sources were unaffected):")
        for r in errored:
            print(f"  {r.source}: {r.error}")
    if results and results[0].dry_run:
        print("\n(dry run — nothing was stored or pushed to HubSpot)")
