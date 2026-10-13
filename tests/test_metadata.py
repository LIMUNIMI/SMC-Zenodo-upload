import re
import unittest

from tests.support import WorkspaceTestCase, bib_entry


class TestMetadataMapping(WorkspaceTestCase):
    """Bib entry -> Zenodo metadata, observed through the deposition-creation request."""

    def upload_one(self, **entry_fields):
        entry_fields.setdefault('key', 'nime2025_1')
        self.make_pdf(entry_fields['key'])
        bib = self.write_bib(bib_entry(**entry_fields))
        result = self.run_upload(bib)
        self.assertIsNone(result.exception, result.output)
        metadata = self.created_metadata()
        self.assertEqual(len(metadata), 1)
        return metadata[0]

    def test_full_entry_is_mapped(self):
        md = self.upload_one(
            title='Sound Weaving',
            authors='Doe, Jane and Roe, Richard',
            Address='Utrecht, Netherlands',
            Pages='10--15',
            Abstract='An abstract.',
            booktitle='Proceedings of NIME',
            note='Paper Session 2',
            isbn='978-1-0000-0000-0',
            issn='2220-4806',
        )

        self.assertEqual(md['title'], 'Sound Weaving')
        self.assertEqual(md['upload_type'], 'publication')
        self.assertEqual(md['publication_type'], 'conferencepaper')
        self.assertEqual(md['description'], 'An abstract.')
        self.assertEqual(md['conference_place'], 'Utrecht, Netherlands')
        self.assertEqual(md['conference_url'], 'https://nime.org')
        self.assertEqual(md['partof_title'], 'Proceedings of NIME')
        self.assertEqual(md['imprint_title'], 'Proceedings of NIME')
        self.assertEqual(md['partof_pages'], '10--15')
        self.assertEqual(md['conference_session'], 'Paper Session 2')
        self.assertEqual(md['imprint_isbn'], '978-1-0000-0000-0')
        self.assertEqual(md['imprint_issn'], '2220-4806')
        self.assertEqual(md['communities'], [{'identifier': 'nime_conference'}])
        self.assertEqual(
            md['creators'], [{'name': 'Doe, Jane'}, {'name': 'Roe, Richard'}]
        )

    def test_conference_fields_come_from_configuration(self):
        md = self.upload_one()

        self.assertEqual(md['conference_title'], self.app.CONFERENCE_TITLE)
        self.assertEqual(md['conference_acronym'], self.app.CONFERENCE_ACRONYM)
        self.assertEqual(md['conference_dates'], self.app.CONFERENCE_DATES)
        self.assertRegex(md['publication_date'], r'^\d{4}-\d{2}-\d{2}$')
        # Characterization: the constant is used as-is; the year parsed from the
        # Url is computed by the program but not used.
        self.assertEqual(md['publication_date'], self.app.PUBLICATION_DATE)

    def test_missing_optional_fields_use_defaults(self):
        md = self.upload_one()

        self.assertEqual(md['description'], '---')
        self.assertEqual(md['conference_place'], 'Address')
        self.assertNotIn('partof_pages', md)
        self.assertNotIn('conference_session', md)
        # Characterization: absent optional fields are sent as null.
        self.assertIsNone(md['partof_title'])
        self.assertIsNone(md['imprint_isbn'])
        self.assertIsNone(md['imprint_issn'])

    def test_field_names_are_case_insensitive(self):
        # pybtex fields are case-insensitive: `url`/`Url`, `title`/`Title`, ...
        self.make_pdf('nime2025_1')
        bib = self.write_bib(
            '@inproceedings{nime2025_1,\n'
            '  author = {Doe, Jane},\n  TITLE = {Upper},\n'
            '  URL = {https://nime.org/proceedings/2025/nime2025_1.pdf},\n'
            '  abstract = {lower abstract}\n}\n'
        )
        result = self.run_upload(bib)

        self.assertIsNone(result.exception, result.output)
        md = self.created_metadata()[0]
        self.assertEqual(md['title'], 'Upper')
        self.assertEqual(md['description'], 'lower abstract')

    def test_pdf_name_is_last_segment_of_url(self):
        self.make_pdf('some_other_name')
        bib = self.write_bib(bib_entry(
            key='k', url='https://example.org/a/b/2024/some_other_name.pdf'
        ))
        result = self.run_upload(bib)

        self.assertIsNone(result.exception, result.output)
        filenames = [c['filename'] for c in self.fake.calls if 'filename' in c]
        self.assertEqual(filenames, ['some_other_name.pdf'])


