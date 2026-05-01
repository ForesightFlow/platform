import pytest


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "cassette_library_dir": "tests/cassettes",
        "record_mode": "new_episodes",  # record if cassette missing; CI uses --record-mode=none
        "match_on": ["method", "scheme", "host", "port", "path", "query"],
    }
