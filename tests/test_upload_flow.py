import unittest

from tests.support import (
    PUBLIC_TOKEN, SANDBOX_TOKEN, FakeResponse, WorkspaceTestCase, csv_row,
)


class TestUploadHappyPath(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.make_pdf('nime2025_1')
        self.bib = self.write_csv(csv_row(key='nime2025_1', title='Happy'))

    def test_api_call_sequence(self):
        result = self.run_full(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertEqual(
            self.call_summary(),
            [
                ('GET', 'list'),
                ('POST', 'create'),
                ('POST', 'file'),
                ('GET', 'list'),
                ('POST', 'publish'),
                ('GET', 'get'),
            ],
        )

    def test_upload_stops_at_the_draft_and_publish_completes_it(self):
        result = self.run_upload(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertEqual(
            self.call_summary(), [('GET', 'list'), ('POST', 'create'), ('POST', 'file')]
        )
        self.assertEqual(self.fake.calls_to('/actions/publish'), [])
        self.assertEqual(self.read_state()[0]['status'], 'uploaded')
        self.assertEqual(self.read_state()[0]['doi'], '')
        self.assertIn('run `publish`', result.output)

        result = self.run_publish(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertEqual(len(self.fake.calls_to('/actions/publish')), 1)
        self.assertEqual(self.done_rows(), [('nime2025_1.pdf', '1000', '10.5281/zenodo.1000')])

    def test_sandbox_is_the_default_target_and_uses_sandbox_token(self):
        self.run_full(self.bib)

        self.assertTrue(self.fake.calls)
        for call in self.fake.calls:
            self.assertTrue(call['url'].startswith('https://sandbox.zenodo.org/api/deposit/depositions'))
            self.assertEqual(self.call_token(call), SANDBOX_TOKEN)

    def test_production_flag_uses_production_server_and_public_token(self):
        self.run_full(self.bib, '--production')

        self.assertTrue(self.fake.calls)
        for call in self.fake.calls:
            self.assertTrue(call['url'].startswith('https://zenodo.org/api/deposit/depositions'))
            self.assertEqual(self.call_token(call), PUBLIC_TOKEN)

    def test_token_travels_in_the_header_never_in_the_url(self):
        self.run_upload(self.bib)

        self.assertTrue(self.fake.calls)
        for call in self.fake.calls:
            self.assertTrue(call['auth'].startswith('Bearer '))
            self.assertNotIn('access_token', call['url'])

    def test_create_request_sends_json_with_metadata(self):
        self.run_full(self.bib)

        create = [c for c in self.fake.calls if c['method'] == 'POST' and c['json']][0]
        self.assertEqual(create['headers'], {'Content-Type': 'application/json'})
        self.assertEqual(create['json']['metadata']['title'], 'Happy')

    def test_pdf_is_uploaded_to_the_created_deposition(self):
        self.run_full(self.bib)

        self.assertEqual(self.fake.uploaded, [(1000, 'nime2025_1.pdf')])
        file_call = [c for c in self.fake.calls if 'filename' in c][0]
        self.assertIn('/api/deposit/depositions/1000/files', file_call['url'])

    def test_publish_targets_the_created_deposition(self):
        self.run_full(self.bib)

        publish = self.fake.calls_to('/actions/publish')
        self.assertEqual(len(publish), 1)
        self.assertIn('/depositions/1000/actions/publish', publish[0]['url'])

    def test_doi_is_recorded_in_the_csv_with_deposition_id(self):
        self.run_full(self.bib)

        self.assertEqual(self.done_rows(), [('nime2025_1.pdf', '1000', '10.5281/zenodo.1000')])

    def test_success_is_reported(self):
        result = self.run_full(self.bib)

        self.assertIn('PUBLISHED with ID 1000', result.output)
        self.assertIn('10.5281/zenodo.1000', result.output)

    def test_multiple_entries_are_processed_in_bib_order(self):
        for n in (2, 3):
            self.make_pdf(f'nime2025_{n}')
        bib = self.write_csv(
            csv_row(key='nime2025_3'),
            csv_row(key='nime2025_1'),
            csv_row(key='nime2025_2'),
            name='multi.csv',
        )

        self.run_full(bib)

        self.assertEqual(
            self.done_rows(),
            [
                ('nime2025_3.pdf', '1000', '10.5281/zenodo.1000'),
                ('nime2025_1.pdf', '1001', '10.5281/zenodo.1001'),
                ('nime2025_2.pdf', '1002', '10.5281/zenodo.1002'),
            ],
        )


class TestUploadFailures(WorkspaceTestCase):
    """Failures at one stage skip that entry and continue with the next."""

    def setUp(self):
        super().setUp()
        self.make_pdf('nime2025_1')
        self.make_pdf('nime2025_2')
        self.bib = self.write_csv(
            csv_row(key='nime2025_1', title='First'),
            csv_row(key='nime2025_2', title='Second'),
        )

    def test_create_failure_skips_entry_and_continues(self):
        self.fake.fail_titles = {'First'}

        result = self.run_full(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertIn('Error happened during submission', result.output)
        self.assertEqual(self.fake.uploaded, [(1000, 'nime2025_2.pdf')])
        self.assertEqual(self.done_rows(), [('nime2025_2.pdf', '1000', '10.5281/zenodo.1000')])

    def test_refused_token_is_reported_and_nothing_is_created(self):
        self.fake.fail_list = 401

        result = self.run_full(self.bib)

        self.assertEqual(result.exit_code, 1)
        self.assertIsNone(result.exception, result.output)
        self.assertIn('Cannot access Zenodo', result.output)
        self.assertEqual(self.created_depositions(), [])
        rows = self.read_state()
        self.assertEqual([r['status'] for r in rows], ['pending', 'pending'])
        self.assertEqual({r['error'] for r in rows}, {'access check failed: HTTP 401'})

    def test_create_failure_stops_further_calls_for_that_entry(self):
        self.fake.fail_create = 400
        self.run_full(self.bib)

        self.assertEqual(
            self.call_summary(),
            [('GET', 'list'), ('POST', 'create'), ('GET', 'list'), ('POST', 'create')],
        )
        self.assertEqual(self.done_rows(), [])

    def test_pdf_upload_failure_skips_entry_without_publishing(self):
        self.fake.fail_files = {'nime2025_1.pdf': 500}

        result = self.run_full(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertIn('Error happened during file upload of nime2025_1.pdf', result.output)
        publish = self.fake.calls_to('/actions/publish')
        self.assertEqual(len(publish), 1)
        self.assertIn('/depositions/1001/', publish[0]['url'])
        self.assertEqual(self.done_rows(), [('nime2025_2.pdf', '1001', '10.5281/zenodo.1001')])

    def test_publish_failure_records_nothing_and_continues(self):
        self.fake.fail_publish = 500

        result = self.run_full(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertIn('Error happened during publish', result.output)
        self.assertEqual(len(self.fake.calls_to('/actions/publish')), 2)
        self.assertEqual(self.done_rows(), [])
        self.assertNotIn('PUBLISHED', result.output)

    def test_status_210_is_success_and_211_is_failure(self):
        self.fake.fail_create = FakeResponse(210, {'id': 4242})
        result = self.run_full(self.bib)
        self.assertNotIn('Error happened during submission', result.output)

        self.reload_app()
        self.fake.calls.clear()
        self.fake.fail_create = FakeResponse(211, {'message': 'nope'})
        self.write_csv(  # start again from clean rows
            csv_row(key='nime2025_1', title='First'),
            csv_row(key='nime2025_2', title='Second'),
        )
        result = self.run_full(self.bib)
        self.assertIn('Error happened during submission', result.output)

    def test_json_error_body_is_printed(self):
        self.fake.fail_create = FakeResponse(400, {'message': 'Validation error XYZ'})

        result = self.run_full(self.bib)

        self.assertIn('Validation error XYZ', result.output)

    def test_html_error_body_is_printed_raw(self):
        self.fake.fail_publish = FakeResponse(
            413, text='<html><body>413 Request Entity Too Large</body></html>'
        )

        result = self.run_full(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertIn('413 Request Entity Too Large', result.output)


if __name__ == '__main__':
    unittest.main()
