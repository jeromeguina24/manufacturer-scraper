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
from manufacturer_scraper.hubspot.publisher import HubSpotPublisher
from manufacturer_scraper.log import configure_logging
from manufacturer_scraper.runner import (
    SourceResult,
    print_summary,
    retry_failed,
    run_source,
)
from manufacturer_scraper.sources import SOURCES, get_source
from manufacturer_scraper.store import Store

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manufacturer-scraper",
        description="Scrape printer-manufacturer newsrooms and publish to HubSpot.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="scrape sources and publish new articles")
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
        "setup-hubspot", help="inspect the portal: blogs, author, custom properties"
    )
    setup.add_argument("--author-name", default="Manufacturer News", help="author to create if none exists")
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

    if not args.dry_run:
        require_hubspot_config(settings)

    store = Store(args.db or settings.scraping.db_path)
    session = make_session(
        settings.scraping.user_agent, settings.scraping.timeout_s
    )

    publisher = None
    if not args.dry_run:
        client = HubSpotClient(settings.hubspot.access_token or "")
        publisher = HubSpotPublisher(client, store, settings)

    selected = _selected_sources(args.source, settings)
    max_pages = args.max_pages or settings.scraping.max_pages

    results: list[SourceResult] = []
    if args.retry_failed:
        by_manufacturer = {
            SOURCES[key].manufacturer: get_source(key, settings, session)
            for key in selected
        }
        results.append(retry_failed(by_manufacturer, store, publisher, limit=args.limit))
    else:
        for key in selected:
            source = get_source(key, settings, session)
            log.info("=== %s (%s) ===", source.manufacturer, key)
            try:
                result = run_source(
                    source,
                    None if args.dry_run else store,
                    publisher,
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

    print_summary(results)
    store.close()
    return 1 if any(r.failed or r.error for r in results) else 0


def cmd_setup_hubspot(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    if not settings.hubspot.access_token:
        log.error("HUBSPOT_ACCESS_TOKEN is not set (see .env.example)")
        return 1
    client = HubSpotClient(settings.hubspot.access_token)

    try:
        blogs = client.list_blogs()
    except HubSpotError as exc:
        log.error("Cannot reach HubSpot (auth/scopes?): %s", exc)
        return 1

    print("Blogs in this portal:")
    if not blogs:
        print("  (none — create a blog in HubSpot first: Marketing -> Website -> Blog)")
    for blog in blogs:
        marker = "  <-- configured" if str(blog.get("id")) == settings.hubspot.blog_id else ""
        print(f"  id={blog.get('id')}  name={blog.get('name')!r}{marker}")

    authors = client.list_blog_authors()
    author_id = settings.hubspot.blog_author_id
    print("\nBlog authors:")
    for author in authors:
        marker = "  <-- configured" if str(author.get("id")) == author_id else ""
        print(f"  id={author.get('id')}  name={author.get('name')!r}{marker}")
    if not authors:
        try:
            created = client.create_blog_author(args.author_name)
            author_id = str(created.get("id", ""))
            print(f"  Created author {args.author_name!r} id={author_id}")
        except HubSpotError as exc:
            print(f"  Could not create author: {exc}")

    if settings.hubspot.custom_properties:
        print("\nCustom properties on blog posts (source_url, manufacturer):")
        if client.ensure_blog_post_properties():
            print("  OK")
        else:
            print(
                "  NOT available — linkback still works via the in-body link.\n"
                "  (HubSpot gates the blog-post property API behind CRM scopes a\n"
                "  content-only private app can't be granted. To use them anyway,\n"
                "  create 'source_url' and 'manufacturer' manually under\n"
                "  Settings -> Properties -> Blog Post; otherwise set\n"
                "  hubspot.custom_properties: false in config.yaml.)"
            )

    print("\nPaste into config.yaml:")
    print("hubspot:")
    if not settings.hubspot.blog_id:
        print("  blog_id: \"<pick one from the list above>\"")
    else:
        print(f"  blog_id: \"{settings.hubspot.blog_id}\"")
    print(f"  blog_author_id: \"{author_id or '<pick one from the list above>'}\"")
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
        blogs = client.list_blogs()
        check("API reachable (content scope)", True)
    except HubSpotError as exc:
        check("API reachable (content scope)", False, str(exc))
        return 1

    blog_ids = {str(b.get("id")) for b in blogs}
    if settings.hubspot.blog_id:
        check("blog_id configured", True, settings.hubspot.blog_id)
        check("blog exists in portal", settings.hubspot.blog_id in blog_ids)
    else:
        check("blog_id configured", False, "run setup-hubspot and fill config.yaml")

    try:
        authors = client.list_blog_authors()
        author_ids = {str(a.get("id")) for a in authors}
        if settings.hubspot.blog_author_id:
            check("blog_author_id configured", True, settings.hubspot.blog_author_id)
            check("author exists in portal", settings.hubspot.blog_author_id in author_ids)
        else:
            check("blog_author_id configured", False, "run setup-hubspot")
    except HubSpotError as exc:
        check("blog authors readable", False, str(exc))

    if settings.hubspot.custom_properties:
        for prop in ("source_url", "manufacturer"):
            found = None
            for object_type in ("BLOG_POST", "blog_post"):
                try:
                    found = client.get_property(object_type, prop)
                except HubSpotError:
                    found = None
                if found:
                    break
            check(f"custom property {prop}", bool(found), "" if found else "run setup-hubspot")

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
