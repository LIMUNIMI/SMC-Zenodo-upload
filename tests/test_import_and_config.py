import importlib
import os
import sys
import unittest

from tests.support import MB, MODULE_NAME, WorkspaceTestCase, csv_row


class TestImportSideEffects(WorkspaceTestCase):
    # The module reads conference.toml and secrets.toml at import time and
    # writes nothing.

    def test_import_creates_no_files(self):
        self.assertEqual(
            sorted(os.listdir('.')), ['conference.toml', 'secrets.toml', 'upload']
        )

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

    def test_state_columns_and_stages(self):
        self.assertEqual(
            self.app.STATE_COLUMNS,
            ('status', 'server', 'deposition_id', 'doi', 'skipped_files', 'error', 'updated_at'),
        )
        self.assertEqual(
            self.app.STAGES, ('pending', 'created', 'uploaded', 'published', 'done')
        )


if __name__ == '__main__':
    unittest.main()
