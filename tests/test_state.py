"""State kept in the CSV file: steps, resume, server handling and safety guards."""

import os
import unittest
from unittest import mock

from tests.support import MB, FakeResponse, WorkspaceTestCase, csv_row, fake_sizes


class StateTestCase(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        for key in ('nime2025_1', 'nime2025_2'):
            self.make_pdf(key)

    def row(self, index=0):
        return self.read_state()[index]

    def post_summary(self):
        return [name for method, name in self.call_summary() if method == 'POST']

    def run_again(self, *args):
        self.fake.calls.clear()
        return self.run_upload(self.last_csv, *args)


class TestStateColumns(StateTestCase):
    def test_finished_row_has_all_state_columns_filled(self):
        path = self.write_csv(csv_row(key='nime2025_1'))

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 0, result.output)
        row = self.row()
        self.assertEqual(row['status'], 'done')
        self.assertEqual(row['server'], 'sandbox')
        self.assertEqual(row['deposition_id'], '1000')
        self.assertEqual(row['doi'], '10.5281/zenodo.1000')
        self.assertEqual(row['skipped_files'], '')
        self.assertEqual(row['error'], '')
        self.assertRegex(row['updated_at'], r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')

    def test_production_run_records_production_server(self):
        path = self.write_csv(csv_row(key='nime2025_1'))

        self.run_upload(path, '--production')

        self.assertEqual(self.row()['server'], 'production')

    def test_state_columns_are_appended_and_other_columns_are_preserved(self):
        path = self.write_csv(
            csv_row(key='nime2025_1', track='Papers', Year='2025'),
            csv_row(key='nime2025_2', track='Music', Year='2026'),
        )

        self.run_upload(path)

        with open(path, encoding='utf-8') as f:
            header = f.readline().strip().split(',')
        self.assertEqual(
            header,
            ['key', 'pdf', 'title', 'authors', 'track', 'year',
             'status', 'server', 'deposition_id', 'doi', 'skipped_files', 'error', 'updated_at'],
        )
        self.assertEqual([r['track'] for r in self.read_state()], ['Papers', 'Music'])
        self.assertEqual([r['year'] for r in self.read_state()], ['2025', '2026'])

    def test_existing_state_columns_keep_their_position(self):
        path = self.write_csv(csv_row(key='nime2025_1', status='', doi='', track='Papers'))

        self.run_upload(path)

        with open(path, encoding='utf-8') as f:
            header = f.readline().strip().split(',')
        self.assertEqual(header[4:7], ['status', 'doi', 'track'])
        self.assertEqual(self.row()['status'], 'done')

    def test_doi_from_the_bib_is_replaced(self):
        path = self.write_csv(csv_row(key='nime2025_1', doi='10.5281/zenodo.OLD'))

        self.run_upload(path)

        self.assertEqual(self.row()['doi'], '10.5281/zenodo.1000')

    def test_values_are_written_back_unchanged_for_untouched_rows(self):
        path = self.write_csv(
            csv_row(key='nime2025_1', abstract='Line one\nLine two, with comma', title='Q "x"'),
            csv_row(key='nime2025_2', status='done', server='sandbox', deposition_id='7',
                    doi='10.5281/zenodo.7'),
        )

        self.run_upload(path)

        first = self.row(0)
        self.assertEqual(first['abstract'], 'Line one\nLine two, with comma')
        self.assertEqual(first['title'], 'Q "x"')

    def test_check_does_not_add_or_change_anything(self):
        path = self.write_csv(csv_row(key='nime2025_1'))
        with open(path, 'rb') as f:
            before = f.read()

        self.run_check(path)

        with open(path, 'rb') as f:
            self.assertEqual(f.read(), before)

    def test_no_temporary_file_is_left_behind(self):
        path = self.write_csv(csv_row(key='nime2025_1'))

        self.run_upload(path)

        self.assertEqual(
            sorted(f for f in os.listdir('upload') if f.endswith('.tmp')), []
        )

    def test_backup_of_the_original_is_made_before_the_first_change(self):
        path = self.write_csv(csv_row(key='nime2025_1'))
        with open(path, 'rb') as f:
            original = f.read()

        self.run_upload(path)

        with open(path + '.bak', 'rb') as f:
            self.assertEqual(f.read(), original)

    def test_no_backup_for_check_or_rejected_file(self):
        path = self.write_csv(csv_row(key='nime2025_1', title=''))

        self.run_check(path)
        self.run_upload(path)

        self.assertFalse(os.path.exists(path + '.bak'))


class TestResume(StateTestCase):
    def test_done_rows_are_skipped_without_any_call(self):
        path = self.write_csv(csv_row(key='nime2025_1'))
        self.run_upload(path)

        result = self.run_again()

        self.assertEqual(self.fake.calls, [])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('Nothing to upload', result.output)
        self.assertEqual(self.row()['deposition_id'], '1000')

    def test_only_the_missing_rows_are_uploaded(self):
        path = self.write_csv(
            csv_row(key='nime2025_1', status='done', server='sandbox', deposition_id='7',
                    doi='10.5281/zenodo.7'),
            csv_row(key='nime2025_2'),
        )

        result = self.run_upload(path)

        self.assertIn('Skipping nime2025_1.pdf: already done', result.output)
        self.assertEqual(self.fake.uploaded, [(1000, 'nime2025_2.pdf')])
        self.assertEqual(
            self.done_rows(),
            [('nime2025_1.pdf', '7', '10.5281/zenodo.7'),
             ('nime2025_2.pdf', '1000', '10.5281/zenodo.1000')],
        )

    def test_done_rows_do_not_need_their_pdf_any_more(self):
        os.remove('upload/nime2025_1.pdf')
        path = self.write_csv(
            csv_row(key='nime2025_1', status='done', server='sandbox', deposition_id='7',
                    doi='10.5281/zenodo.7'),
            csv_row(key='nime2025_2'),
        )

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(len(self.done_rows()), 2)

    def test_pdf_failure_keeps_the_draft_and_the_next_run_reuses_it(self):
        path = self.write_csv(csv_row(key='nime2025_1'))
        self.fake.fail_files = {'nime2025_1.pdf': 500}
        first = self.run_upload(path)

        self.assertEqual(first.exit_code, 1)
        row = self.row()
        self.assertEqual((row['status'], row['deposition_id']), ('created', '1000'))
        self.assertEqual(row['error'], 'file upload failed: HTTP 500')

        self.fake.fail_files = {}
        second = self.run_again()

        self.assertEqual(second.exit_code, 0, second.output)
        self.assertEqual(self.post_summary(), ['file', 'publish'])  # no new deposition
        self.assertEqual(self.fake.uploaded, [(1000, 'nime2025_1.pdf')])
        row = self.row()
        self.assertEqual((row['status'], row['doi'], row['error']),
                         ('done', '10.5281/zenodo.1000', ''))

    def test_resume_does_not_upload_files_the_draft_already_has(self):
        self.make_file('nime2025_1_file01.mp4')
        self.make_file('nime2025_1_file02.mp4')
        path = self.write_csv(csv_row(key='nime2025_1'))
        self.fake.fail_files = {'nime2025_1.pdf': 500}
        self.run_upload(path)
        # The deposition already has the first supplementary file.
        self.fake.uploaded.append((1000, 'nime2025_1_file01.mp4'))
        self.fake.fail_files = {}

        self.run_again()

        self.assertEqual(
            sorted(name for _, name in self.fake.uploaded),
            ['nime2025_1.pdf', 'nime2025_1_file01.mp4', 'nime2025_1_file02.mp4'],
        )
        sent = [c['filename'] for c in self.fake.calls if 'filename' in c]
        self.assertEqual(sorted(sent), ['nime2025_1.pdf', 'nime2025_1_file02.mp4'])

    def test_publish_failure_is_retried_without_touching_the_files(self):
        path = self.write_csv(csv_row(key='nime2025_1'))
        self.fake.fail_publish = 500
        self.run_upload(path)
        self.assertEqual(self.row()['status'], 'uploaded')
        self.assertEqual(self.row()['error'], 'publish failed: HTTP 500')

        self.fake.fail_publish = None
        result = self.run_again()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.post_summary(), ['publish'])
        self.assertEqual(self.row()['status'], 'done')

    def test_lost_publish_answer_is_recovered_in_the_same_run(self):
        path = self.write_csv(csv_row(key='nime2025_1'))
        self.fake.lost_publish = True

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('published anyway', result.output)
        self.assertEqual(self.row()['status'], 'done')
        self.assertEqual(len(self.fake.calls_to('/actions/publish')), 1)

    def test_published_row_only_fetches_the_doi(self):
        path = self.write_csv(
            csv_row(key='nime2025_1', status='published', server='sandbox', deposition_id='555')
        )

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.post_summary(), [])
        row = self.row()
        self.assertEqual((row['status'], row['doi']), ('done', '10.5281/zenodo.555'))

    def test_missing_doi_leaves_the_row_published_with_an_error(self):
        path = self.write_csv(csv_row(key='nime2025_1'))
        self.fake.doi_missing = True

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 1)
        row = self.row()
        self.assertEqual((row['status'], row['doi'], row['error']),
                         ('published', '', 'doi not available'))

        self.fake.doi_missing = False
        self.run_again()

        self.assertEqual(self.row()['status'], 'done')
        self.assertEqual(len(self.fake.calls_to('/actions/publish')), 0)

    def test_create_failure_leaves_the_row_pending(self):
        path = self.write_csv(csv_row(key='nime2025_1'), csv_row(key='nime2025_2', title='Other'))
        self.fake.fail_titles = {'A Title'}

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 1)
        self.assertEqual([r['status'] for r in self.read_state()], ['pending', 'done'])
        self.assertEqual(self.row(0)['error'], 'create failed: HTTP 400')
        self.assertIn('1 not completed', result.output)

    def test_error_is_cleared_when_the_row_advances(self):
        path = self.write_csv(csv_row(key='nime2025_1'))
        self.fake.fail_create = 500
        self.run_upload(path)
        self.assertNotEqual(self.row()['error'], '')

        self.fake.fail_create = None
        self.run_again()

        self.assertEqual(self.row()['error'], '')

    def test_exit_code_is_zero_when_everything_is_done(self):
        path = self.write_csv(csv_row(key='nime2025_1'), csv_row(key='nime2025_2'))

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 0)
        self.assertIn('Summary: 2 uploaded, 0 already done, 0 not completed.', result.output)

    def test_skipped_supplementary_files_survive_a_resume(self):
        self.make_file('nime2025_1_big.mp4')
        path = self.write_csv(csv_row(key='nime2025_1'))
        with mock.patch('os.path.getsize', side_effect=fake_sizes({'nime2025_1_big.mp4': 150 * MB})):
            self.fake.fail_publish = 500
            self.run_upload(path)
            self.assertEqual(self.row()['skipped_files'], 'nime2025_1_big.mp4')
            self.fake.fail_publish = None
            self.run_again()

        row = self.row()
        self.assertEqual((row['status'], row['skipped_files']), ('done', 'nime2025_1_big.mp4'))


