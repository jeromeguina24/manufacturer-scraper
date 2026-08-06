"""Manufacturer newsroom sources. To add a manufacturer: write a new module
subclassing BaseSource and add it to ALL_SOURCES below."""

from __future__ import annotations

import requests

from manufacturer_scraper.config import Settings
from manufacturer_scraper.sources.base import BaseSource
from manufacturer_scraper.sources.canon import CanonSource
from manufacturer_scraper.sources.fujifilm import FujifilmSource
from manufacturer_scraper.sources.konica import KonicaSource
from manufacturer_scraper.sources.kyocera import KyoceraSource

ALL_SOURCES: tuple[type[BaseSource], ...] = (
    CanonSource,
    FujifilmSource,
    KyoceraSource,
    KonicaSource,
)

SOURCES: dict[str, type[BaseSource]] = {cls.name: cls for cls in ALL_SOURCES}


def get_source(name: str, settings: Settings, session: requests.Session) -> BaseSource:
    try:
        cls = SOURCES[name]
    except KeyError:
        raise KeyError(
            f"Unknown source {name!r}; available: {', '.join(sorted(SOURCES))}"
        ) from None
    return cls(settings, session)
