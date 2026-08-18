from manufacturer_scraper.sources.ijetcolor import parse_ijetcolor_items


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
