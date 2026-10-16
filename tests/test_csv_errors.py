import unittest
from unittest import mock

from tests.support import MB, WorkspaceTestCase, csv_row, fake_sizes


class TestInvalidCsv(WorkspaceTestCase):
    # An unusable CSV is rejected as a whole, before any network call, and the
    # message lists every problem found.

    def assert_rejected(self, result, *expected):
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIsNone(result.exception, result.output)
        for text in expected:
            self.assertIn(text, result.output)
        self.assertEqual(self.fake.calls, [])

    def test_empty_title_is_rejected(self):
        self.make_pdf()
        path = self.write_csv(csv_row(title=''))

        self.assert_rejected(self.run_check(path), 'row 2', 'empty title')

    def test_empty_authors_are_rejected(self):
        self.make_pdf()
        path = self.write_csv(csv_row(authors=''))

        self.assert_rejected(self.run_check(path), 'row 2', 'empty authors')

    def test_empty_pdf_is_rejected(self):
        path = self.write_csv(csv_row(pdf=''))

        self.assert_rejected(self.run_check(path), 'row 2', 'empty pdf')

    def test_empty_key_is_rejected(self):
        self.make_pdf()
        path = self.write_csv(csv_row(key='', pdf='nime2025_1.pdf'))

        self.assert_rejected(self.run_check(path), 'row 2', 'no key', 'empty key')

    def test_duplicate_key_is_rejected(self):
        self.make_pdf('nime2025_1')
        self.make_pdf('nime2025_2')
        path = self.write_csv(
            csv_row(key='nime2025_1'), csv_row(key='nime2025_2'),
            csv_row(key='nime2025_1', pdf='nime2025_2.pdf'),
        )

        self.assert_rejected(self.run_check(path), 'row 4', 'duplicate key')

    def test_missing_required_column_is_rejected(self):
        self.make_pdf()
        row = csv_row()
        del row['title']
        path = self.write_csv(row)

        self.assert_rejected(self.run_check(path), 'missing column', 'title')

    def test_file_without_header_or_rows_is_rejected(self):
        with open('upload/empty.csv', 'w') as f:
            f.write('')

        self.assert_rejected(self.run_check('upload/empty.csv'), 'missing column')

    def test_affiliations_must_match_the_number_of_authors(self):
        self.make_pdf()
        path = self.write_csv(csv_row(authors='Doe, Jane; Roe, Rick', affiliations='UNIMI'))

        self.assert_rejected(self.run_check(path), 'row 2', 'affiliations')

    def test_all_problems_are_reported_together(self):
        path = self.write_csv(
            csv_row(key='a', title=''), csv_row(key='b', authors=''), csv_row(key='c', pdf='')
        )

        self.assert_rejected(
            self.run_check(path), 'row 2', 'empty title', 'row 3', 'empty authors',
            'row 4', 'empty pdf',
        )

    def test_one_invalid_row_stops_the_whole_run_before_any_upload(self):
        for key in ('nime2025_1', 'nime2025_2', 'nime2025_3'):
            self.make_pdf(key)
        path = self.write_csv(
            csv_row(key='nime2025_1'),
            csv_row(key='nime2025_2', title=''),
            csv_row(key='nime2025_3'),
        )

        with open(path, 'rb') as f:
            before = f.read()

        result = self.run_upload(path)

        self.assert_rejected(result, 'row 3')
        self.assertEqual(self.created_depositions(), [])
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), before)

    def test_upload_does_not_ask_for_confirmation_on_an_unusable_file(self):
        self.make_pdf()
        path = self.write_csv(csv_row(title=''))

        with mock.patch('builtins.input') as prompt:
            result = self.run_cli('upload', path)

        prompt.assert_not_called()
        self.assertEqual(result.exit_code, 1)


class TestMissingPdf(WorkspaceTestCase):
    def test_check_reports_a_missing_pdf_and_fails(self):
        # `check` also requires the PDFs to be present.
        path = self.write_csv(csv_row(key='nime2025_1'))

        result = self.run_check(path)

        self.assertEqual(result.exit_code, 1)
        self.assertIsNone(result.exception, result.output)
        self.assertIn('nime2025_1.pdf', result.output)
        self.assertNotIn('Traceback', result.output)

    def test_upload_lists_all_missing_pdfs_and_calls_nothing(self):
        self.make_pdf('nime2025_2')
        path = self.write_csv(
            csv_row(key='nime2025_1'),
            csv_row(key='nime2025_2'),
            csv_row(key='nime2025_3'),
        )

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 1)
        self.assertIsNone(result.exception, result.output)
        self.assertIn('nime2025_1.pdf', result.output)
        self.assertIn('nime2025_3.pdf', result.output)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.done_rows(), [])


class TestOversizedPdf(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.make_pdf('nime2025_1')
        self.make_pdf('nime2025_2')
        self.csv = self.write_csv(
            csv_row(key='nime2025_1'), csv_row(key='nime2025_2')
        )

    def patch_sizes(self, sizes):
        patcher = mock.patch('os.path.getsize', side_effect=fake_sizes(sizes))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pdf_over_limit_aborts_before_any_upload(self):
        self.patch_sizes({'nime2025_2.pdf': 100 * MB + 1})

        result = self.run_upload(self.csv)

        self.assertEqual(result.exit_code, 1)
        self.assertIsNone(result.exception, result.output)
        self.assertIn('nime2025_2.pdf', result.output)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.done_rows(), [])

    def test_pdf_exactly_at_limit_is_accepted(self):
        self.patch_sizes({'nime2025_1.pdf': 100 * MB, 'nime2025_2.pdf': 100 * MB})

        result = self.run_upload(self.csv)

        self.assertIsNone(result.exception, result.output)
        self.assertEqual(len(self.done_rows()), 2)

    def test_check_does_not_enforce_pdf_size(self):
        self.patch_sizes({'nime2025_1.pdf': 500 * MB})

        result = self.run_check(self.csv)

        self.assertIsNone(result.exception, result.output)


if __name__ == '__main__':
    unittest.main()
