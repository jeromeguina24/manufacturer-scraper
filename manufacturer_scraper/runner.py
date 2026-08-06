"""Orchestration: scrape a source, dedupe, enrich, publish, report."""

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
    publisher,  # HubSpotPublisher | None
    *,
    dry_run: bool = False,
    max_pages: int | None = None,
    limit: int | None = None,
    dry_run_enrich_limit: int = 3,
) -> SourceResult:
    """Scrape one source.

    - dry_run: no store writes, no HubSpot calls; the first few new articles
      are enriched so the output demonstrates what would be pushed.
    - limit: cap on new articles processed (enrich + publish) this run.
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

        if limit is not None and result.pushed + result.failed >= limit:
            break

        enriched = source.enrich(article)
        store.insert_new(enriched)  # type: ignore[union-attr]
        try:
            post_id, slug = publisher.publish(enriched)
        except Exception as exc:  # noqa: BLE001 - one bad article must not kill the run
            result.failed += 1
            store.mark_failed(article.url, str(exc))  # type: ignore[union-attr]
            log.error("FAIL %s | %s: %s", source.manufacturer, article.title, exc)
            continue

        result.pushed += 1
        store.mark_pushed(article.url, post_id, slug)  # type: ignore[union-attr]
        log.info(
            "PUSH %s | post %s | %s", source.manufacturer, post_id, article.title
        )

    result.duration_s = time.monotonic() - started
    result.finished_at = utcnow()
    return result


def retry_failed(
    sources_by_manufacturer: dict[str, BaseSource],
    store: Store,
    publisher,
    *,
    limit: int | None = None,
) -> SourceResult:
    """Re-attempt articles with status='failed' (re-enrich + re-publish)."""
    result = SourceResult(source="retry-failed")
    started = time.monotonic()
    for article in store.failed_articles():
        result.found += 1
        if limit is not None and result.pushed + result.failed >= limit:
            break
        source = sources_by_manufacturer.get(article.manufacturer)
        enriched = source.enrich(article) if source else article
        store.update_enrichment(enriched.url, enriched.summary, enriched.image_url)
        try:
            post_id, slug = publisher.publish(enriched)
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            store.mark_failed(article.url, str(exc))
            log.error("FAIL retry | %s: %s", article.title, exc)
            continue
        result.pushed += 1
        result.new += 1
        store.mark_pushed(article.url, post_id, slug)
        log.info("PUSH retry | post %s | %s", post_id, article.title)
    result.duration_s = time.monotonic() - started
    result.finished_at = utcnow()
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
