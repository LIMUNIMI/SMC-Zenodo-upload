"""Zenodo metadata of a paper, built from its CSV row."""

from typing import NamedTuple

from zenodo_upload.rows import field, split_authors


class Conference(NamedTuple):
    """Per-edition values, from conference.toml."""
    publication_date: str
    dates: str
    title: str
    acronym: str
    url: str
    community: str
    license: str
    access_right: str
    publisher: str
    place: str
    proceedings_title: str
    isbn: str  # empty when not known yet
    issn: str  # empty when the proceedings have none


def build_deposition(row, conference):
    """The deposition dict for Zenodo ({'metadata': {...}}) of a CSV row."""
    affiliations = [a.strip() for a in field(row, 'affiliations', '').split(';')]
    creators = []
    for index, author_name in enumerate(split_authors(row['authors'])):
        creator = {'name': author_name}
        if field(row, 'affiliations') and affiliations[index]:
            creator['affiliation'] = affiliations[index]
        creators.append(creator)

    pages = field(row, 'pages')
    conf_session = field(row, 'note')

    data = {
        'metadata': {
            'title': row['title'],
            'upload_type': 'publication',
            'publication_type': 'conferencepaper',
            'description': field(row, 'abstract', '---'),  # '---' if no abstract is given
            'conference_title': conference.title,
            'conference_acronym': conference.acronym,
            'conference_dates': conference.dates,
            'conference_place': conference.place,
            'conference_url': conference.url,
            'publication_date': conference.publication_date,
            'partof_title': conference.proceedings_title,
            'imprint_title': conference.proceedings_title,
            'creators': creators,
            'communities': [{'identifier': conference.community}],  # the conference's community
            'license': conference.license,
            'access_right': conference.access_right,
            'imprint_publisher': conference.publisher
        }
    }

    if conference.isbn:
        data['metadata']['imprint_isbn'] = conference.isbn

    if conference.issn:
        data['metadata']['imprint_issn'] = conference.issn

    if conf_session is not None:
        data['metadata']['conference_session'] = conf_session

    if pages is not None:
        data['metadata']['partof_pages'] = pages

    return data
