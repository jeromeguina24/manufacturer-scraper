# HubSpot setup guide

The scraper publishes articles as **CMS blog posts**. HubSpot has no API to
create a blog itself, so a blog must exist in the portal first. Everything
else the scraper can create for you.

## 1. Create a private app (access token)

1. In HubSpot: **Settings → Integrations → Private Apps → Create private app**.
2. On the **Scopes** tab, grant:
   - `content` — required (blogs, posts, tags, authors)
   - `files` — required (importing article images into the file manager)

   The optional `source_url` / `manufacturer` custom properties need write
   access to the CRM properties API, which HubSpot gates behind generic CRM
   scopes (there is no `crm.schemas.blog_posts.*` scope to grant). A
   content-only private app therefore can't create them — the scraper
   degrades gracefully: the linkback link is always embedded in the post
   body. If you still want the properties, create them manually in HubSpot
   (**Settings → Properties → Blog Post**, both as single-line text):
   `source_url` and `manufacturer`, then set `hubspot.custom_properties: true`.
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
| Custom properties `[FAIL]` / "NOT available" | Expected for a content-only private app — HubSpot gives such apps no way to create blog-post properties via API. Safe to ignore (in-body linkback still works); or create `source_url`/`manufacturer` manually under **Settings → Properties → Blog Post** and set `hubspot.custom_properties: true` |
| `409` slug collision | Handled automatically (suffix `-2`, `-3`, …) |
