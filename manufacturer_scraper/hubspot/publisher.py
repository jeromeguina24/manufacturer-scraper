"""Publishes normalized Articles to a HubSpot CMS blog."""

from __future__ import annotations

import html
import logging
import posixpath
from collections.abc import Sequence

from manufacturer_scraper.config import Settings
from manufacturer_scraper.hubspot.client import HubSpotClient, HubSpotError
from manufacturer_scraper.models import Article, slugify, truncate
from manufacturer_scraper.store import Store

log = logging.getLogger(__name__)

MAX_SLUG_ATTEMPTS = 5


class PublishError(RuntimeError):
    pass


class HubSpotPublisher:
    def __init__(self, client: HubSpotClient, store: Store, settings: Settings) -> None:
        self.client = client
        self.store = store
        self.settings = settings
        self._remote_tags: dict[str, str] | None = None

    # -- public API ---------------------------------------------------------

    def publish(self, article: Article) -> tuple[str, str]:
        """Create the blog post. Returns (post_id, slug)."""
        tag_ids = self._ensure_tags(article.categories)
        image = self._ensure_image(article)

        slug = self._build_slug(article)
        for attempt in range(1, MAX_SLUG_ATTEMPTS + 1):
            payload = self._build_payload(article, slug, tag_ids, image)
            try:
                post = self.client.create_blog_post(payload)
                post_id = str(post.get("id", ""))
                log.info(
                    "Published %s post %s (%s)", article.manufacturer, post_id, slug
                )
                return post_id, slug
            except HubSpotError as exc:
                if exc.status == 409 and attempt < MAX_SLUG_ATTEMPTS:
                    slug = f"{self._build_slug(article)}-{attempt + 1}"
                    log.warning("Slug collision; retrying with %s", slug)
                    continue
                raise PublishError(f"HubSpot rejected the post: {exc} {exc.body}") from exc
        raise PublishError(f"Could not find a free slug for {article.url}")

    # -- building blocks ------------------------------------------------------

    def _build_slug(self, article: Article) -> str:
        date_part = article.published.strftime("%Y-%m-%d") if article.published else "undated"
        return slugify(f"{article.manufacturer}-{date_part}-{article.title}")

    def _build_payload(
        self,
        article: Article,
        slug: str,
        tag_ids: list[str],
        image: tuple[str, str] | None,
    ) -> dict:
        hub = self.settings.hubspot
        summary = article.summary or article.title
        linkback = (
            f'<p><a href="{html.escape(article.url, quote=True)}" target="_blank" '
            f'rel="noopener">Read the full article on the '
            f"{html.escape(article.manufacturer)} website</a></p>"
        )
        post_body = f"<p>{html.escape(summary)}</p>\n{linkback}"

        payload: dict = {
            "name": article.title,
            "contentGroupId": hub.blog_id,
            "blogAuthorId": hub.blog_author_id,
            "slug": slug,
            "state": hub.post_state,
            "postBody": post_body,
            "metaDescription": truncate(summary, 300),
        }
        if article.published is not None:
            payload["publishDate"] = article.published.isoformat()
        if tag_ids:
            payload["tagIds"] = tag_ids
        if image:
            file_id, _path = image
            if file_id:
                payload["featuredImage"] = file_id
            payload["featuredImageAltText"] = truncate(article.title, 120)
        else:
            payload["useFeaturedImage"] = False
        if hub.custom_properties:
            payload["properties"] = {
                "source_url": article.url,
                "manufacturer": article.manufacturer,
            }
        return payload

    # -- tags -------------------------------------------------------------------

    def _load_remote_tags(self) -> dict[str, str]:
        if self._remote_tags is None:
            self._remote_tags = {}
            for tag in self.client.list_blog_tags():
                name = tag.get("name")
                if name:
                    self._remote_tags[name.casefold()] = str(tag.get("id", ""))
        return self._remote_tags

    def _ensure_tags(self, categories: Sequence[str]) -> list[str]:
        hub = self.settings.hubspot
        excluded = {t.casefold() for t in hub.tag_exclude}
        tag_ids: list[str] = []
        for category in categories:
            name = category.strip()
            if not name or name.casefold() in excluded:
                continue

            tag_id = self.store.cached_tag(name)
            if tag_id is None:
                tag_id = self._load_remote_tags().get(name.casefold())
                if tag_id:
                    self.store.cache_tag(name, tag_id)
            if tag_id is None:
                try:
                    created = self.client.create_blog_tag(name)
                except HubSpotError as exc:
                    log.warning("Could not create tag %r: %s", name, exc)
                    continue
                tag_id = str(created.get("id", ""))
                if tag_id:
                    self.store.cache_tag(name, tag_id)
                    if self._remote_tags is not None:
                        self._remote_tags[name.casefold()] = tag_id
            if tag_id:
                tag_ids.append(tag_id)
        return tag_ids

    # -- images -------------------------------------------------------------------

    def _ensure_image(self, article: Article) -> tuple[str, str] | None:
        """Import the article image into the HubSpot file manager (cached).
        Never fatal: returns None and the post goes out without an image."""
        if not article.image_url:
            return None
        cached = self.store.cached_image(article.image_url)
        if cached and (cached[0] or cached[1]):
            return cached

        file_name = posixpath.basename(article.image_url.split("?")[0]) or "image.jpg"
        file_name = slugify(file_name, 120) or "image"
        # keep a sensible extension
        ext = posixpath.splitext(posixpath.basename(article.image_url.split("?")[0]))[1]
        if ext and not file_name.endswith(ext.lower()):
            file_name = f"{file_name}{ext.lower()}"

        try:
            task_id = self.client.import_file_from_url(
                article.image_url,
                self.settings.hubspot.image_folder_path,
                file_name,
            )
            result = self.client.poll_import_task(task_id)
        except HubSpotError as exc:
            log.warning(
                "Image import failed for %s (%s) — publishing without image",
                article.image_url,
                exc,
            )
            return None

        pair = (result.get("id", ""), result.get("path", ""))
        self.store.cache_image(article.image_url, pair[0], pair[1])
        return pair
