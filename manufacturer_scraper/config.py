"""Configuration loading: config.yaml + .env (secrets)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class HubSpotSettings:
    hubdb_table_name: str = "manufacturer_news"
    access_token: str | None = None


@dataclass(frozen=True)
class ScrapingSettings:
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    )
    request_delay_s: float = 1.5
    timeout_s: float = 20.0
    retries: int = 3
    max_pages: int = 3
    db_path: str = "scraper_state.db"
    # Only articles published in this year or later are imported (None = all).
    min_year: int | None = None
    # Keep only print / document-imaging related articles (keyword match on
    # title + categories + summary). Off by default; enable for newsrooms of
    # diversified vendors that also publish non-print news.
    print_topics_only: bool = False


@dataclass(frozen=True)
class SourceSettings:
    enabled: bool = True
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    hubspot: HubSpotSettings
    scraping: ScrapingSettings
    sources: dict[str, SourceSettings]


def _source_settings(raw: dict) -> SourceSettings:
    data = dict(raw or {})
    enabled = bool(data.pop("enabled", True))
    return SourceSettings(enabled=enabled, extra=data)


def _parse_min_year(raw_value) -> int | None:
    """`scraping.min_year`: a year, the string 'current', or absent."""
    if raw_value is None or str(raw_value).strip() == "":
        return None
    if isinstance(raw_value, bool):
        raise ConfigError(f"scraping.min_year must be a year or 'current', got {raw_value!r}")
    if isinstance(raw_value, int):
        return raw_value
    text = str(raw_value).strip().lower()
    if text == "current":
        return datetime.now(UTC).year
    if text.isdigit():
        return int(text)
    raise ConfigError(f"scraping.min_year must be a year or 'current', got {raw_value!r}")


_MISSING = object()


def resolve_min_year(global_min_year: int | None, extra: dict) -> int | None:
    """Effective min_year for one source.

    A per-source `min_year` (in its config block) overrides the global
    `scraping.min_year`; `min_year: null` disables the filter for that source
    (useful for small archives that predate the cutoff).
    """
    raw = extra.get("min_year", _MISSING)
    if raw is _MISSING:
        return global_min_year
    return _parse_min_year(raw)


def resolve_print_topics_only(global_flag: bool, extra: dict) -> bool:
    """Effective print-topics filter for one source.

    A per-source `print_topics_only` (in its config block) overrides the
    global `scraping.print_topics_only`. Specialist print/document sources
    keep this off so their (print-related) niche content isn't dropped by
    the keyword match.
    """
    raw = extra.get("print_topics_only", _MISSING)
    if raw is _MISSING:
        return global_flag
    return bool(raw)


def load_settings(
    config_path: str | Path = "config.yaml",
    env_file: str | Path | None = ".env",
) -> Settings:
    """Load settings from YAML + environment. Never raises for a missing
    HubSpot token here — callers that need it check and produce a clear error."""
    config_path = Path(config_path)
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    if env_file is not None:
        env_file = Path(env_file)
        if env_file.is_file():
            load_dotenv(dotenv_path=env_file, override=False)

    hub_raw = raw.get("hubspot") or {}
    hubspot = HubSpotSettings(
        hubdb_table_name=str(hub_raw.get("hubdb_table_name") or "manufacturer_news"),
        access_token=os.environ.get("HUBSPOT_ACCESS_TOKEN") or None,
    )

    scr_raw = raw.get("scraping") or {}
    scraping = ScrapingSettings(
        user_agent=str(scr_raw.get("user_agent") or ScrapingSettings.user_agent),
        request_delay_s=float(scr_raw.get("request_delay_s", 1.5)),
        timeout_s=float(scr_raw.get("timeout_s", 20)),
        retries=int(scr_raw.get("retries", 3)),
        max_pages=int(scr_raw.get("max_pages", 3)),
        db_path=str(scr_raw.get("db_path") or "scraper_state.db"),
        min_year=_parse_min_year(scr_raw.get("min_year")),
        print_topics_only=bool(scr_raw.get("print_topics_only", False)),
    )

    sources = {
        name: _source_settings(body)
        for name, body in (raw.get("sources") or {}).items()
    }

    return Settings(hubspot=hubspot, scraping=scraping, sources=sources)


def require_hubspot_config(settings: Settings) -> None:
    """Raise an actionable ConfigError if anything needed for syncing is missing."""
    if not settings.hubspot.access_token:
        raise ConfigError(
            "HubSpot configuration incomplete:\n"
            "  - HUBSPOT_ACCESS_TOKEN is not set (put it in .env — see .env.example)"
        )
