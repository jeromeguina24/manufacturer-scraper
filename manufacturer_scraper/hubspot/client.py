"""Thin HubSpot REST client: Bearer auth, retries on 429/5xx, typed helpers."""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.hubapi.com"


class HubSpotError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class HubSpotClient:
    def __init__(
        self,
        access_token: str,
        session: requests.Session | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.session = session or requests.Session()
        # Content-Type is set per request by requests (application/json for
        # json= payloads); a session-level value is unnecessary.
        self.session.headers["Authorization"] = f"Bearer {access_token}"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # -- low level ------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        retries: int = 3,
        backoff_base: float = 2.0,
    ) -> dict | list | None:
        url = f"{self.base_url}{path}"
        last_error: HubSpotError | None = None
        for attempt in range(retries + 1):
            try:
                response = self.session.request(
                    method, url, json=json, params=params, timeout=self.timeout
                )
            except requests.RequestException as exc:
                if attempt < retries:
                    time.sleep(backoff_base * (2**attempt))
                    continue
                raise HubSpotError(f"Request failed: {exc}") from exc

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else backoff_base * (2**attempt)
                except ValueError:
                    wait = backoff_base * (2**attempt)
                log.warning("HubSpot 429 on %s; waiting %.1fs", path, wait)
                if attempt < retries:
                    time.sleep(wait)
                    continue
            if response.status_code >= 500 and attempt < retries:
                time.sleep(backoff_base * (2**attempt))
                continue

            if 200 <= response.status_code < 300:
                if not response.content:
                    return None
                return response.json()

            raise HubSpotError(
                f"HubSpot API error {response.status_code} on {method} {path}",
                status=response.status_code,
                body=response.text[:2000],
            )
        raise last_error or HubSpotError(f"Request failed for {path}")  # pragma: no cover

    def _items(self, path: str, params: dict | None = None) -> list[dict]:
        data = self._request("GET", path, params=params) or {}
        return list(data.get("results", []))  # type: ignore[union-attr]

    # -- HubDB ------------------------------------------------------------------

    def list_hubdb_tables(self) -> list[dict]:
        return self._items("/cms/v3/hubdb/tables", params={"limit": 100})

    def get_hubdb_table(self, table_id_or_name: str) -> dict | None:
        try:
            return self._request("GET", f"/cms/v3/hubdb/tables/{table_id_or_name}")  # type: ignore[return-value]
        except HubSpotError as exc:
            if exc.status == 404:
                return None
            raise

    def create_hubdb_table(self, name: str, label: str, columns: list[dict]) -> dict:
        return self._request(  # type: ignore[return-value]
            "POST",
            "/cms/v3/hubdb/tables",
            json={"name": name, "label": label, "columns": columns},
        )

    def create_hubdb_row(
        self, table_id_or_name: str, values: dict, name: str | None = None
    ) -> dict:
        """Add a row to the DRAFT version; publish via publish_hubdb_table."""
        payload: dict = {"values": values}
        if name:
            payload["name"] = name
        return self._request(  # type: ignore[return-value]
            "POST", f"/cms/v3/hubdb/tables/{table_id_or_name}/rows", json=payload
        )

    def publish_hubdb_table(self, table_id_or_name: str) -> dict:
        """Push the draft table (schema + rows) live."""
        return self._request(  # type: ignore[return-value]
            "POST", f"/cms/v3/hubdb/tables/{table_id_or_name}/draft/push-live"
        )

    def list_hubdb_rows(self, table_id_or_name: str, limit: int = 10) -> list[dict]:
        return self._items(
            f"/cms/v3/hubdb/tables/{table_id_or_name}/rows", params={"limit": limit}
        )

