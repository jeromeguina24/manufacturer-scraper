from datetime import UTC, datetime
from pathlib import Path

import pytest

from manufacturer_scraper.config import ConfigError, load_settings, resolve_min_year


def _write_config(tmp_path: Path, scraping_block: str) -> Path:
    config = tmp_path / "config.yaml"
    config.write_text(f"scraping:\n{scraping_block}\n", encoding="utf-8")
    return config


def test_min_year_current_resolves_to_this_year(tmp_path):
    settings = load_settings(_write_config(tmp_path, "  min_year: current"), env_file=None)
    assert settings.scraping.min_year == datetime.now(UTC).year


def test_min_year_fixed_int(tmp_path):
    settings = load_settings(_write_config(tmp_path, "  min_year: 2024"), env_file=None)
    assert settings.scraping.min_year == 2024


def test_min_year_quoted_number(tmp_path):
    settings = load_settings(_write_config(tmp_path, '  min_year: "2024"'), env_file=None)
    assert settings.scraping.min_year == 2024


def test_min_year_absent_means_no_filter(tmp_path):
    settings = load_settings(_write_config(tmp_path, "  retries: 3"), env_file=None)
    assert settings.scraping.min_year is None


def test_min_year_invalid_value_raises(tmp_path):
    with pytest.raises(ConfigError, match="min_year"):
        load_settings(_write_config(tmp_path, "  min_year: nonsense"), env_file=None)


def test_resolve_min_year_inherits_global_when_absent():
    assert resolve_min_year(2026, {}) == 2026
    assert resolve_min_year(2026, {"per_page": 100}) == 2026
    assert resolve_min_year(None, {"per_page": 100}) is None


def test_resolve_min_year_source_override_wins():
    assert resolve_min_year(2026, {"min_year": 2019}) == 2019
    assert resolve_min_year(None, {"min_year": 2019}) == 2019
    assert resolve_min_year(2026, {"min_year": "current"}) == datetime.now(UTC).year


def test_resolve_min_year_null_disables_filter_for_source():
    assert resolve_min_year(2026, {"min_year": None}) is None
