from datetime import UTC, datetime

from manufacturer_scraper.sources.kyocera import (
    extract_detail_image,
    matches_scope,
    parse_kyocera_list,
)

INCLUDE = ["Printers / Multifunctionals", "Printing Devices"]


def test_parse_list_extracts_all_fields(load_fixture):
    items = parse_kyocera_list(load_fixture("kyocera_list_p1.html"))
    assert len(items) == 20

    first = items[0]
    assert first.date == "23 June 2026"
    assert first.title.startswith("Kyocera brings comprehensive ceramic expertise")
    assert first.url == "https://europe.kyocera.com/news/2026/06/23091907.html"
    assert "Semiconductor Components" in first.categories
    assert first.summary  # SubTitle used as summary


def test_scope_filter_keeps_only_printer_items(load_fixture):
    items = parse_kyocera_list(load_fixture("kyocera_list_p1.html"))
    kept = [i for i in items if matches_scope(i.categories, INCLUDE)]
    assert len(kept) == 2
    assert any(i.categories == ("Printing Devices",) for i in kept)
    assert any("Printers / Multifunctionals" in i.categories for i in kept)


def test_matches_scope_is_case_and_whitespace_insensitive():
    assert matches_scope(("printers /  multifunctionals",), INCLUDE)
    assert matches_scope(("Printing Devices",), INCLUDE)
    assert not matches_scope(("Corporate",), INCLUDE)
    # Empty include list means "keep everything".
    assert matches_scope(("Corporate",), [])


def test_date_parsing_shape():
    items = parse_kyocera_list(
        "<ol><li class='news-BoxA_Item'>"
        "<p class='news-BoxA_PostDate'>05 March 2026</p>"
        "<p class='news-BoxA_Title'>T</p>"
        "<a class='news-BoxA_Link' href='/news/2026/03/x.html'>Read more</a>"
        "</li></ol>"
    )
    assert parse_date_ok(items[0].date)


def parse_date_ok(value: str) -> bool:
    from manufacturer_scraper.models import parse_date

    return parse_date(value, "%d %B %Y") == datetime(2026, 3, 5, tzinfo=UTC)


def test_extract_detail_image_skips_common_assets():
    html = """
    <main>
      <img src="/_assets/img/common/logo.svg">
      <img src="/news/2026/06/photo.jpg">
    </main>
    """
    assert extract_detail_image(html) == "https://europe.kyocera.com/news/2026/06/photo.jpg"


def test_extract_detail_image_none_when_only_logos():
    html = '<main><img src="/_assets/img/common/ogp.png"></main>'
    assert extract_detail_image(html) is None
