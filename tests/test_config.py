import unittest

from tests.support import CONFERENCE_TOML, WorkspaceTestCase, csv_row


class TestConferenceValidation(WorkspaceTestCase):
    """Placeholder or malformed edition values stop every command before any work is done."""

    def setUp(self):
        super().setUp()
        self.make_pdf()
        self.csv = self.write_csv(csv_row())

    def run_with(self, **changes):
        self.app.CONFERENCE = self.app.CONFERENCE._replace(**changes)
        return self.run_check(self.csv)

    def assertRejected(self, result, text):
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn(text, result.output)
        self.assertEqual(self.fake.calls, [])

    def test_valid_configuration_is_accepted(self):
        result = self.run_check(self.csv)

        self.assertEqual(result.exit_code, 0, result.output)

    def test_publication_date_must_be_a_real_date(self):
        for value in ('YYYY-MM-DD', '2026-13-01', '26 June 2026'):
            with self.subTest(value=value):
                self.assertRejected(self.run_with(publication_date=value), 'PUBLICATION_DATE')

    def test_url_must_be_a_real_address(self):
        for value in ('https://example.org', 'http://www.example.com/x', 'smcnetwork.org'):
            with self.subTest(value=value):
                self.assertRejected(self.run_with(url=value), 'CONFERENCE_URL')

    def test_isbn_may_be_empty_but_not_malformed(self):
        self.assertEqual(self.run_with(isbn='').exit_code, 0)
        for value in ('978-0-306-40615-8', 'XXX-X-XXXXX', '12345'):
            with self.subTest(value=value):
                self.assertRejected(self.run_with(isbn=value), 'ISBN')

    def test_isbn_placeholder_in_the_file_means_no_isbn(self):
        with open('conference.toml', 'w') as f:
            f.write(CONFERENCE_TOML.replace(
                "ISBN = '978-0-306-40615-7'", "ISBN = 'XXX-X-XXXXX-XXX-X'"
            ))
        self.reload_app()

        result = self.run_check(self.csv)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.app.CONFERENCE.isbn, '')

    def test_isbn_may_be_left_out_of_the_file(self):
        with open('conference.toml', 'w') as f:
            f.write(CONFERENCE_TOML.replace("ISBN = '978-0-306-40615-7'\n", ''))
        self.reload_app()

        self.assertEqual(self.run_check(self.csv).exit_code, 0)
        self.assertEqual(self.app.CONFERENCE.isbn, '')

    def test_isbn_10_and_13_are_accepted(self):
        for value in ('0-306-40615-2', '9780306406157', '978 0 306 40615 7'):
            with self.subTest(value=value):
                self.assertEqual(self.run_with(isbn=value).exit_code, 0)

    def test_issn_may_be_empty_but_not_malformed(self):
        self.assertEqual(self.run_with(issn='').exit_code, 0)
        self.assertRejected(self.run_with(issn='12345678'), 'ISSN')

    def test_place_placeholder_is_rejected(self):
        self.assertRejected(self.run_with(place='City, Country'), 'CONFERENCE_PLACE')

    def test_access_right_must_be_known(self):
        self.assertRejected(self.run_with(access_right='public'), 'ACCESS_RIGHT')

    def test_empty_values_are_rejected(self):
        for name, key in (('title', 'CONFERENCE_TITLE'), ('dates', 'CONFERENCE_DATES'),
                          ('license', 'LICENSE'), ('publisher', 'PUBLISHER'),
                          ('proceedings_title', 'PROCEEDINGS_TITLE')):
            with self.subTest(name=name):
                self.assertRejected(self.run_with(**{name: ''}), f'{key} is empty')

    def test_all_problems_are_listed_together(self):
        result = self.run_with(publication_date='YYYY-MM-DD', isbn='12345')

        self.assertRejected(result, 'PUBLICATION_DATE')
        self.assertIn('ISBN', result.output)

    def test_upload_is_stopped_too(self):
        self.app.CONFERENCE = self.app.CONFERENCE._replace(publication_date='YYYY-MM-DD')

        result = self.run_upload(self.csv)

        self.assertRejected(result, 'PUBLICATION_DATE')


if __name__ == '__main__':
    unittest.main()
