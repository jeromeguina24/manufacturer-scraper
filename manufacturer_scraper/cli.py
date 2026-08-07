"""Command line interface: run / setup-hubspot / check-hubspot."""

from __future__ import annotations

import argparse
import logging
import sys

import requests

from manufacturer_scraper import __version__
from manufacturer_scraper.config import (
    ConfigError,
    Settings,
    load_settings,
    require_hubspot_config,
)
from manufacturer_scraper.http import make_session
from manufacturer_scraper.hubspot.client import HubSpotClient, HubSpotError
from manufacturer_scraper.hubspot.syncer import EXPECTED_COLUMNS, HubDbSyncer, SyncError
from manufacturer_scraper.log import configure_logging
from manufacturer_scraper.runner import (
    SourceResult,
    print_summary,
    retry_failed,
    run_source,
    sync_articles,
)
from manufacturer_scraper.sources import SOURCES, get_source
from manufacturer_scraper.store import Store

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manufacturer-scraper",
        description="Scrape printer-manufacturer newsrooms and sync them to HubSpot HubDB.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="scrape sources and sync new articles to HubDB")
    run.add_argument(
        "--source",
        default="all",
        help=f"source to run ({', '.join(sorted(SOURCES))} or all; default: all)",
    )
    run.add_argument("--dry-run", action="store_true", help="scrape + report only")
    run.add_argument("--max-pages", type=int, default=None, help="page limit per source")
    run.add_argument("--limit", type=int, default=None, help="max NEW articles this run")
    run.add_argument("--retry-failed", action="store_true", help="retry failed articles")
    run.add_argument("--db", default=None, help="override scraping.db_path")
    run.set_defaults(func=cmd_run)

    setup = sub.add_parser(
        "setup-hubspot", help="create/verify the HubDB table used by the scraper"
    )
    setup.set_defaults(func=cmd_setup_hubspot)

    check = sub.add_parser("check-hubspot", help="report-only HubSpot health check")
    check.set_defaults(func=cmd_check_hubspot)

    return parser


def _selected_sources(name: str, settings: Settings) -> list[str]:
    if name != "all":
        if name not in SOURCES:
            raise ConfigError(
                f"Unknown source {name!r}. Available: {', '.join(sorted(SOURCES))}"
            )
        return [name]
    enabled = [key for key, src in settings.sources.items() if src.enabled]
    unknown = [key for key in enabled if key not in SOURCES]
    if unknown:
        raise ConfigError(f"config.yaml lists unknown sources: {', '.join(unknown)}")
    return [key for key in SOURCES if key in enabled]


def cmd_run(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)

    if args.dry_run and args.retry_failed:
        raise ConfigError("--retry-failed cannot be combined with --dry-run")

    if not args.dry_run:
        require_hubspot_config(settings)

    store = Store(args.db or settings.scraping.db_path)
    session = make_session(
        settings.scraping.user_agent, settings.scraping.timeout_s
    )

    syncer = None
    if not args.dry_run:
        client = HubSpotClient(settings.hubspot.access_token or "")
        syncer = HubDbSyncer(client, store, settings)

    selected = _selected_sources(args.source, settings)
    max_pages = args.max_pages or settings.scraping.max_pages

    results: list[SourceResult] = []
    if args.retry_failed:
        by_manufacturer = {
            SOURCES[key].manufacturer: get_source(key, settings, session)
            for key in selected
        }
        results.append(retry_failed(by_manufacturer, store, syncer, limit=args.limit))
    else:
        for key in selected:
            source = get_source(key, settings, session)
            log.info("=== %s (%s) ===", source.manufacturer, key)
            try:
                result = run_source(
                    source,
                    None if args.dry_run else store,
                    dry_run=args.dry_run,
                    max_pages=max_pages,
                    limit=args.limit,
                )
            except Exception as exc:  # noqa: BLE001 - one down source must not block the rest
                log.error("SOURCE FAILED %s (%s): %s", source.manufacturer, key, exc)
                result = SourceResult(source=key, dry_run=args.dry_run, error=str(exc))
            if not args.dry_run:
                store.record_run(
                    started_at=result.started_at,
                    finished_at=result.finished_at,
                    source=result.source,
                    dry_run=result.dry_run,
                    found=result.found,
                    new=result.new,
                    pushed=result.pushed,
                    failed=result.failed,
                    skipped=result.skipped_seen,
                )
            results.append(result)

        # One HubDB sync per run, after all sources. pending_articles() also
        # picks up leftovers from a crashed earlier run (self-healing).
        if not args.dry_run:
            pending = store.pending_articles()
            if pending:
                sync_result = sync_articles(syncer, pending)
                store.record_run(
                    started_at=sync_result.started_at,
                    finished_at=sync_result.finished_at,
                    source=sync_result.source,
                    dry_run=False,
                    found=0,
                    new=sync_result.new,
                    pushed=sync_result.pushed,
                    failed=sync_result.failed,
                    skipped=0,
                )
                results.append(sync_result)

    print_summary(results)
    store.close()
    return 1 if any(r.failed or r.error for r in results) else 0