class TestServerHandling(StateTestCase):
    def test_sandbox_rows_restart_on_production(self):
        path = self.write_csv(csv_row(key='nime2025_1'))
        self.run_upload(path)
        self.assertEqual(self.row()['server'], 'sandbox')

        result = self.run_again('--production')

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('restart from scratch on production', result.output)
        self.assertEqual(self.post_summary(), ['create', 'file', 'publish'])
        row = self.row()
        self.assertEqual((row['status'], row['server']), ('done', 'production'))
        self.assertEqual(row['deposition_id'], '1001')

    def test_partial_sandbox_state_is_discarded_on_production(self):
        path = self.write_csv(
            csv_row(key='nime2025_1', status='created', server='sandbox', deposition_id='555')
        )

        self.run_upload(path, '--production')

        self.assertEqual(self.fake.uploaded, [(1000, 'nime2025_1.pdf')])
        self.assertEqual(self.row()['deposition_id'], '1000')

    def test_production_rows_are_protected_from_a_sandbox_run(self):
        path = self.write_csv(
            csv_row(key='nime2025_1', status='done', server='production', deposition_id='9',
                    doi='10.5281/zenodo.9'),
            csv_row(key='nime2025_2'),
        )
        with open(path, 'rb') as f:
            before = f.read()

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 1)
        self.assertIn('nime2025_1', result.output)
        self.assertIn('production', result.output)
        self.assertEqual(self.fake.calls, [])
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), before)

    def test_partial_production_rows_are_protected_too(self):
        path = self.write_csv(
            csv_row(key='nime2025_1', status='published', server='production', deposition_id='9'),
        )

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(self.fake.calls, [])

    def test_production_run_may_resume_production_rows(self):
        path = self.write_csv(
            csv_row(key='nime2025_1', status='published', server='production', deposition_id='9'),
        )

        result = self.run_upload(path, '--production')

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.row()['doi'], '10.5281/zenodo.9')
        self.assertNotIn('restart from scratch', result.output)


