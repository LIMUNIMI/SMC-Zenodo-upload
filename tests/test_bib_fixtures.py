"""Tests on real-world entries stored in tests/fixtures/.

Each fixture is a verbatim entry from the NIME bibliography exports. Where the
current behavior is a limitation rather than a requirement, it is marked as
characterization so that changing it is a deliberate decision.
"""

import unittest

from pybtex.database import InvalidNameString

from tests.support import WorkspaceTestCase


class TestValidEntries(WorkspaceTestCase):
    def test_installation_entry_passes_check(self):
        bib = self.copy_fixture('valid_installation.bib')

        result = self.run_check(bib)

        self.assertIsNone(result.exception, result.output)
        self.assertIn('Fold Loud', result.output)
        self.assertEqual(self.fake.calls, [])

    def test_installation_entry_is_uploaded_with_expected_metadata(self):
        bib = self.copy_fixture('valid_installation.bib')

        result = self.run_upload(bib)

        self.assertIsNone(result.exception, result.output)
        md = self.created_metadata()[0]
        self.assertEqual(md['title'], 'Fold Loud')
        self.assertEqual(md['creators'], [{'name': 'Paek, JooYoun'}])
        self.assertEqual(md['partof_pages'], '411')
        self.assertEqual(md['conference_place'], 'Genova, Italy')
        self.assertEqual(md['imprint_issn'], '2220-4806')
        self.assertEqual(md['description'], '---')  # no abstract in the entry
        self.assertNotIn('conference_session', md)
        self.assertEqual(
            self.doi_lines(),
            ['nime2008_installations_Paek.pdf,1000,10.5281/zenodo.1000'],
        )

    def test_paper_entry_is_uploaded_with_abstract_and_all_authors(self):
        bib = self.copy_fixture('valid_paper.bib')

        result = self.run_upload(bib, '--title')

        self.assertIsNone(result.exception, result.output)
        md = self.created_metadata()[0]
        self.assertEqual(md['title'], 'TENORI-ON')
        self.assertEqual(
            md['creators'], [{'name': 'Nishibori, Yu'}, {'name': 'Iwai, Toshio'}]
        )
        self.assertEqual(md['partof_pages'], '172--175')
        self.assertTrue(md['description'].startswith('Development of a musical interface'))
        # The PDF name comes from the url, not from the entry key.
        self.assertEqual(
            self.doi_lines(), ['nime2006_172.pdf,1000,10.5281/zenodo.1000,TENORI-ON']
        )


class TestKnownProblematicEntries(WorkspaceTestCase):
    def test_entry_without_url_aborts_with_key_error(self):
        bib = self.copy_fixture('missing_url.bib')

        result = self.run_upload(bib)

        self.assertIsInstance(result.exception, KeyError)
        self.assertEqual(self.fake.calls, [])

    def test_comma_separated_editors_are_rejected_by_the_bib_parser(self):
        # Characterization: `editor = {A B, C D, ...}` (comma instead of `and`)
        # makes pybtex fail on the whole file, before any other processing.
        bib = self.copy_fixture('comma_separated_editors.bib')

        result = self.run_check(bib)

        self.assertIsInstance(result.exception, InvalidNameString)
        self.assertEqual(self.fake.calls, [])

    def test_canonical_template_is_not_a_valid_input(self):
        # Characterization: the empty `author` makes the entry unusable.
        bib = self.copy_fixture('canonical_template.bib')

        result = self.run_check(bib)

        self.assertIsInstance(result.exception, KeyError)


if __name__ == '__main__':
    unittest.main()
