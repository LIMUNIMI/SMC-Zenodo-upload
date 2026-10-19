"""Tests against the real Zenodo sandbox; skipped unless secrets.toml has a SANDBOX_TOKEN."""

import glob
import os
import re
import unittest
from unittest import mock

from tests.live import LiveTestCase, sandbox_token
from tests.support import MB, csv_row, fake_sizes
from zenodo_upload.zenodo import SERVERS, AccessError, ZenodoClient


class TestSandboxTokenDetection(unittest.TestCase):
    """Offline: when the live tests run or are skipped."""

    def token_with(self, secrets):
        with mock.patch('tests.live._repo_toml', return_value=secrets):
            return sandbox_token()

    def test_a_real_token_is_found(self):
        self.assertEqual(self.token_with({'SANDBOX_TOKEN': 'abc123'}), 'abc123')

    def test_missing_empty_or_placeholder_tokens_mean_no_live_tests(self):
        for secrets in (
            {}, {'SANDBOX_TOKEN': ''}, {'PUBLIC_TOKEN': 'abc'},
            {'SANDBOX_TOKEN': 'replace-with-your-zenodo-sandbox-token'},
        ):
            with self.subTest(secrets=secrets):
                self.assertIsNone(self.token_with(secrets))


class TestLiveAccess(LiveTestCase):
    """No record is left on the server by these tests."""

    def test_the_token_is_accepted(self):
        self.client.check_access()  # raises AccessError otherwise

    def test_a_wrong_token_is_refused(self):
        client = ZenodoClient('sandbox', SERVERS['sandbox'][0], 'not-a-valid-token')

        with self.assertRaises(AccessError) as caught:
            client.check_access()

        # The sandbox answers 403 (not 401) to an invalid token.
        self.assertRegex(str(caught.exception), r'HTTP (401|403)')

    def test_upload_with_a_wrong_token_changes_nothing(self):
        self.write_live_config(token='not-a-valid-token')
        self.make_pdf()
        path = self.write_csv(csv_row(title=self.live_title()))
        with open(path, 'rb') as f:
            before = f.read()

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn('Cannot access', result.output)
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(glob.glob('upload/*.bak'), [])

    def test_metadata_refused_by_the_server_is_recorded_as_a_create_failure(self):
        self.write_live_config(LICENSE='not-a-licence')
        self.make_pdf()
        path = self.write_csv(csv_row(title=self.live_title()))

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 1, result.output)
        [row] = self.read_state()
        self.assertEqual((row['status'], row['deposition_id']), ('pending', ''))
        self.assertEqual(row['error'], 'create failed: HTTP 400')
        self.assertEqual(self.find_test_drafts(), [])


class TestLiveDrafts(LiveTestCase):
    """Real drafts in the conference's community; they are deleted at the end of every test."""

    def setUp(self):
        super().setUp()
        self.require_community()

    def test_upload_creates_a_draft_with_the_metadata_and_the_files(self):
        self.upload_one('p1_file01.txt')

        [row] = self.read_state()
        self.assertEqual((row['status'], row['server'], row['skipped_files']), ('uploaded', 'sandbox', ''))
        self.assertRegex(row['deposition_id'], r'^\d+$')
        draft = self.deposition()
        self.assertFalse(draft['submitted'])
        self.assertEqual(draft['state'], 'unsubmitted')
        self.assertEqual(self.file_names(), {'p1.pdf', 'p1_file01.txt'})

        conference = self.app.CONFERENCE
        expected = {
            'title': self.title,
            'upload_type': 'publication',
            'publication_type': 'conferencepaper',
            'description': 'An abstract.',
            'license': conference.license,
            'access_right': conference.access_right,
            'imprint_publisher': conference.publisher,
            'imprint_isbn': conference.isbn,
            'partof_title': conference.proceedings_title,
            'partof_pages': '1--8',
            'publication_date': conference.publication_date,
            'conference_title': conference.title,
            'conference_acronym': conference.acronym,
            'conference_dates': conference.dates,
            'conference_place': conference.place,
            'conference_url': conference.url,
            'conference_session': 'Paper Session 1',
        }
        metadata = draft['metadata']
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(metadata.get(key), value)
        with self.subTest(key='creators'):
            self.assertEqual(
                [(c['name'], c.get('affiliation')) for c in metadata['creators']],
                [('Doe, Jane', 'University A'), ('Roe, Richard', None)],
            )
        # Characterization: the deposit API has no such fields, it silently drops them.
        for key in ('imprint_issn', 'imprint_title'):
            with self.subTest(key=key, dropped_by_zenodo=True):
                self.assertNotIn(key, metadata)
        with self.subTest(key='communities'):
            self.assertIn({'identifier': self.community}, metadata['communities'])

    def test_a_supplementary_file_over_the_limit_is_skipped_and_recorded(self):
        self.make_pdf('p1')
        self.make_file('p1_big.mp4')
        path = self.write_csv(csv_row(key='p1', title=self.title))

        with mock.patch('os.path.getsize', side_effect=fake_sizes({'p1_big.mp4': 150 * MB})):
            result = self.run_upload(path)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.read_state()[0]['skipped_files'], 'p1_big.mp4')
        self.assertEqual(self.file_names(), {'p1.pdf'})

    def test_a_second_upload_does_nothing(self):
        path = self.upload_one()
        deposition_id = self.read_state()[0]['deposition_id']

        with mock.patch.object(
            ZenodoClient, 'create', autospec=True, side_effect=ZenodoClient.create
        ) as create:
            result = self.run_upload(path)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('Nothing to upload', result.output)
        create.assert_not_called()
        self.assertEqual(self.read_state()[0]['deposition_id'], deposition_id)

    def test_a_row_that_stopped_after_creation_resumes_on_the_same_draft(self):
        path = self.upload_one()
        deposition_id = self.read_state()[0]['deposition_id']
        self.set_status(path, 'created')

        with mock.patch.object(
            ZenodoClient, 'upload_file', autospec=True, side_effect=ZenodoClient.upload_file
        ) as upload_file:
            result = self.run_upload(path)

        self.assertEqual(result.exit_code, 0, result.output)
        upload_file.assert_not_called()  # the PDF is already on the draft
        [row] = self.read_state()
        self.assertEqual((row['status'], row['deposition_id']), ('uploaded', deposition_id))
        self.assertEqual(self.file_names(), {'p1.pdf'})

    def test_publish_refuses_a_row_that_is_not_uploaded(self):
        path = self.upload_one()
        self.set_status(path, 'created')

        result = self.run_publish(path)

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn('Cannot publish', result.output)
        self.assertEqual(self.read_state()[0]['status'], 'created')
        self.assertFalse(self.deposition()['submitted'])


