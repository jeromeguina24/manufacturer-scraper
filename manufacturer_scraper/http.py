"""Polite HTTP helpers: browser UA, delays, retries with backoff."""

from __future__ import annotations

import logging
import random
import time

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


class FetchError(RuntimeError):
    """A request ultimately failed after retries."""


def make_session(user_agent: str, timeout: float) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    # Default per-request timeout (requests has no session-level timeout natively).
    session.timeout = timeout  # type: ignore[attr-defined]
    return session


def _sleep_delay(base_delay_s: float) -> None:
    if base_delay_s > 0:
        time.sleep(base_delay_s + random.uniform(0.0, base_delay_s * 0.3))


def fetch(
    session: requests.Session,
    url: str,
    *,
    params: dict | None = None,
    retries: int = 3,
    backoff_base: float = 2.0,
    delay_s: float = 0.0,
    acceptable: tuple[int, ...] | None = None,
) -> requests.Response:
    """GET a URL with politeness delay and retries on 429/5xx/connection errors.

    `acceptable` optionally widens which status codes are returned without error
    (e.g. (200, 404) to probe end-of-pagination); anything else non-2xx raises
    FetchError after retries are exhausted.
    """
    timeout = getattr(session, "timeout", 20)
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        _sleep_delay(delay_s)
        try:
            log.debug("GET %s%s", url, f" params={params}" if params else "")
            response = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries:
                wait = backoff_base * (2**attempt)
                log.warning("Request error for %s (%s); retrying in %.1fs", url, exc, wait)
                time.sleep(wait)
                continue
            raise FetchError(f"Request failed for {url}: {exc}") from exc

        if response.status_code == 429 or response.status_code >= 500:
            if attempt < retries:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else backoff_base * (2**attempt)
                except ValueError:
                    wait = backoff_base * (2**attempt)
                log.warning(
                    "HTTP %s for %s; retrying in %.1fs", response.status_code, url, wait
                )
                time.sleep(wait)
                continue
            raise FetchError(f"HTTP {response.status_code} for {url} after {retries} retries")

        ok_codes = acceptable or (200,)
        if response.status_code not in ok_codes and not (
            acceptable is None and 200 <= response.status_code < 300
        ):
            raise FetchError(f"HTTP {response.status_code} for {url}")
        # requests falls back to ISO-8859-1 when the server declares no charset
        # (Kyocera, Konica), which mojibakes UTF-8 pages. Trust UTF-8 then.
        if "charset" not in response.headers.get("Content-Type", "").lower():
            response.encoding = "utf-8"
        return response

    raise FetchError(f"Request failed for {url}: {last_error}")  # pragma: no cover


def get_soup(
    session: requests.Session,
    url: str,
    *,
    parser: str = "lxml",
    retries: int = 3,
    delay_s: float = 0.0,
    acceptable: tuple[int, ...] | None = None,
) -> tuple[BeautifulSoup, requests.Response]:
    response = fetch(session, url, retries=retries, delay_s=delay_s, acceptable=acceptable)
    return BeautifulSoup(response.text, parser), response
