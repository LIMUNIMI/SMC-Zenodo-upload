import re
import unittest

from tests.support import WorkspaceTestCase, csv_row


class TestMetadataMapping(WorkspaceTestCase):
    """CSV row -> Zenodo metadata, observed through the deposition-creation request."""

    def upload_one(self, **entry_fields):
        entry_fields.setdefault('key', 'nime2025_1')
        self.make_pdf(entry_fields['key'])
        bib = self.write_csv(csv_row(**entry_fields))
        result = self.run_upload(bib)
        self.assertIsNone(result.exception, result.output)
        metadata = self.created_metadata()
        self.assertEqual(len(metadata), 1)
        return metadata[0]

    def test_full_entry_is_mapped(self):
        md = self.upload_one(
            title='Sound Weaving',
            authors='Doe, Jane; Roe, Richard',
            pages='10--15',
            abstract='An abstract.',
            note='Paper Session 2',
        )

        self.assertEqual(md['title'], 'Sound Weaving')
        self.assertEqual(md['upload_type'], 'publication')
        self.assertEqual(md['publication_type'], 'conferencepaper')
        self.assertEqual(md['description'], 'An abstract.')
        self.assertEqual(md['conference_url'], 'https://exc.test/')
        self.assertEqual(md['partof_pages'], '10--15')
        self.assertEqual(md['conference_session'], 'Paper Session 2')
        self.assertEqual(md['communities'], [{'identifier': 'example_community'}])
        self.assertEqual(
            md['creators'], [{'name': 'Doe, Jane'}, {'name': 'Roe, Richard'}]
        )

    def test_conference_fields_come_from_configuration(self):
        md = self.upload_one()

        self.assertEqual(md['conference_title'], self.app.CONFERENCE_TITLE)
        self.assertEqual(md['conference_acronym'], self.app.CONFERENCE_ACRONYM)
        self.assertEqual(md['conference_dates'], self.app.CONFERENCE_DATES)
        self.assertEqual(md['license'], 'cc-by-4.0')
        self.assertEqual(md['access_right'], 'open')
        self.assertEqual(md['imprint_publisher'], 'Example Publisher')
        self.assertEqual(md['conference_place'], 'Example City, Country')
        self.assertEqual(md['partof_title'], 'Proceedings of the Example Conference on Sound')
        self.assertEqual(md['imprint_title'], md['partof_title'])
        self.assertEqual(md['imprint_isbn'], '978-0-306-40615-7')
        self.assertEqual(md['imprint_issn'], '0000-0000')
        self.assertRegex(md['publication_date'], r'^\d{4}-\d{2}-\d{2}$')
        # The date comes from the configuration, never from the rows.
        self.assertEqual(md['publication_date'], self.app.PUBLICATION_DATE)

    def test_missing_optional_fields_use_defaults(self):
        md = self.upload_one()

        self.assertEqual(md['description'], '---')
        self.assertNotIn('partof_pages', md)
        self.assertNotIn('conference_session', md)

    def test_column_names_are_case_insensitive_and_extra_columns_are_ignored(self):
        self.make_pdf('nime2025_1')
        path = self.write_csv({
            'KEY': 'nime2025_1', 'Pdf': 'nime2025_1.pdf', 'TITLE': 'Upper',
            'Authors': 'Doe, Jane', 'abstract': 'lower abstract',
            'track': 'Papers', 'whatever': 'garbage',
        })
        result = self.run_upload(path)

        self.assertIsNone(result.exception, result.output)
        md = self.created_metadata()[0]
        self.assertEqual(md['title'], 'Upper')
        self.assertEqual(md['description'], 'lower abstract')
        self.assertNotIn('Papers', str(md))
        self.assertNotIn('garbage', str(md))

    def test_empty_cells_are_like_missing_columns(self):
        md = self.upload_one(abstract='', pages='', note='')

        self.assertEqual(md['description'], '---')
        self.assertNotIn('partof_pages', md)
        self.assertNotIn('conference_session', md)

    def test_edition_columns_of_the_csv_are_ignored(self):
        md = self.upload_one(
            address='Utrecht, Netherlands', booktitle='Other title',
            isbn='111-1-1111-1111-1', issn='1111-1111',
        )

        self.assertEqual(md['conference_place'], 'Example City, Country')
        self.assertEqual(md['partof_title'], 'Proceedings of the Example Conference on Sound')
        self.assertEqual(md['imprint_isbn'], '978-0-306-40615-7')
        self.assertEqual(md['imprint_issn'], '0000-0000')

    def test_issn_is_left_out_when_the_proceedings_have_none(self):
        from zenodo_upload.metadata import build_deposition

        md = build_deposition(csv_row(), self.app.CONFERENCE._replace(issn=''))['metadata']

        self.assertNotIn('imprint_issn', md)

    def test_isbn_is_left_out_when_not_known_yet(self):
        from zenodo_upload.metadata import build_deposition

        md = build_deposition(csv_row(), self.app.CONFERENCE._replace(isbn=''))['metadata']

        self.assertNotIn('imprint_isbn', md)

    def test_values_are_stripped(self):
        md = self.upload_one(title='  Padded  ')

        self.assertEqual(md['title'], 'Padded')

    def test_pdf_column_names_the_file(self):
        self.make_file('some_other_name.pdf')
        path = self.write_csv(csv_row(key='k', pdf='some_other_name.pdf'))
        result = self.run_upload(path)

        self.assertIsNone(result.exception, result.output)
        filenames = [c['filename'] for c in self.fake.calls if 'filename' in c]
        self.assertEqual(filenames, ['some_other_name.pdf'])


