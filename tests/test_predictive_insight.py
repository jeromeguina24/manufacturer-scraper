from datetime import UTC, datetime

from manufacturer_scraper.sources.predictive_insight import parse_press_date, parse_press_list


def test_parse_press_list_extracts_all_entries(load_fixture):
    items = parse_press_list(load_fixture("predictive_press.html"))
    assert len(items) == 13


def test_parse_press_list_groups_title_date_link(load_fixture):
    items = parse_press_list(load_fixture("predictive_press.html"))

    first = items[0]
    assert first.title == "Print Security Landscape, 2024"
    assert first.date == "July, 2024"
    assert first.url == (
        "https://www.mpsmonitor.com/docs/"
        "Quocirca-Print-Security-2024_MPS-Monitor_Excerpt.pdf"
    )

    second = items[1]
    assert "Mind-Blowing Growth Spurt" in second.title
    assert second.date == "April, 2024"
    assert second.url.startswith("https://www.thecannatareport.com/")

    last = items[-1]
    assert last.title == "Stramaglio Consulting Partners with Predictive Insight"
    assert last.date == "December, 2020"


def test_parse_press_list_no_orphan_items(load_fixture):
    """Every item must have a title — the page heading alone never emits one."""
    items = parse_press_list(load_fixture("predictive_press.html"))
    assert all(item.title for item in items)
    assert all(item.url.startswith("http") for item in items)


def test_parse_press_date_formats():
    assert parse_press_date("July, 2024") == datetime(2024, 7, 1, tzinfo=UTC)
    assert parse_press_date("December 2020") == datetime(2020, 12, 1, tzinfo=UTC)
    assert parse_press_date("") is None
    assert parse_press_date("not a date") is None
