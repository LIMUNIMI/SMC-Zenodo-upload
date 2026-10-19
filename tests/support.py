"""Shared helpers for the test suite.

Tests never touch the network: ``requests.get``/``requests.post`` are replaced by
:class:`FakeZenodo`. Each test runs in a temporary working directory because the
program resolves ``./upload/``, ``secrets.toml`` and ``conference.toml`` relative
to the CWD.
"""

import contextlib
import csv
import importlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import urllib.parse
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(REPO_ROOT, 'tests', 'fixtures')
EXAMPLES_DIR = os.path.join(REPO_ROOT, 'examples')
MODULE_NAME = 'zenodo_upload.__main__'

# Absolute path: the CWD changes during tests, so '' in sys.path would break.
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

MB = 1024 * 1024
PUBLIC_TOKEN = 'PUB-TOKEN'
SANDBOX_TOKEN = 'SBX-TOKEN'
CONFERENCE_TOML = (
    "PUBLICATION_DATE = '2026-06-23'\n"
    "CONFERENCE_DATES = '23 June - 26 June, 2026'\n"
    "CONFERENCE_TITLE = 'Example Conference on Sound'\n"
    "CONFERENCE_ACRONYM = 'EXC'\n"
    "CONFERENCE_URL = 'https://example.org'\n"
    "ZENODO_COMMUNITY = 'example_community'\n"
    "LICENSE = 'cc-by-4.0'\n"
    "ACCESS_RIGHT = 'open'\n"
    "PUBLISHER = 'Example Publisher'\n"
)


class CliResult:
    """Outcome of a CLI invocation: exit code, captured stdout and raised exception."""

    def __init__(self, exit_code, output, exception=None):
        self.exit_code = exit_code
        self.output = output
        self.exception = exception


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        if text is not None:
            self.text = text
        else:
            self.text = json.dumps(payload) if payload is not None else ''

    def json(self):
        if self._payload is None:
            raise ValueError('response is not JSON')
        return self._payload


class FakeZenodo:
    """Records calls and answers like the Zenodo deposit API.

    ``fail_create``/``fail_publish``/``fail_pdf`` take a status code (or a
    ``FakeResponse``) and apply to every deposition; ``fail_files`` maps an
    uploaded filename to a status code (or ``FakeResponse``). They stay set until
    the test clears them. ``fail_list``, ``fail_listing`` and ``fail_get`` do the same for
    the listing of the account's depositions, of a deposition's files and for the fetch of a
    deposition.
    ``lost_publish`` makes a publish succeed on the server while the answer is an
    error; ``doi_missing`` hides the DOI of depositions.
    """

    def __init__(self):
        self.calls = []
        self.fail_create = None
        self.fail_publish = None
        self.fail_pdf = None
        self.fail_list = None
        self.fail_listing = None
        self.fail_get = None
        self.fail_files = {}
        self.fail_titles = set()
        self._next_id = 1000
        self._current_id = None
        self.uploaded = []  # (deposition_id, filename)
        self.published = set()  # deposition ids
        self.lost_publish = False
        self.doi_missing = False

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _as_response(spec, default_payload=None):
        if isinstance(spec, FakeResponse):
            return spec
        return FakeResponse(spec, {'message': 'error'})

    def doi_for(self, deposition_id):
        return f'10.5281/zenodo.{deposition_id}'

    def calls_to(self, suffix):
        return [c for c in self.calls if c['url'].split('?')[0].endswith(suffix)]

    # -- patched entry points ------------------------------------------------
    def get(self, url, params=None, **kwargs):
        self.calls.append({'method': 'GET', 'url': url, 'params': params})
        path = url.split('?')[0]
        if path.endswith('/api/deposit/depositions'):
            if self.fail_list is not None:
                return self._as_response(self.fail_list)
            return FakeResponse(200, [])
        if path.endswith('/files'):
            if self.fail_listing is not None:
                return self._as_response(self.fail_listing)
            deposition_id = int(path.split('/depositions/')[1].split('/')[0])
            return FakeResponse(200, [
                {'filename': name} for dep, name in self.uploaded if dep == deposition_id
            ])
        if self.fail_get is not None:
            return self._as_response(self.fail_get)
        deposition_id = int(path.rsplit('/', 1)[-1])
        return FakeResponse(200, {
            'id': deposition_id,
            'doi': '' if self.doi_missing else self.doi_for(deposition_id),
            'submitted': deposition_id in self.published,
        })

    def post(self, url, params=None, json=None, headers=None, data=None, files=None, **kwargs):
        record = {
            'method': 'POST', 'url': url, 'params': params, 'json': json,
            'headers': headers, 'data': data,
        }
        self.calls.append(record)
        path = url.split('?')[0]

        if path.endswith('/api/deposit/depositions'):
            if self.fail_create is not None:
                return self._as_response(self.fail_create)
            if json is not None and json.get('metadata', {}).get('title') in self.fail_titles:
                return FakeResponse(400, {'message': 'bad metadata'})
            self._current_id = self._next_id
            self._next_id += 1
            record['deposition_id'] = self._current_id
            return FakeResponse(201, {'id': self._current_id})

        if path.endswith('/files'):
            filename = (data or {}).get('filename')
            record['filename'] = filename
            if files is not None:
                # Read the stream like requests would, so size/handle issues surface.
                files['file'].read(1)
            deposition_id = int(path.split('/depositions/')[1].split('/')[0])
            record['deposition_id'] = deposition_id
            if filename in self.fail_files:
                return self._as_response(self.fail_files[filename])
            if self.fail_pdf is not None and filename.endswith('.pdf'):
                return self._as_response(self.fail_pdf)
            self.uploaded.append((deposition_id, filename))
            return FakeResponse(201, {'filename': filename})

        if path.endswith('/actions/publish'):
            record['deposition_id'] = int(path.split('/depositions/')[1].split('/')[0])
            if self.lost_publish:
                self.published.add(record['deposition_id'])
                return FakeResponse(500, {'message': 'timeout'})
            if self.fail_publish is not None:
                return self._as_response(self.fail_publish)
            self.published.add(record['deposition_id'])
            return FakeResponse(202, {'id': record['deposition_id']})

        raise AssertionError(f'Unexpected POST to {url}')


