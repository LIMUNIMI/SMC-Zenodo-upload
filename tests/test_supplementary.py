import unittest
from unittest import mock

from tests.support import MB, FakeResponse, WorkspaceTestCase, csv_row, fake_sizes


class SupplementaryTestCase(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.make_pdf('nime2025_10')
        self.bib = self.write_csv(csv_row(key='nime2025_10', title='With Extras'))

    def patch_sizes(self, sizes):
        patcher = mock.patch('os.path.getsize', side_effect=fake_sizes(sizes))
        patcher.start()
        self.addCleanup(patcher.stop)

    def uploaded_names(self):
        return sorted(name for _, name in self.fake.uploaded)


class TestSupplementaryMatching(SupplementaryTestCase):
    def test_files_sharing_base_name_and_underscore_are_uploaded(self):
        self.make_file('nime2025_10_file01.mp4')
        self.make_file('nime2025_10_file02.mov')

        result = self.run_upload(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertEqual(
            self.uploaded_names(),
            ['nime2025_10.pdf', 'nime2025_10_file01.mp4', 'nime2025_10_file02.mov'],
        )

    def test_unrelated_files_are_ignored(self):
        self.make_file('nime2025_11.pdf')          # other paper
        self.make_file('nime2025_10.txt')          # no underscore after base name
        self.make_file('nime2025_100_file01.mp4')  # different base name
        self.make_file('other_nime2025_10_x.mp4')  # prefix not at the start

        self.run_upload(self.bib)

        self.assertEqual(self.uploaded_names(), ['nime2025_10.pdf'])

    def test_supplementary_files_are_uploaded_before_publishing(self):
        self.make_file('nime2025_10_file01.mp4')

        self.run_upload(self.bib)

        self.assertEqual(
            self.call_summary(),
            [
                ('GET', 'list'), ('POST', 'create'), ('POST', 'file'),
                ('POST', 'file'), ('POST', 'publish'), ('GET', 'get'),
            ],
        )

    def test_skipped_files_column_is_empty_when_nothing_is_skipped(self):
        self.make_file('nime2025_10_file01.mp4')

        self.run_upload(self.bib)

        self.assertEqual(self.done_rows(), [('nime2025_10.pdf', '1000', '10.5281/zenodo.1000')])
        self.assertEqual(self.read_state()[0]['skipped_files'], '')


class TestOversizedSupplementary(SupplementaryTestCase):
    def test_file_over_limit_is_skipped_and_recorded(self):
        self.make_file('nime2025_10_file01.mp4')
        self.make_file('nime2025_10_file02.mov')
        self.patch_sizes({'nime2025_10_file01.mp4': 100 * MB + 1})

        result = self.run_upload(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertIn('Skipping supplementary file nime2025_10_file01.mp4', result.output)
        self.assertEqual(
            self.uploaded_names(), ['nime2025_10.pdf', 'nime2025_10_file02.mov']
        )
        self.assertEqual(self.done_rows(), [('nime2025_10.pdf', '1000', '10.5281/zenodo.1000')])
        self.assertEqual(self.read_state()[0]['skipped_files'], 'nime2025_10_file01.mp4')

    def test_file_exactly_at_limit_is_uploaded(self):
        self.make_file('nime2025_10_file01.mp4')
        self.patch_sizes({'nime2025_10_file01.mp4': 100 * MB})

        self.run_upload(self.bib)

        self.assertIn('nime2025_10_file01.mp4', self.uploaded_names())
        self.assertEqual(self.read_state()[0]['skipped_files'], '')

    def test_multiple_skipped_files_are_semicolon_separated(self):
        self.make_file('nime2025_10_a.mp4')
        self.make_file('nime2025_10_b.mp4')
        self.patch_sizes({
            'nime2025_10_a.mp4': 200 * MB,
            'nime2025_10_b.mp4': 300 * MB,
        })

        self.run_upload(self.bib)

        row = self.read_state()[0]
        self.assertEqual(row['doi'], '10.5281/zenodo.1000')
        # Order follows os.listdir, which is not guaranteed.
        self.assertEqual(
            sorted(row['skipped_files'].split(';')),
            ['nime2025_10_a.mp4', 'nime2025_10_b.mp4'],
        )

    def test_skipped_file_is_not_sent_to_server(self):
        self.make_file('nime2025_10_big.mp4')
        self.patch_sizes({'nime2025_10_big.mp4': 150 * MB})

        self.run_upload(self.bib)

        sent = [c['filename'] for c in self.fake.calls if 'filename' in c]
        self.assertEqual(sent, ['nime2025_10.pdf'])


class TestSupplementaryServerErrors(SupplementaryTestCase):
    def test_413_records_file_as_skipped_and_run_continues(self):
        self.make_file('nime2025_10_file01.mp4')
        self.make_file('nime2025_10_file02.mov')
        self.fake.fail_files = {
            'nime2025_10_file01.mp4': FakeResponse(
                413, text='<html>413 Request Entity Too Large</html>'
            )
        }

        result = self.run_upload(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertIn('HTTP 413', result.output)
        self.assertIn('upload this file manually', result.output.lower())
        self.assertEqual(
            self.uploaded_names(), ['nime2025_10.pdf', 'nime2025_10_file02.mov']
        )
        self.assertEqual(len(self.fake.calls_to('/actions/publish')), 1)
        self.assertEqual(self.done_rows(), [('nime2025_10.pdf', '1000', '10.5281/zenodo.1000')])
        self.assertEqual(self.read_state()[0]['skipped_files'], 'nime2025_10_file01.mp4')

    def test_other_server_error_records_file_as_skipped(self):
        self.make_file('nime2025_10_file01.mp4')
        self.fake.fail_files = {'nime2025_10_file01.mp4': 500}

        result = self.run_upload(self.bib)

        self.assertIn('Error happened during supplementary file upload', result.output)
        self.assertNotIn('HTTP 413', result.output)
        self.assertEqual(self.read_state()[0]['skipped_files'], 'nime2025_10_file01.mp4')

    def test_skipped_files_are_reported_on_console(self):
        self.make_file('nime2025_10_file01.mp4')
        self.fake.fail_files = {'nime2025_10_file01.mp4': 500}

        result = self.run_upload(self.bib)

        self.assertIn('Supplementary files skipped for nime2025_10.pdf', result.output)


if __name__ == '__main__':
    unittest.main()
