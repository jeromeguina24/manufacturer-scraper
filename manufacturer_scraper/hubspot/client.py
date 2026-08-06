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
        self.session.headers.update(
            {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        )
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

    # -- blogs ------------------------------------------------------------------

    def list_blogs(self) -> list[dict]:
        """List blogs (content groups). HubSpot serves these via the
        blog-settings endpoint (there is no /cms/v3/blogs/blogs route)."""
        blogs: list[dict] = []
        after: str | None = None
        while True:
            params: dict[str, str | int] = {"limit": 100}
            if after is not None:
                params["after"] = after
            data = self._request("GET", "/cms/v3/blog-settings/settings", params=params)
            page = data if isinstance(data, dict) else {}
            blogs.extend(page.get("results") or [])
            after = (page.get("paging") or {}).get("next", {}).get("after")
            if not after:
                return blogs

    def create_blog_post(self, payload: dict) -> dict:
        return self._request("POST", "/cms/v3/blogs/posts", json=payload)  # type: ignore[return-value]

    def find_blog_post_by_slug(self, blog_id: str, slug: str) -> dict | None:
        items = self._items(
            "/cms/v3/blogs/posts",
            params={"content_group_id": blog_id, "slug": slug, "limit": 1},
        )
        return items[0] if items else None

    def list_blog_tags(self) -> list[dict]:
        return self._items("/cms/v3/blogs/tags", params={"limit": 100})

    def create_blog_tag(self, name: str) -> dict:
        return self._request("POST", "/cms/v3/blogs/tags", json={"name": name})  # type: ignore[return-value]

    def list_blog_authors(self) -> list[dict]:
        return self._items("/cms/v3/blogs/authors", params={"limit": 100})

    def create_blog_author(self, name: str, email: str | None = None) -> dict:
        payload: dict = {"name": name}
        if email:
            payload["email"] = email
        return self._request("POST", "/cms/v3/blogs/authors", json=payload)  # type: ignore[return-value]

    # -- files --------------------------------------------------------------------

    def import_file_from_url(self, url: str, folder_path: str, file_name: str) -> str:
        """Start an async import; returns the task id."""
        data = self._request(
            "POST",
            "/files/v3/files/import-from-url/async",
            json={
                "url": url,
                "folderPath": folder_path,
                "fileName": file_name,
                "options": {"overwrite": False},
            },
        )
        task_id = (data or {}).get("id")  # type: ignore[union-attr]
        if not task_id:
            raise HubSpotError(f"No task id returned from import-from-url: {data}")
        return str(task_id)

    def poll_import_task(
        self, task_id: str, timeout_s: float = 90.0, interval_s: float = 2.5
    ) -> dict:
        """Poll until COMPLETE; returns {"id": file_id, "path": hubfs_path}."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            data = self._request(
                "GET", f"/files/v3/files/import-from-url/async/tasks/{task_id}/status"
            ) or {}
            status = data.get("status")  # type: ignore[union-attr]
            if status == "COMPLETE":
                files = data.get("files") or []  # type: ignore[union-attr]
                if files:
                    first = files[0]
                    return {"id": str(first.get("id", "")), "path": first.get("path", "")}
                raise HubSpotError(f"Import task {task_id} completed without files")
            if status in ("CANCELED", "ERROR"):
                raise HubSpotError(f"Import task {task_id} ended with status {status}")
            time.sleep(interval_s)
        raise HubSpotError(f"Import task {task_id} timed out after {timeout_s:.0f}s")

    # -- custom properties (best effort) --------------------------------------------

    def get_property(self, object_type: str, name: str) -> dict | None:
        try:
            return self._request("GET", f"/crm/v3/properties/{object_type}/{name}")  # type: ignore[return-value]
        except HubSpotError as exc:
            if exc.status == 404:
                return None
            raise

    def ensure_custom_property(
        self, object_type: str, name: str, label: str
    ) -> bool:
        """Create a string property if missing. Returns True when present/created."""
        try:
            groups = self._items(f"/crm/v3/properties/{object_type}/groups")
            group_name = groups[0]["name"] if groups else "blog_post_information"
            payload = {
                "groupName": group_name,
                "name": name,
                "label": label,
                "type": "string",
                "fieldType": "text",
            }
            self._request("POST", f"/crm/v3/properties/{object_type}", json=payload)
            log.info("Created custom property %s on %s", name, object_type)
            return True
        except HubSpotError as exc:
            body = (exc.body or "").lower()
            if exc.status == 409 or "already exists" in body or "name_conflict" in body:
                return True
            log.warning("Could not create property %s on %s: %s", name, object_type, exc)
            return False

    def ensure_blog_post_properties(self) -> bool:
        """Create source_url + manufacturer on blog posts. Portal plans differ,
        so every failure is non-fatal; returns True if both are available."""
        ok = True
        for object_type in ("BLOG_POST", "blog_post"):
            made_url = self.ensure_custom_property(
                object_type, "source_url", "Source URL"
            )
            made_mfr = self.ensure_custom_property(
                object_type, "manufacturer", "Manufacturer"
            )
            if made_url and made_mfr:
                return True
            ok = ok and made_url and made_mfr
        return ok
