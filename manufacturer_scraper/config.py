"""Configuration loading: config.yaml + .env (secrets)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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
