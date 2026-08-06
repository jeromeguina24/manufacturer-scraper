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

If a parser test starts failing, the most likely cause is markup drift on the
manufacturer's site: re-capture the page with the same URL/User-Agent,
re-run the tests, and adjust the parser if the structure genuinely changed.
