from datetime import UTC, datetime

from manufacturer_scraper.sources.ijetcolor import (
    _date_from_pdf_content,
    _date_from_pdf_url,
    _parse_written_date,
    extract_article_date,
    parse_ijetcolor_items,
)


def test_parse_items_extracts_news_and_press_releases(load_fixture):
    items = parse_ijetcolor_items(load_fixture("ijetcolor_news.html"))
    assert len(items) == 30

    news = [i for i in items if i.categories == ("In The News",)]
    press = [i for i in items if i.categories == ("Press Releases",)]
    assert len(news) == 12
    assert len(press) == 18


def test_parse_items_keeps_descriptive_link_text(load_fixture):
    items = parse_ijetcolor_items(load_fixture("ijetcolor_news.html"))
    by_url = {i.url: i for i in items}

    wtt = next(i for i in items if "128713" in i.url)
    assert wtt.title.startswith("Tim Murphy shares our company")
    assert wtt.categories == ("In The News",)

    united = next(i for i in items if "printing.org" in i.url)
    assert united.title == "United Against Challenges"
    assert united.categories == ("Press Releases",)  # PDF link
    del by_url


def test_parse_items_pdf_titles_from_filename(load_fixture):
    items = parse_ijetcolor_items(load_fixture("ijetcolor_news.html"))
    generic = [i for i in items if i.url.endswith("PRESS%20RELEASE_%20iJetColor%201175%20Pro%2BPXG%20%207-20-2026.pdf")]
    assert len(generic) == 1
    # "Download the press release" anchor text is replaced by the file name.
    assert generic[0].title == "PRESS RELEASE iJetColor 1175 Pro PXG 7-20-2026"


def test_parse_items_dedupes_and_skips_video_hosts(load_fixture):
    items = parse_ijetcolor_items(load_fixture("ijetcolor_news.html"))
    urls = [i.url for i in items]
    assert len(urls) == len(set(urls))
    assert not any("youtube.com" in u or "youtu.be" in u or "wistia.com" in u for u in urls)
    assert not any("ijetcolor.com" in u for u in urls)
    assert all(u.startswith(("http://", "https://")) for u in urls)


def test_parse_items_empty_page():
    assert parse_ijetcolor_items("<html><body><main></main></body></html>") == []


# --- publication-date lookup -------------------------------------------------


def test_parse_written_date_full_and_abbreviated_months():
    assert _parse_written_date("Wednesday, August 07, 2024") == datetime(
        2024, 8, 7, tzinfo=UTC
    )
    assert _parse_written_date("Aug 7, 2024") == datetime(2024, 8, 7, tzinfo=UTC)
    assert _parse_written_date("Sept 30, 2022") == datetime(2022, 9, 30, tzinfo=UTC)


def test_parse_written_date_ignores_non_dates():
    assert _parse_written_date("no date here") is None
    assert _parse_written_date("") is None
    assert _parse_written_date("February 30, 2024") is None  # invalid day


def test_extract_article_date_prefers_meta_tag():
    html = (
        "<html><head>"
        '<meta property="article:published_time" content="2018-11-19T06:12:55+00:00">'
        "</head><body><p class='published'>January 1, 2020</p></body></html>"
    )
    assert extract_article_date(html) == datetime(2018, 11, 19, 6, 12, 55, tzinfo=UTC)


def test_extract_article_date_jsonld():
    html = (
        "<html><body><script type='application/ld+json'>"
        '{"@type":"NewsArticle","datePublished":"2024-08-07T12:00:00Z"}'
        "</script></body></html>"
    )
    assert extract_article_date(html) == datetime(2024, 8, 7, 12, 0, tzinfo=UTC)


def test_extract_article_date_time_element():
    html = "<html><body><time datetime='2023-10-23T09:00:00'>Oct 23</time></body></html>"
    assert extract_article_date(html) == datetime(2023, 10, 23, 9, 0, tzinfo=UTC)


def test_extract_article_date_published_class():
    # whattheythink markup: day-of-week prefix inside a .published paragraph.
    html = (
        "<html><body><p class='published fst-italic'>"
        "Wednesday, August 07, 2024</p></body></html>"
    )
    assert extract_article_date(html) == datetime(2024, 8, 7, tzinfo=UTC)


def test_extract_article_date_whole_page_fallback():
    html = "<html><body><div>Posted on December 15, 2025 by staff</div></body></html>"
    assert extract_article_date(html) == datetime(2025, 12, 15, tzinfo=UTC)


def test_extract_article_date_none_when_absent():
    assert extract_article_date("<html><body><p>nothing here</p></body></html>") is None


def test_date_from_pdf_url_us_format():
    url = (
        "https://x.net/hubfs/PRESS%20RELEASE_%20iJetColor%201175%20Pro%2BPXG"
        "%20%207-20-2026.pdf"
    )
    assert _date_from_pdf_url(url) == datetime(2026, 7, 20, tzinfo=UTC)


def test_date_from_pdf_url_iso_format():
    assert _date_from_pdf_url("https://x.net/Release 2026-07-20.pdf") == datetime(
        2026, 7, 20, tzinfo=UTC
    )


def test_date_from_pdf_url_bare_year():
    assert _date_from_pdf_url("https://x.net/Sale%20Press%20Release%202026.pdf") == (
        datetime(2026, 1, 1, tzinfo=UTC)
    )


def test_date_from_pdf_url_none_when_absent():
    assert _date_from_pdf_url("https://x.net/iJetColorFlow%202.0%20Press%20Release.pdf") is None


def test_date_from_pdf_content_creation_date():
    data = b"%PDF-1.7 ... /CreationDate (D:20250715203014-05'00') ..."
    assert _date_from_pdf_content(data) == datetime(2025, 7, 15, tzinfo=UTC)


def test_date_from_pdf_content_falls_back_to_mod_date():
    data = b"%PDF-1.7 /ModDate (D:20190920125202Z)"
    assert _date_from_pdf_content(data) == datetime(2019, 9, 20, tzinfo=UTC)


def test_date_from_pdf_content_none_when_absent_or_invalid():
    assert _date_from_pdf_content(b"%PDF-1.7 no dates here") is None
    assert _date_from_pdf_content(b"/CreationDate (D:20251340101010)") is None  # month 13
    assert _date_from_pdf_content(b"") is None
