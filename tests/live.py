"""Helpers for the tests that talk to the real Zenodo sandbox (tests/test_live_sandbox.py).

They run only when `secrets.toml` in the repository root holds a real SANDBOX_TOKEN; the
production token is never read. The records they create are drafts titled with MARKER, deleted
at the end of every test.
"""

import csv
import datetime
import os
import re
import tomllib
import warnings

from tests.support import CONFERENCE_TOML, REPO_ROOT, WorkspaceTestCase, csv_row
from zenodo_upload.zenodo import TIMEOUT, ZenodoClient

SANDBOX_URL = 'https://sandbox.zenodo.org'
MARKER = '[TEST zenodo_upload]'

# The paper the live tests upload (the rest of its metadata comes from the test conference).
PAPER = dict(
    authors='Doe, Jane; Roe, Richard', affiliations='University A;', abstract='An abstract.',
    pages='1--8', note='Paper Session 1',
)


def _repo_toml(name):
    try:
        with open(os.path.join(REPO_ROOT, name), 'rb') as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def sandbox_token():
    """The SANDBOX_TOKEN of the repository's secrets.toml, None if absent or still a placeholder."""
    token = _repo_toml('secrets.toml').get('SANDBOX_TOKEN')
    if not token or token.startswith('replace-with'):
        return None
    return token