def cmd_setup_hubspot(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    if not settings.hubspot.access_token:
        log.error("HUBSPOT_ACCESS_TOKEN is not set (see .env.example)")
        return 1

    store = Store(settings.scraping.db_path)
    client = HubSpotClient(settings.hubspot.access_token)
    syncer = HubDbSyncer(client, store, settings)

    try:
        table_id = syncer.ensure_table()
    except HubSpotError as exc:
        if exc.status == 403:
            log.error(
                "HubSpot refused the HubDB call (403). HubDB requires "
                "Marketing Hub Professional or CMS Professional, and the "
                "private app needs the 'hubdb' scope. Details: %s",
                exc,
            )
        else:
            log.error("Cannot reach HubSpot (auth/scopes?): %s", exc)
        store.close()
        return 1
    except SyncError as exc:
        log.error("%s", exc)
        store.close()
        return 1

    print(f"HubDB table ready: name={settings.hubspot.hubdb_table_name!r} id={table_id}")
    print("\nPaste into config.yaml:")
    print("hubspot:")
    print(f"  hubdb_table_name: \"{settings.hubspot.hubdb_table_name}\"")
    print(
        "\nNext: create the hub page once — see docs/hubspot-setup.md and "
        "docs/hub-page-template.html."
    )
    print(
        "\nNote: if earlier experiments created blog posts in this portal, "
        "delete them manually (Marketing -> Website -> Blog)."
    )
    store.close()
    return 0


def cmd_check_hubspot(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    problems = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal problems
        print(f"  [{'OK' if ok else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
        if not ok:
            problems += 1

    print("HubSpot health check")
    if not settings.hubspot.access_token:
        check("access token present", False, "HUBSPOT_ACCESS_TOKEN not set in .env")
        return 1
    check("access token present", True)

    client = HubSpotClient(settings.hubspot.access_token)
    try:
        client.list_hubdb_tables()
        check("API reachable (hubdb scope)", True)
    except HubSpotError as exc:
        detail = str(exc)
        if exc.status == 403:
            detail += (
                " — HubDB requires Marketing Hub Professional/CMS Professional "
                "and the 'hubdb' scope on the private app"
            )
        check("API reachable (hubdb scope)", False, detail)
        return 1

    try:
        table = client.get_hubdb_table(settings.hubspot.hubdb_table_name)
    except HubSpotError as exc:
        check("table readable", False, str(exc))
        return 1
    if table is None:
        check(
            "HubDB table exists",
            False,
            f"{settings.hubspot.hubdb_table_name!r} not found — run setup-hubspot",
        )
        return 1
    check("HubDB table exists", True, f"id={table.get('id')}")

    existing = {column.get("name") for column in table.get("columns", [])}
    missing = [name for name in EXPECTED_COLUMNS if name not in existing]
    check("expected columns present", not missing, ", ".join(missing) if missing else "")

    try:
        rows = client.list_hubdb_rows(str(table.get("id")), limit=100)
        check("rows readable", True, f"{len(rows)} row(s) live (capped sample)")
    except HubSpotError as exc:
        check("rows readable", False, str(exc))

    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    # Windows consoles often use cp1252; force UTF-8 so titles render cleanly.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):  # pragma: no cover
                pass

    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    try:
        return args.func(args)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2
    except requests.RequestException as exc:
        log.error("Network error: %s", exc)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
