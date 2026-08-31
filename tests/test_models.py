from datetime import UTC, datetime

from manufacturer_scraper.models import (
    absolute_url,
    is_print_related,
    normalize_url,
    parse_date,
    parse_iso_utc,
    slugify,
    strip_html,
    truncate,
)


def test_strip_html_removes_tags_and_collapses_whitespace():
    assert strip_html("<p>Hello&nbsp; <b>world</b></p>\n\n") == "Hello world"


def test_strip_html_unescapes_entities():
    assert strip_html("Canon&#8217;s &amp; Kyocera&#x27;s") == "Canon’s & Kyocera's"


def test_strip_html_drops_scripts():
    assert strip_html("a<script>alert(1)</script>b") == "ab"


def test_parse_date_known_formats():
    assert parse_date("Aug 6, 2026", "%b %d, %Y") == datetime(
        2026, 8, 6, tzinfo=UTC
    )
    assert parse_date("23 June 2026", "%d %B %Y") == datetime(
        2026, 6, 23, tzinfo=UTC
    )
    assert parse_date("2026.07.30", "%Y.%m.%d") == datetime(
        2026, 7, 30, tzinfo=UTC
    )


def test_parse_date_garbage_returns_none():
    assert parse_date("not a date", "%Y.%m.%d") is None
    assert parse_date("", "%Y.%m.%d") is None


def test_parse_iso_utc_assumes_utc():
    dt = parse_iso_utc("2026-07-30T09:01:51")
    assert dt == datetime(2026, 7, 30, 9, 1, 51, tzinfo=UTC)


def test_normalize_url_strips_query_and_trailing_slash():
    assert (
        normalize_url("https://cpp.canon/some-post/?utm_source=x")
        == "https://cpp.canon/some-post"
    )


def test_normalize_url_keeps_fragment():
    # Konica investor links use #anchors as identity.
    assert (
        normalize_url("https://www.konicaminolta.com/page.html#anchor_1q")
        == "https://www.konicaminolta.com/page.html#anchor_1q"
    )


def test_normalize_url_lowercases_host():
    assert normalize_url("HTTPS://WWW.Example.COM/Path/") == "https://www.example.com/Path"


def test_absolute_url():
    assert (
        absolute_url("/news/2026/06/x.html", "https://europe.kyocera.com/news/")
        == "https://europe.kyocera.com/news/2026/06/x.html"
    )


def test_slugify_ascii_and_limits():
    assert slugify("Konica Minolta's New Édge 2026!") == "konica-minolta-s-new-edge-2026"
    assert len(slugify("x" * 500)) <= 180


def test_truncate_on_word_boundary():
    text = "word " * 100
    out = truncate(text.strip(), 60)
    assert len(out) <= 60
    assert out.endswith("…")


def test_is_print_related_matches_print_terms():
    assert is_print_related("Canon launches new inkjet printer")
    assert is_print_related("Managed Print Services agreement signed")
    assert is_print_related("New bizhub multifunction system")
    assert is_print_related("Wide-format signage solutions expand")


def test_is_print_related_prefix_matching():
    # Terms match from a word boundary onward: "print" catches printer/
    # printing/printers, "ink" catches inkjet, "copier" catches copiers.
    assert is_print_related("Printing industry award won")
    assert is_print_related("Inkjet technology breakthrough")
    assert is_print_related("New toner cartridge recycling program")
    assert is_print_related("Copiers for the office of tomorrow")


def test_is_print_related_rejects_unrelated_news():
    assert not is_print_related("HP unveils new EliteBook laptop")
    assert not is_print_related("1st Quarter Financial Results")
    assert not is_print_related("U.S. Healthcare Sales Company established")
    assert not is_print_related("Gaming headset lineup announced")


def test_is_print_related_ignores_word_tails():
    # No match inside longer words: "blueprint", "fingerprint", "email".
    assert not is_print_related("Company unveils new blueprint for growth")
    assert not is_print_related("Fingerprint sensor technology improves")
    assert not is_print_related("Email campaign tips for marketers")


def test_is_print_related_checks_categories_and_summary():
    assert is_print_related("New product announced", categories=("Printers",))
    assert is_print_related("Quarterly update", summary="Toner sales grew five percent")
    assert not is_print_related("New product announced", categories=("Corporate",))