class TestAuthorNames(WorkspaceTestCase):
    def creators(self, authors):
        self.make_pdf()
        bib = self.write_bib(bib_entry(authors=authors))
        result = self.run_upload(bib)
        self.assertIsNone(result.exception, result.output)
        return [c['name'] for c in self.created_metadata()[0]['creators']]

    def test_last_first_names_are_kept(self):
        self.assertEqual(self.creators('Doe, Jane'), ['Doe, Jane'])

    def test_first_last_names_are_reordered_to_last_first(self):
        self.assertEqual(self.creators('Jane Doe'), ['Doe, Jane'])

    def test_multiple_authors_keep_bib_order(self):
        self.assertEqual(
            self.creators('Zed, Zoe and Alpha, Al and Mid, Max'),
            ['Zed, Zoe', 'Alpha, Al', 'Mid, Max'],
        )

    def test_braces_and_latex_umlaut_marker_are_stripped(self):
        # Characterization: `{`, `}` and `\"` are removed, so M{\"u}ller -> Muller.
        self.assertEqual(self.creators('M{\\"u}ller, {J}urgen'), ['Muller, Jurgen'])

    def test_von_particle_is_preserved(self):
        self.assertEqual(self.creators('van der Berg, Anna'), ['van der Berg, Anna'])


class TestUtf8Input(WorkspaceTestCase):
    def test_utf8_bib_content_is_preserved(self):
        # The README requires UTF-8 symbols (not LaTeX codes) in the .bib.
        self.make_pdf()
        bib = self.write_bib(bib_entry(
            title='Café “quoted” ñ', authors='Müller, Jürgen and Žižek, Slavoj'
        ))

        result = self.run_upload(bib)

        self.assertIsNone(result.exception, result.output)
        md = self.created_metadata()[0]
        self.assertEqual(md['title'], 'Café “quoted” ñ')
        self.assertEqual(
            [c['name'] for c in md['creators']], ['Müller, Jürgen', 'Žižek, Slavoj']
        )


class TestCheckCommand(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.make_pdf()
        self.bib = self.write_bib(bib_entry(title='Check Me', authors='Doe, Jane'))

    def test_check_prints_metadata_without_network_access(self):
        result = self.run_check(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertEqual(result.exit_code, 0)
        self.assertIn('Check Me', result.output)
        self.assertIn('conferencepaper', result.output)
        self.assertEqual(self.fake.calls, [])

    def test_check_does_not_write_dois(self):
        self.run_check(self.bib)

        self.assertEqual(self.doi_lines(), [])

    def test_check_authors_prints_names_only(self):
        result = self.run_check(self.bib, '--authors')

        self.assertIsNone(result.exception, result.output)
        self.assertIn('Doe, Jane', result.output)
        self.assertNotIn('conferencepaper', result.output)
        self.assertEqual(self.fake.calls, [])

    def test_check_nonexistent_bib_is_usage_error(self):
        result = self.run_check('upload/nope.bib')

        self.assertEqual(result.exit_code, 2)
        self.assertEqual(self.fake.calls, [])

    def test_check_with_multiple_entries_lists_all(self):
        self.make_pdf('nime2025_2')
        bib = self.write_bib(
            bib_entry(key='nime2025_1', title='First'),
            bib_entry(key='nime2025_2', title='Second'),
            name='two.bib',
        )
        result = self.run_check(bib)

        self.assertIsNone(result.exception, result.output)
        self.assertEqual(len(re.findall(r"'upload_type'", result.output)), 2)
        self.assertIn('First', result.output)
        self.assertIn('Second', result.output)


if __name__ == '__main__':
    unittest.main()