def csv_row(key='nime2025_1', title='A Title', authors='Doe, Jane', pdf=None, **fields):
    """Build a CSV row (dict). ``None`` values become empty cells.

    ``pdf`` defaults to ``<key>.pdf``; ``authors`` uses ``;`` as separator.
    """
    values = {'key': key, 'pdf': f'{key}.pdf' if pdf is None else pdf,
              'title': title, 'authors': authors}
    values.update(fields)
    return {name: ('' if value is None else value) for name, value in values.items()}


class WorkspaceTestCase(unittest.TestCase):
    """Runs each test inside a temp dir with ``upload/``, ``secrets.toml`` and ``conference.toml``.

    The program module is imported fresh for every test (it has import-time side
    effects) and exposed as ``self.app``. If the refactoring changes how the
    program is loaded, this class is the only place to adapt.
    """

    write_secrets = True
    write_conference = True

    def setUp(self):
        self._old_cwd = os.getcwd()
        self._old_module = sys.modules.pop(MODULE_NAME, None)
        self.tmp = tempfile.mkdtemp(prefix='zenodo_test_')
        os.chdir(self.tmp)
        os.mkdir('upload')
        if self.write_secrets:
            with open('secrets.toml', 'w') as f:
                f.write(f"PUBLIC_TOKEN = '{PUBLIC_TOKEN}'\nSANDBOX_TOKEN = '{SANDBOX_TOKEN}'\n")
        if self.write_conference:
            with open('conference.toml', 'w') as f:
                f.write(CONFERENCE_TOML)

        self.fake = FakeZenodo()
        for name, target in (('get', self.fake.get), ('post', self.fake.post)):
            patcher = mock.patch(f'requests.{name}', side_effect=target)
            patcher.start()
            self.addCleanup(patcher.stop)

        if self.write_secrets and self.write_conference:
            self.app = importlib.import_module(MODULE_NAME)

    def tearDown(self):
        os.chdir(self._old_cwd)
        sys.modules.pop(MODULE_NAME, None)
        if self._old_module is not None:
            sys.modules[MODULE_NAME] = self._old_module
        shutil.rmtree(self.tmp, ignore_errors=True)

    def reload_app(self):
        """Import the program again, as a new process would see it."""
        sys.modules.pop(MODULE_NAME, None)
        self.app = importlib.import_module(MODULE_NAME)

    # -- file helpers ---------------------------------------------------------
    def write_csv(self, *rows, name='test.csv', encoding='utf-8'):
        """Write rows (dicts, see :func:`csv_row`) to upload/<name>; header = union of keys."""
        fieldnames = []
        for row in rows:
            for column in row:
                if column not in fieldnames:
                    fieldnames.append(column)
        path = os.path.join('upload', name)
        with open(path, 'w', encoding=encoding, newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, restval='')
            writer.writeheader()
            writer.writerows(rows)
        self.last_csv = path
        return path

    def make_file(self, name, content=b'%PDF-1.4 test'):
        with open(os.path.join('upload', name), 'wb') as f:
            f.write(content)

    def copy_fixture(self, name, source_dir=FIXTURES_DIR):
        """Copy <source_dir>/<name> (default tests/fixtures) into upload/ and create the PDFs its rows name.

        Returns the path of the copied .csv file.
        """
        dest = os.path.join('upload', name)
        shutil.copy(os.path.join(source_dir, name), dest)
        self.last_csv = dest
        with open(dest, encoding='utf-8', newline='') as f:
            for row in csv.DictReader(f):
                if row.get('pdf'):
                    self.make_file(row['pdf'])
        return dest

    def make_pdf(self, key='nime2025_1'):
        self.make_file(f'{key}.pdf')

    def read_state(self, path=None):
        """Rows (dicts) of a CSV file as the program left it; default: the last one written."""
        with open(path or self.last_csv, encoding='utf-8', newline='') as f:
            return list(csv.DictReader(f))

    def done_rows(self, path=None):
        """(pdf, deposition_id, doi) of the rows whose status is done, in file order."""
        return [
            (row['pdf'], row['deposition_id'], row['doi'])
            for row in self.read_state(path) if row.get('status') == 'done'
        ]

    # -- inspection helpers -------------------------------------------------------
    def created_depositions(self):
        """JSON bodies of every deposition-creation request, in order."""
        return [
            c['json'] for c in self.fake.calls
            if c['method'] == 'POST' and c['url'].split('?')[0].endswith('/api/deposit/depositions')
        ]

    def created_metadata(self):
        return [body['metadata'] for body in self.created_depositions()]

    def call_summary(self):
        """Compact (method, endpoint) list: 'list', 'create', 'file', 'publish', 'get'."""
        names = []
        for c in self.fake.calls:
            path = c['url'].split('?')[0]
            if path.endswith('/files'):
                names.append((c['method'], 'file'))
            elif path.endswith('/actions/publish'):
                names.append((c['method'], 'publish'))
            elif path.endswith('/api/deposit/depositions'):
                names.append((c['method'], 'list' if c['method'] == 'GET' else 'create'))
            else:
                names.append((c['method'], 'get'))
        return names

    @staticmethod
    def call_token(call):
        """Access token of a recorded call (query param or part of the URL)."""
        if call.get('params') and 'access_token' in call['params']:
            return call['params']['access_token']
        query = urllib.parse.urlparse(call['url']).query
        return urllib.parse.parse_qs(query)['access_token'][0]

    # -- invocation helpers -----------------------------------------------------
    def run_cli(self, *argv):
        """Run ``main(argv)`` in-process; unexpected exceptions give exit code 1."""
        out = io.StringIO()
        exit_code, exception = 0, None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                self.app.main(list(argv))
            except SystemExit as e:
                exit_code = e.code if isinstance(e.code, int) else 1
            except (Exception, KeyboardInterrupt) as e:
                exit_code, exception = 1, e
        return CliResult(exit_code, out.getvalue(), exception)

    def run_upload(self, csv_path, *args):
        with mock.patch('builtins.input', return_value=''):
            return self.run_cli('upload', csv_path, *args)

    def run_check(self, csv_path, *args):
        return self.run_cli('check', csv_path, *args)


def fake_sizes(sizes):
    """Return an os.path.getsize replacement reporting ``sizes[basename]`` bytes.

    Avoids creating 100 MB files; other files report their real size.
    """
    real = os.path.getsize

    def fake(path):
        return sizes.get(os.path.basename(str(path)), None) or real(path)

    return fake
