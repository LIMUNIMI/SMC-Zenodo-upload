import unittest

from tests.support import WorkspaceTestCase, csv_row


class TestDoiFileFormat(WorkspaceTestCase):
    def upload(self, *flags, **entry):
        entry.setdefault('key', 'nime2025_7')
        self.make_pdf(entry['key'])
        bib = self.write_csv(csv_row(**entry))
        result = self.run_upload(bib, *flags)
        self.assertIsNone(result.exception, result.output)

    def test_default_line_has_three_fields(self):
        self.upload(title='Plain Title')

        self.assertEqual(self.doi_lines(), ['nime2025_7.pdf,1000,10.5281/zenodo.1000'])

    def test_title_flag_appends_title_as_last_field(self):
        self.upload('--title', title='Plain Title')

        self.assertEqual(
            self.doi_lines(),
            ['nime2025_7.pdf,1000,10.5281/zenodo.1000,Plain Title'],
        )

    def test_newlines_in_title_are_replaced_by_spaces(self):
        self.upload('--title', title='First part\nsecond part')

        line = self.doi_lines()[0]
        self.assertTrue(line.endswith(',First part second part'), line)

    def test_title_is_stripped(self):
        self.upload('--title', title='  Padded  ')

        self.assertTrue(self.doi_lines()[0].endswith(',Padded'))

    def test_commas_in_title_are_not_escaped(self):
        # Characterization: the file is not CSV-safe; a title containing commas
        # produces extra fields.
        self.upload('--title', title='Hello, World')

        self.assertEqual(self.doi_lines()[0].split(',')[3:], ['Hello', ' World'])

    def test_title_flag_with_skipped_supplementary_keeps_title_last(self):
        self.make_file('nime2025_7_file01.mp4')
        self.fake.fail_files = {'nime2025_7_file01.mp4': 500}

        self.upload('--title', title='Last Field')

        self.assertEqual(
            self.doi_lines(),
            ['nime2025_7.pdf,1000,10.5281/zenodo.1000*nime2025_7_file01.mp4,Last Field'],
        )

    def test_runs_append_to_existing_file(self):
        self.upload(title='One', key='nime2025_7')
        self.reload_app()
        self.upload(title='Two', key='nime2025_8')

        lines = self.doi_lines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith('nime2025_7.pdf,'))
        self.assertTrue(lines[1].startswith('nime2025_8.pdf,'))


if __name__ == '__main__':
    unittest.main()
