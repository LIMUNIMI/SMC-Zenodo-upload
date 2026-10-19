"""Check of the per-edition values (conference.toml) before anything is processed."""

import datetime
import re
import urllib.parse

ACCESS_RIGHTS = ('open', 'embargoed', 'restricted', 'closed')
PLACEHOLDER_HOSTS = ('example.org', 'example.com')
PLACEHOLDER_PLACE = 'City, Country'

# Conference fields that are named differently in conference.toml
KEYS = {
    'dates': 'CONFERENCE_DATES', 'title': 'CONFERENCE_TITLE', 'acronym': 'CONFERENCE_ACRONYM',
    'url': 'CONFERENCE_URL', 'community': 'ZENODO_COMMUNITY', 'place': 'CONFERENCE_PLACE',
}


class ConfigError(Exception):
    """conference.toml has unusable values; the message lists them all."""


def validate_conference(conference):
    """Raise ConfigError if a `metadata.Conference` still has placeholder or malformed values."""
    problems = []
    for name, value in conference._asdict().items():
        if not value and name != 'issn':
            problems.append(f"{KEYS.get(name, name.upper())} is empty")

    if conference.publication_date:
        try:
            datetime.date.fromisoformat(conference.publication_date)
        except ValueError:
            problems.append("PUBLICATION_DATE must be a valid date, YYYY-MM-DD")

    if conference.url:
        url = urllib.parse.urlparse(conference.url)
        if url.scheme not in ('http', 'https') or not url.hostname:
            problems.append("CONFERENCE_URL must be a http(s) URL")
        elif url.hostname.removeprefix('www.') in PLACEHOLDER_HOSTS:
            problems.append("CONFERENCE_URL is still the placeholder")

    if conference.access_right and conference.access_right not in ACCESS_RIGHTS:
        problems.append(f"ACCESS_RIGHT must be one of: {', '.join(ACCESS_RIGHTS)}")

    if conference.place == PLACEHOLDER_PLACE:
        problems.append("CONFERENCE_PLACE is still the placeholder")

    if conference.isbn and not _is_isbn(conference.isbn):
        problems.append("ISBN is not a valid ISBN-10 or ISBN-13")

    if conference.issn and not re.fullmatch(r'\d{4}-\d{3}[\dX]', conference.issn):
        problems.append("ISSN must look like 1234-5678 (or be empty)")

    if problems:
        raise ConfigError("conference.toml:\n  " + "\n  ".join(problems))


def _is_isbn(value):
    digits = value.replace('-', '').replace(' ', '')
    if re.fullmatch(r'\d{13}', digits):
        total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits))
        return total % 10 == 0
    if re.fullmatch(r'\d{9}[\dX]', digits):
        total = sum((10 - i) * (10 if d == 'X' else int(d)) for i, d in enumerate(digits))
        return total % 11 == 0
    return False