class TestStateValidation(StateTestCase):
    def test_unknown_status_is_rejected(self):
        path = self.write_csv(csv_row(key='nime2025_1', status='finished'))

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 1)
        self.assertIn("unknown status 'finished'", result.output)
        self.assertEqual(self.fake.calls, [])

    def test_unknown_server_is_rejected(self):
        path = self.write_csv(csv_row(key='nime2025_1', status='created', server='staging'))

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 1)
        self.assertIn("unknown server 'staging'", result.output)

    def test_missing_pdf_stops_before_any_state_change(self):
        os.remove('upload/nime2025_2.pdf')
        path = self.write_csv(csv_row(key='nime2025_1'), csv_row(key='nime2025_2'))
        with open(path, 'rb') as f:
            before = f.read()

        self.run_upload(path)

        self.assertEqual(self.fake.calls, [])
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), before)
        self.assertFalse(os.path.exists(path + '.bak'))


class TestSavingFailures(StateTestCase):
    def test_unwritable_file_stops_the_run_with_a_clear_message(self):
        path = self.write_csv(csv_row(key='nime2025_1'), csv_row(key='nime2025_2'))

        with mock.patch('os.replace', side_effect=PermissionError('file is locked')):
            result = self.run_upload(path)

        self.assertEqual(result.exit_code, 1)
        self.assertIsNone(result.exception, result.output)
        self.assertIn('Cannot write', result.output)
        self.assertIn('file is locked', result.output)
        # Stopped at the first failed save: no further depositions were started.
        self.assertEqual(len(self.created_depositions()), 1)

    def test_run_after_an_unwritable_file_resumes_from_the_saved_state(self):
        path = self.write_csv(csv_row(key='nime2025_1'))
        with mock.patch('os.replace', side_effect=PermissionError('locked')):
            self.run_upload(path)

        result = self.run_again()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.row()['status'], 'done')


if __name__ == '__main__':
    unittest.main()
