"""Tests on real-world entries stored in tests/fixtures/.

Each fixture is a verbatim entry from the NIME bibliography exports, converted
with bibcsv/bibcsv.py (the .bib sources are kept next to the .csv files).
Where the current behavior is a limitation rather than a requirement, it is
marked as characterization so that changing it is a deliberate decision.
"""

import unittest

from tests.support import EXAMPLES_DIR, WorkspaceTestCase, csv_row


class TestValidEntries(WorkspaceTestCase):
    def test_installation_entry_passes_check(self):
        path = self.copy_fixture('valid_installation.csv')

        result = self.run_check(path)

        self.assertIsNone(result.exception, result.output)
        self.assertIn('Fold Loud', result.output)
        self.assertEqual(self.fake.calls, [])

    def test_installation_entry_is_uploaded_with_expected_metadata(self):
        path = self.copy_fixture('valid_installation.csv')

        result = self.run_upload(path)

        self.assertIsNone(result.exception, result.output)
        md = self.created_metadata()[0]
        self.assertEqual(md['title'], 'Fold Loud')
        self.assertEqual(md['creators'], [{'name': 'Paek, JooYoun'}])
        self.assertEqual(md['partof_pages'], '411')
        self.assertEqual(md['description'], '---')  # no abstract in the entry
        self.assertNotIn('conference_session', md)
        self.assertEqual(
            self.done_rows(),
            [('nime2008_installations_Paek.pdf', '1000', '10.5281/zenodo.1000')],
        )

    def test_paper_entry_is_uploaded_with_abstract_and_all_authors(self):
        path = self.copy_fixture('valid_paper.csv')

        result = self.run_upload(path)

        self.assertIsNone(result.exception, result.output)
        md = self.created_metadata()[0]
        self.assertEqual(md['title'], 'TENORI-ON')
        self.assertEqual(
            md['creators'], [{'name': 'Nishibori, Yu'}, {'name': 'Iwai, Toshio'}]
        )
        self.assertEqual(md['partof_pages'], '172--175')
        self.assertTrue(md['description'].startswith('Development of a musical interface'))
        # The PDF name comes from the pdf column, not from the entry key.
        self.assertEqual(
            self.done_rows(), [('nime2006_172.pdf', '1000', '10.5281/zenodo.1000')]
        )


class TestExampleCsv(WorkspaceTestCase):
    """The example CSV shipped in examples/ must stay valid and show what it documents."""

    def setUp(self):
        super().setUp()
        self.example = self.copy_fixture('proceedings_example.csv', source_dir=EXAMPLES_DIR)

    def test_example_passes_check(self):
        result = self.run_check(self.example)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.fake.calls, [])

    def test_example_is_uploaded_with_the_documented_metadata(self):
        result = self.run_upload(self.example)

        self.assertEqual(result.exit_code, 0, result.output)
        full, partial, minimal = self.created_metadata()
        self.assertEqual(
            full['creators'],
            [{'name': 'Rossi, Maria', 'affiliation': 'University of Example'},
             {'name': 'Bianchi, Luca', 'affiliation': 'Institute of Sound Research'}],
        )
        self.assertEqual(full['conference_session'], 'Paper Session 1')
        self.assertEqual(full['partof_pages'], '1--8')
        self.assertEqual(
            partial['creators'],
            [{'name': 'Verdi, Anna'},
             {'name': 'Neri, Paolo', 'affiliation': 'Institute of Sound Research'}],
        )
        self.assertEqual(minimal['creators'], [{'name': 'Gialli, Sara'}])
        self.assertEqual(minimal['description'], '---')
        self.assertEqual(len(self.done_rows()), 3)


class TestKnownProblematicEntries(WorkspaceTestCase):
    def test_entry_without_url_is_rejected(self):
        # The pdf column is derived from the url by bibcsv, so it stays empty.
        path = self.copy_fixture('missing_url.csv')

        result = self.run_upload(path)

        self.assertEqual(result.exit_code, 1)
        self.assertIn('empty pdf', result.output)
        self.assertEqual(self.fake.calls, [])

    def test_unused_columns_do_not_reach_zenodo(self):
        # e.g. the editor list of comma_separated_editors.bib, which pybtex could not parse.
        self.make_pdf()
        path = self.write_csv(csv_row(editor='Andrew Johnston, Sam Ferguson, Jos Mulder'))

        result = self.run_upload(path)

        self.assertIsNone(result.exception, result.output)
        self.assertNotIn('Andrew Johnston', str(self.created_metadata()[0]))

    def test_canonical_template_is_not_a_valid_input(self):
        # Characterization: the empty title and author make the row unusable.
        path = self.copy_fixture('canonical_template.csv')

        result = self.run_check(path)

        self.assertEqual(result.exit_code, 1)
        self.assertIn('empty title, authors', result.output)


if __name__ == '__main__':
    unittest.main()