class TestAuthorNames(WorkspaceTestCase):
    def creators(self, authors):
        self.make_pdf()
        bib = self.write_csv(csv_row(authors=authors))
        result = self.run_upload(bib)
        self.assertIsNone(result.exception, result.output)
        return [c['name'] for c in self.created_metadata()[0]['creators']]

    def test_last_first_names_are_kept(self):
        self.assertEqual(self.creators('Doe, Jane'), ['Doe, Jane'])

    def test_names_are_not_reordered(self):
        # Names are taken as written; bibcsv normalises them when converting a .bib.
        self.assertEqual(self.creators('Jane Doe'), ['Jane Doe'])

    def test_multiple_authors_keep_row_order(self):
        self.assertEqual(
            self.creators('Zed, Zoe; Alpha, Al; Mid, Max'),
            ['Zed, Zoe', 'Alpha, Al', 'Mid, Max'],
        )

    def test_empty_segments_and_padding_are_dropped(self):
        self.assertEqual(
            self.creators(' Doe, Jane ;; Roe, Richard ; '), ['Doe, Jane', 'Roe, Richard']
        )

    def test_braces_are_left_alone(self):
        # Characterization: the uploader no longer cleans names (bibcsv does).
        self.assertEqual(self.creators('{Some Group}'), ['{Some Group}'])


class TestAffiliations(WorkspaceTestCase):
    def creators(self, authors, affiliations):
        self.make_pdf()
        path = self.write_csv(csv_row(authors=authors, affiliations=affiliations))
        result = self.run_upload(path)
        self.assertIsNone(result.exception, result.output)
        return self.created_metadata()[0]['creators']

    def test_affiliations_are_matched_to_authors_by_position(self):
        self.assertEqual(
            self.creators('Doe, Jane; Roe, Rick', 'University A; Institute B'),
            [{'name': 'Doe, Jane', 'affiliation': 'University A'},
             {'name': 'Roe, Rick', 'affiliation': 'Institute B'}],
        )

    def test_an_author_may_have_no_affiliation(self):
        self.assertEqual(
            self.creators('Doe, Jane; Roe, Rick', ';Institute B'),
            [{'name': 'Doe, Jane'}, {'name': 'Roe, Rick', 'affiliation': 'Institute B'}],
        )

    def test_empty_affiliations_give_plain_names(self):
        self.assertEqual(self.creators('Doe, Jane', ''), [{'name': 'Doe, Jane'}])


class TestUtf8Input(WorkspaceTestCase):
    def test_utf8_content_is_preserved(self):
        # The CSV must be UTF-8; a BOM (Excel) is tolerated.
        self.make_pdf()
        bib = self.write_csv(csv_row(
            title='Café “quoted” ñ', authors='Müller, Jürgen; Žižek, Slavoj'
        ))

        result = self.run_upload(bib)

        self.assertIsNone(result.exception, result.output)
        md = self.created_metadata()[0]
        self.assertEqual(md['title'], 'Café “quoted” ñ')
        self.assertEqual(
            [c['name'] for c in md['creators']], ['Müller, Jürgen', 'Žižek, Slavoj']
        )

    def test_utf8_bom_is_tolerated(self):
        self.make_pdf()
        path = self.write_csv(csv_row(title='With BOM'), encoding='utf-8-sig')

        result = self.run_upload(path)

        self.assertIsNone(result.exception, result.output)
        self.assertEqual(self.created_metadata()[0]['title'], 'With BOM')


class TestCheckCommand(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.make_pdf()
        self.bib = self.write_csv(csv_row(title='Check Me', authors='Doe, Jane'))

    def test_check_prints_metadata_without_network_access(self):
        result = self.run_check(self.bib)

        self.assertIsNone(result.exception, result.output)
        self.assertEqual(result.exit_code, 0)
        self.assertIn('Check Me', result.output)
        self.assertIn('conferencepaper', result.output)
        self.assertEqual(self.fake.calls, [])

    def test_check_does_not_modify_the_file(self):
        with open(self.bib, 'rb') as f:
            before = f.read()

        self.run_check(self.bib)

        with open(self.bib, 'rb') as f:
            self.assertEqual(f.read(), before)

    def test_check_authors_prints_names_only(self):
        result = self.run_check(self.bib, '--authors')

        self.assertIsNone(result.exception, result.output)
        self.assertIn('Doe, Jane', result.output)
        self.assertNotIn('conferencepaper', result.output)
        self.assertEqual(self.fake.calls, [])

    def test_check_nonexistent_file_is_usage_error(self):
        result = self.run_check('upload/nope.csv')

        self.assertEqual(result.exit_code, 2)
        self.assertEqual(self.fake.calls, [])

    def test_check_with_multiple_entries_lists_all(self):
        self.make_pdf('nime2025_2')
        bib = self.write_csv(
            csv_row(key='nime2025_1', title='First'),
            csv_row(key='nime2025_2', title='Second'),
            name='two.csv',
        )
        result = self.run_check(bib)

        self.assertIsNone(result.exception, result.output)
        self.assertEqual(len(re.findall(r"'upload_type'", result.output)), 2)
        self.assertIn('First', result.output)
        self.assertIn('Second', result.output)


if __name__ == '__main__':
    unittest.main()
