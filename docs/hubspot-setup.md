# HubSpot setup guide

The scraper publishes articles as **CMS blog posts**. HubSpot has no API to
create a blog itself, so a blog must exist in the portal first. Everything
else the scraper can create for you.

## 1. Create a private app (access token)

1. In HubSpot: **Settings → Integrations → Private Apps → Create private app**.
2. On the **Scopes** tab, grant:
   - `content` — required (blogs, posts, tags, authors)
   - `files` — required (importing article images into the file manager)
   - `crm.schemas.blog_posts.write` — optional; needed only if you want the
     `source_url` / `manufacturer` custom properties. The scraper degrades
     gracefully without them (the linkback link is always embedded in the
     post body as well).
3. Copy the access token into `.env`:
   ```
   HUBSPOT_ACCESS_TOKEN=pat-na1-xxxx…xxxx
   ```

## 2. Create (or pick) a blog

In HubSpot: **Marketing → Website → Blog**. Either use an existing blog or
create a new one (e.g. "Manufacturer News"). You'll need its id — the next
step prints it.

## 3. Run the setup assistant

```bash
python -m manufacturer_scraper setup-hubspot
```

It will:
- verify the token and list all **blogs** in the portal (with their ids),
- list **blog authors** and create one named "Manufacturer News" if none exists,
- try to create the `source_url` and `manufacturer` custom properties
  (best effort — some portal plans don't allow it),
- print a ready-to-paste `config.yaml` snippet.

Paste the printed `blog_id` and `blog_author_id` into `config.yaml`.

## 4. Verify

```bash
python -m manufacturer_scraper check-hubspot
```

All lines should report `[OK]`.

## 5. About the linkback

Each post gets the original article URL two ways:

1. **Always**: a "Read the full article on the {Manufacturer} website" link at
   the end of the post body.
2. **When custom properties are available**: `source_url` and `manufacturer`
   properties on the post. If your HubSpot theme's blog listing module
   supports it, you can point the listing's click-through URL at
   `content.source_url` so the card itself links to the original article
   instead of the HubSpot post page.

## 6. Images

Article images are imported into the HubSpot file manager under the folder
configured as `hubspot.image_folder_path` (default `/news-import`) and set as
the post's featured image. If an import fails (e.g. hotlink protection on the
manufacturer's CDN), the post is published without an image.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `HUBSPOT_ACCESS_TOKEN is not set` | Create `.env` from `.env.example` and paste the token |
| `401` from the API | Token expired/revoked — regenerate in the private app settings |
| `403` on posts | Private app is missing the `content` scope |
| `403` on image import | Private app is missing the `files` scope |
| Custom properties `[FAIL]` | Missing `crm.schemas.blog_posts.write` scope or plan limitation — safe to ignore, in-body linkback still works |
| `409` slug collision | Handled automatically (suffix `-2`, `-3`, …) |