class LiveTestCase(WorkspaceTestCase):
    """A test against the real sandbox, in a temporary workspace; skipped without a token."""

    fake_zenodo = False
    write_secrets = False  # the workspace gets the real token in write_live_config()

    def setUp(self):
        token = sandbox_token()
        if token is None:
            self.skipTest('no SANDBOX_TOKEN in secrets.toml')
        super().setUp()
        self.token = token
        self.community = _repo_toml('conference.toml').get('ZENODO_COMMUNITY')
        self.api = f'{SANDBOX_URL}/api/deposit/depositions'
        self.client = ZenodoClient('sandbox', SANDBOX_URL, token)
        self.title = self.live_title()
        self.write_live_config()

    def write_live_config(self, token=None, **conference):
        """
        Workspace config for the real sandbox: the test conference (valid, fictional) in the
        community of the real conference.toml, and `token` (default: the real one) as
        SANDBOX_TOKEN. `conference` overrides keys of conference.toml, e.g. LICENSE='x'.
        """
        values = dict(re.findall(r"^(\w+) = '(.*)'$", CONFERENCE_TOML, re.MULTILINE))
        values['ZENODO_COMMUNITY'] = self.community
        values.update(conference)
        with open('conference.toml', 'w') as f:
            f.writelines(f"{key} = '{value}'\n" for key, value in values.items())
        with open('secrets.toml', 'w') as f:
            f.write(
                "PUBLIC_TOKEN = 'not-used-by-live-tests'\n"
                f"SANDBOX_TOKEN = '{token or self.token}'\n"
            )
        self.reload_app()

    def upload_one(self, *extra_files, **fields):
        """Upload one paper (with the given supplementary files); returns the CSV path."""
        self.make_pdf('p1')
        for name in extra_files:
            self.make_file(name)
        row = dict(key='p1', title=self.title, **PAPER)
        row.update(fields)
        path = self.write_csv(csv_row(**row))
        result = self.run_upload(path)
        self.assertEqual(result.exit_code, 0, result.output)
        return path

    def deposition(self):
        """The draft as Zenodo returns it, found by its deposition id in the CSV."""
        response = self.client.get(self.read_state()[0]['deposition_id'])
        self.assertTrue(response.ok, response.text)
        return response.json()

    def file_names(self):
        response = self.client.list_files(self.read_state()[0]['deposition_id'])
        self.assertTrue(response.ok, response.text)
        return {item['filename'] for item in response.json()}

    def set_status(self, path, status):
        """Take the row back to an earlier step, as if the run had stopped there."""
        with open(path, encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            fieldnames, rows = reader.fieldnames, list(reader)
        rows[0]['status'] = status
        with open(path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def published_record(self, record_id):
        """
        A published record as Zenodo stores and shows it (InvenioRDM JSON: the older record API
        leaves out publisher and part-of); None if there is no such record.
        """
        response = self.client.session.get(
            f'{SANDBOX_URL}/api/records/{record_id}', timeout=TIMEOUT,
            headers={'Accept': 'application/vnd.inveniordm.v1+json'},
        )
        if response.status_code == 404:
            return None
        self.assertTrue(response.ok, response.text)
        return response.json()

    def assert_published_metadata(self, record):
        """The published record holds the metadata the program sends for PAPER."""
        conference = self.app.CONFERENCE
        metadata, fields = record['metadata'], record['custom_fields']

        self.assertEqual(record['status'], 'published')
        self.assertTrue(metadata['title'].startswith(MARKER), metadata['title'])
        self.assertEqual(metadata['description'], PAPER['abstract'])
        self.assertEqual(metadata['publication_date'], conference.publication_date)
        self.assertEqual(metadata['publisher'], conference.publisher)
        self.assertEqual(metadata['resource_type']['id'], 'publication-conferencepaper')
        self.assertEqual([right['id'] for right in metadata['rights']], [conference.license])
        self.assertEqual(
            [
                (c['person_or_org']['name'], [a['name'] for a in c.get('affiliations', [])])
                for c in metadata['creators']
            ],
            [('Doe, Jane', ['University A']), ('Roe, Richard', [])],
        )
        self.assertEqual(fields['imprint:imprint'], {
            'title': conference.proceedings_title, 'isbn': conference.isbn,
            'pages': PAPER['pages'],
        })  # no ISSN: Zenodo has nowhere to keep it
        self.assertEqual(fields['meeting:meeting'], {
            'title': conference.title, 'acronym': conference.acronym,
            'dates': conference.dates, 'place': conference.place, 'url': conference.url,
            'session': PAPER['note'],
        })

    def community_state(self, record):
        """'included' or 'requested' (inclusion request still open) for the record's community."""
        response = self.client.session.get(
            f'{SANDBOX_URL}/api/communities/{self.community}', timeout=TIMEOUT
        )
        self.assertTrue(response.ok, response.text)
        community_id = response.json()['id']
        if community_id in record['parent'].get('communities', {}).get('ids', []):
            return 'included'
        response = self.client.session.get(
            f"{SANDBOX_URL}/api/records/{record['id']}/requests", timeout=TIMEOUT
        )
        self.assertTrue(response.ok, response.text)
        for request in response.json()['hits']['hits']:
            if (request['type'] == 'community-inclusion' and request['is_open']
                    and request['receiver'] == {'community': community_id}):
                return 'requested'
        return 'none'

    def require_community(self):
        """Skip the test unless the conference's community exists on the sandbox."""
        response = self.client.session.get(
            f'{SANDBOX_URL}/api/communities/{self.community}', timeout=TIMEOUT
        )
        if not response.ok:
            self.skipTest(
                f"community '{self.community}' not found on the sandbox (HTTP "
                f"{response.status_code}): create it there, see the README"
            )

    def live_title(self, label=''):
        """A title that marks the record as a test one, different at every call."""
        now = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        return f'{MARKER} {self._testMethodName} {label}{now}'

    def tearDown(self):
        self.delete_test_drafts()  # before the workspace is removed: its CSV names the drafts
        super().tearDown()

    # -- the account's test drafts ----------------------------------------------
    def find_test_drafts(self):
        """The unpublished depositions of the account whose title starts with MARKER."""
        response = self.client.session.get(
            self.api, params={'status': 'draft', 'size': 100}, timeout=TIMEOUT
        )
        if not response.ok:
            warnings.warn(f'cannot list the sandbox drafts: HTTP {response.status_code}')
            return []
        return [
            deposition for deposition in response.json()
            if deposition.get('title', '').startswith(MARKER) and not deposition.get('submitted')
        ]

    def csv_deposition_ids(self):
        """Ids of the sandbox depositions recorded in the test's CSV (the listing is slow)."""
        try:
            return {
                row['deposition_id'] for row in self.read_state()
                if row.get('server') == 'sandbox' and row.get('deposition_id')
            }
        except (AttributeError, OSError):  # no CSV was written
            return set()

    def delete_test_drafts(self):
        """Delete the unpublished test drafts: the ones in the CSV and the ones in the listing."""
        ids = self.csv_deposition_ids() | {str(d['id']) for d in self.find_test_drafts()}
        for deposition_id in sorted(ids):
            response = self.client.get(deposition_id)
            if not response.ok or response.json().get('submitted'):
                continue  # already gone, or published: it cannot be deleted
            response = self.client.session.delete(f"{self.api}/{deposition_id}", timeout=TIMEOUT)
            if not response.ok:
                warnings.warn(f"cannot delete draft {deposition_id}: HTTP {response.status_code}")