# The record published on the sandbox by TestLivePublish (last run 2026-10-19). If the sandbox is
# reset, run that test again (see README) and put the new id here.
REFERENCE_RECORD_ID = 622796


class TestLiveRecord(LiveTestCase):
    """Read-only: the published reference record has the metadata the program sends."""

    def setUp(self):
        super().setUp()
        self.record = self.published_record(REFERENCE_RECORD_ID)
        if self.record is None:
            self.skipTest(
                f'reference record {REFERENCE_RECORD_ID} not found on the sandbox: run '
                'TestLivePublish (ZENODO_LIVE_PUBLISH=1) and update REFERENCE_RECORD_ID'
            )

    def test_the_published_metadata_is_correct(self):
        self.assert_published_metadata(self.record)

    def test_the_record_has_its_doi(self):
        self.assertEqual(
            self.record['pids']['doi']['identifier'], f'10.5072/zenodo.{REFERENCE_RECORD_ID}'
        )

    def test_the_record_is_in_the_community_or_waits_for_its_review(self):
        self.assertIn(self.community_state(self.record), ('included', 'requested'))


@unittest.skipUnless(
    os.environ.get('ZENODO_LIVE_PUBLISH') == '1',
    'creates a permanent record on the sandbox: set ZENODO_LIVE_PUBLISH=1 to run it',
)
class TestLivePublish(LiveTestCase):
    """The only live test that publishes: the record stays on the sandbox for good."""

    def test_upload_then_publish_gives_a_doi(self):
        self.require_community()
        path = self.upload_one('p1_file01.txt')
        deposition_id = self.read_state()[0]['deposition_id']

        result = self.run_publish(path)

        self.assertEqual(result.exit_code, 0, result.output)
        [row] = self.read_state()
        self.assertEqual((row['status'], row['error']), ('done', ''))
        self.assertRegex(row['doi'], r'^10\.\d+/zenodo\.\d+$')
        self.assertTrue(row['doi'].endswith(f'.{deposition_id}'), row['doi'])
        record = self.deposition()
        self.assertTrue(record['submitted'])
        self.assertEqual(record['state'], 'done')
        self.assertEqual(record['doi'], row['doi'])
        self.assertEqual(self.file_names(), {'p1.pdf', 'p1_file01.txt'})
        # What the program reads from Zenodo, and FakeZenodo imitates.
        self.assertLessEqual({'id', 'doi', 'submitted', 'state'}, set(record))

        self.assert_published_metadata(self.published_record(deposition_id))
        self.assertIn(self.community_state(self.published_record(deposition_id)),
                      ('included', 'requested'))

        again = self.run_publish(path)

        self.assertEqual(again.exit_code, 0, again.output)
        self.assertIn('Nothing to publish', again.output)


if __name__ == '__main__':
    unittest.main()
