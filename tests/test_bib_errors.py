import unittest
from unittest import mock

from tests.support import MB, WorkspaceTestCase, bib_entry, fake_sizes


class TestMissingBibFields(WorkspaceTestCase):
    # Characterization: a missing mandatory field raises KeyError and aborts the
    # whole run (entries after it are not processed).

    def test_missing_title_raises_key_error(self):
        self.make_pdf()
        bib = self.write_bib(bib_entry(title=None))

        result = self.run_check(bib)

        self.assertIsInstance(result.exception, KeyError)

    def test_missing_url_raises_key_error(self):
        bib = self.write_bib(
            '@inproceedings{k,\n  author = {Doe, Jane},\n  title = {T}\n}\n'
        )

        result = self.run_check(bib)

        self.assertIsInstance(result.exception, KeyError)

    def test_missing_author_raises_key_error(self):
        self.make_pdf()
        bib = self.write_bib(bib_entry(authors=None))

        result = self.run_check(bib)

        self.assertIsInstance(result.exception, KeyError)

    def test_error_aborts_remaining_entries_and_keeps_earlier_uploads(self):
        self.make_pdf('nime2025_1')
        self.make_pdf('nime2025_2')
        self.make_pdf('nime2025_3')
        bib = self.write_bib(
            bib_entry(key='nime2025_1'),
            bib_entry(key='nime2025_2', title=None),
            bib_entry(key='nime2025_3'),
        )

        result = self.run_upload(bib)

        self.assertIsInstance(result.exception, KeyError)
        self.assertEqual(len(self.created_depositions()), 1)
        self.assertEqual(len(self.doi_lines()), 1)
        self.assertTrue(self.doi_lines()[0].startswith('nime2025_1.pdf,'))


class TestMissingPdf(WorkspaceTestCase):
    def test_check_raises_when_pdf_is_missing(self):
        # Characterization: `check` also requires the PDFs to be present.
        bib = self.write_bib(bib_entry(key='nime2025_1'))

        result = self.run_check(bib)

        self.assertIsNotNone(result.exception)
        self.assertIn('nime2025_1.pdf', result.output)

    def test_upload_lists_all_missing_pdfs_and_calls_nothing(self):
        self.make_pdf('nime2025_2')
        bib = self.write_bib(
            bib_entry(key='nime2025_1'),
            bib_entry(key='nime2025_2'),
            bib_entry(key='nime2025_3'),
        )

        result = self.run_upload(bib)

        self.assertIsNone(result.exception, result.output)
        self.assertIn('nime2025_1.pdf', result.output)
        self.assertIn('nime2025_3.pdf', result.output)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.doi_lines(), [])


class TestOversizedPdf(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.make_pdf('nime2025_1')
        self.make_pdf('nime2025_2')
        self.bib = self.write_bib(
            bib_entry(key='nime2025_1'), bib_entry(key='nime2025_2')
        )

    def patch_sizes(self, sizes):
        patcher = mock.patch('os.path.getsize', side_effect=fake_sizes(sizes))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pdf_over_limit_aborts_before_any_upload(self):
        self.patch_sizes({'nime2025_2.pdf': 100 * MB + 1})

        result = self.run_upload(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertIn('nime2025_2.pdf', result.output)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.doi_lines(), [])

    def test_pdf_exactly_at_limit_is_accepted(self):
        self.patch_sizes({'nime2025_1.pdf': 100 * MB, 'nime2025_2.pdf': 100 * MB})

        result = self.run_upload(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertEqual(len(self.doi_lines()), 2)

    def test_check_does_not_enforce_pdf_size(self):
        self.patch_sizes({'nime2025_1.pdf': 500 * MB})

        result = self.run_check(self.bib)

        self.assertIsNone(result.exception, result.output)


if __name__ == '__main__':
    unittest.main()
