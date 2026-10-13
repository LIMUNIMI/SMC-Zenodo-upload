import importlib
import os
import sys
import unittest

from tests.support import MB, MODULE_NAME, WorkspaceTestCase, csv_row


class TestImportSideEffects(WorkspaceTestCase):
    # Characterization: the module writes to nime_dois.txt and reads
    # conference.toml and secrets.toml at import time. May change in refactor.

    def test_import_appends_upload_header_to_dois_file(self):
        lines = self.read_dois()
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r'^Uploaded \d{4}-\d{2}-\d{2} \d{2}:\d{2}\s*$')

    def test_import_appends_and_does_not_overwrite_existing_dois_file(self):
        with open('nime_dois.txt', 'a') as f:
            f.write('old.pdf,1,10.5281/zenodo.1\n')
        sys.modules.pop(MODULE_NAME)
        importlib.import_module(MODULE_NAME)

        lines = self.read_dois()
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[1], 'old.pdf,1,10.5281/zenodo.1')
        self.assertTrue(lines[0].startswith('Uploaded '))
        self.assertTrue(lines[2].startswith('Uploaded '))

    def test_missing_token_key_fails_when_that_server_is_used(self):
        with open('secrets.toml', 'w') as f:
            f.write("PUBLIC_TOKEN = 'only-public'\n")
        sys.modules.pop(MODULE_NAME)
        self.app = importlib.import_module(MODULE_NAME)
        self.make_pdf()
        bib = self.write_csv(csv_row())
        result = self.run_upload(bib)  # sandbox -> SANDBOX_TOKEN is missing

        self.assertIsInstance(result.exception, KeyError)
        self.assertEqual(self.fake.calls, [])


class TestInProcessState(WorkspaceTestCase):
    def test_runs_in_one_process_are_independent(self):
        self.make_pdf()
        path = self.write_csv(csv_row())

        first = self.run_check(path)
        second = self.run_check(path)

        self.assertIsNone(first.exception, first.output)
        self.assertIsNone(second.exception, second.output)
        self.assertEqual(first.output, second.output)


class TestImportWithoutSecrets(WorkspaceTestCase):
    write_secrets = False

    def test_missing_secrets_file_fails_at_import(self):
        with self.assertRaises(FileNotFoundError):
            importlib.import_module(MODULE_NAME)


class TestImportWithoutConferenceFile(WorkspaceTestCase):
    write_conference = False

    def test_missing_conference_file_fails_at_import(self):
        with self.assertRaises(FileNotFoundError):
            importlib.import_module(MODULE_NAME)

    def test_missing_conference_file_leaves_dois_file_untouched(self):
        with self.assertRaises(FileNotFoundError):
            importlib.import_module(MODULE_NAME)
        self.assertFalse(os.path.exists('nime_dois.txt'))


class TestConfiguration(WorkspaceTestCase):
    def test_upload_folder_is_relative_upload_directory(self):
        self.assertEqual(os.path.normpath(self.app.UPLOAD_FOLDER), 'upload')

    def test_size_limits_are_100_mb(self):
        self.assertEqual(self.app.MAX_SUPP_BYTES, 100 * MB)
        self.assertEqual(self.app.MAX_PDF_BYTES, 100 * MB)

    def test_conference_constants_are_set(self):
        self.assertRegex(self.app.PUBLICATION_DATE, r'^\d{4}-\d{2}-\d{2}$')
        self.assertEqual(self.app.CONFERENCE_ACRONYM, 'NIME')
        self.assertIn('New Interfaces for Musical Expression', self.app.CONFERENCE_TITLE)
        self.assertTrue(self.app.CONFERENCE_DATES)

    def test_dois_filename(self):
        self.assertEqual(self.app.DOI_FILENAME, 'nime_dois.txt')


if __name__ == '__main__':
    unittest.main()
