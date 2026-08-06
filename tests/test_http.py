import pytest
import responses

from manufacturer_scraper.http import FetchError, fetch, make_session


@pytest.fixture
def session():
    return make_session("test-agent", timeout=5)


@responses.activate
def test_utf8_assumed_when_charset_missing(session):
    # Kyocera/Konica serve `text/html` with no charset; requests would fall
    # back to ISO-8859-1 and mojibake UTF-8 pages.
    responses.add(
        responses.GET,
        "https://example.com/news",
        body="Kyocera’s news".encode("utf-8"),  # noqa: UP012 - explicitness is the point
        content_type="text/html",  # no charset= declared
    )
    response = fetch(session, "https://example.com/news")
    assert response.text == "Kyocera’s news"


@responses.activate
def test_declared_charset_is_respected(session):
    responses.add(
        responses.GET,
        "https://example.com/news",
        body="café".encode("latin-1"),
        content_type="text/html; charset=ISO-8859-1",
    )
    response = fetch(session, "https://example.com/news")
    assert response.text == "café"


@responses.activate
def test_unacceptable_status_raises(session):
    responses.add(responses.GET, "https://example.com/x", status=403)
    with pytest.raises(FetchError):
        fetch(session, "https://example.com/x", retries=0)


@responses.activate
def test_acceptable_widens_status_codes(session):
    responses.add(responses.GET, "https://example.com/x", status=404)
    response = fetch(session, "https://example.com/x", retries=0, acceptable=(200, 404))
    assert response.status_code == 404
