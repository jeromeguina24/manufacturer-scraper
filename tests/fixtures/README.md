# Test fixtures

Real responses captured from the live manufacturer sites on **2026-08-07**,
used by the parser tests:

| File | Captured from |
|---|---|
| `canon_posts_p1.json` | `GET https://cpp.canon/wp-json/wp/v2/posts?_embed=1&per_page=100&page=1` (trimmed to 4 representative posts: 3 with featured media, 1 without) |
| `canon_categories.json` | `GET https://cpp.canon/wp-json/wp/v2/categories?per_page=100` (trimmed to id/name/count) |
| `fujifilm_list_p1.html` | `GET https://www.fujifilm.com/fb/en/news` |
| `fujifilm_detail_internal.html` | `GET https://www.fujifilm.com/fb/en/news/15455e` |
| `kyocera_list_p1.html` | `GET https://europe.kyocera.com/news/index.html` |
| `konica_list.html` | `GET https://www.konicaminolta.com/global-en/newsroom/release/index.html` |
| `konica_detail.html` | `GET https://www.konicaminolta.com/global-en/newsroom/2026/0714-01-01.html` |
| `fp_newsroom.html` | `GET https://www.fp-usa.com/newsroom` (trimmed to 3 press-release cards) |
| `hp_newsroom.html` | `GET https://www.hp.com/us-en/newsroom.html` (embedded `cards-data` JSON trimmed to 5 representative entries) |
| `duplo_posts_p1.json` | `GET https://www.duplousa.com/wp-json/wp/v2/posts?_embed=1&per_page=10` (trimmed to 2 posts, fields reduced) |
| `duplo_categories.json` | `GET https://www.duplousa.com/wp-json/wp/v2/categories?per_page=100` (trimmed to id/name/count) |
| `predictive_press.html` | `GET https://predictive-insight.com/pages/in-the-press/` (item rows region, 13 entries) |
| `papercut_blog.html` | `GET https://www.papercut.com/blog/` (embedded Alpine `x-init` tile array trimmed to 4 tiles) |
| `ijetcolor_news.html` | `GET https://www.ijetcolor.com/news-events-1` (blocks that contain links) |
| `laserfiche_list.html` | `GET https://www.laserfiche.com/resources/press-center/` (trimmed to 4 list cards) |
| `laserfiche_detail.html` | `GET https://www.laserfiche.com/resources/press-center/press/laserfiche-aws-marketplace-launch/` (trimmed to title + meta tags) |
| `docuware_list.html` | `GET https://start.docuware.com/blog/product-news` (trimmed to 3 blog-listing cards) |

If a parser test starts failing, the most likely cause is markup drift on the
manufacturer's site: re-capture the page with the same URL/User-Agent,
re-run the tests, and adjust the parser if the structure genuinely changed.
