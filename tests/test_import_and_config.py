import importlib
import os
import sys
import unittest
from unittest import mock

from tests.support import CONFERENCE_TOML, MB, MODULE_NAME, WorkspaceTestCase, csv_row


class TestImportSideEffects(WorkspaceTestCase):
    # The module reads conference.toml at import time and writes nothing.

    def test_import_creates_no_files(self):
        self.assertEqual(
            sorted(os.listdir('.')), ['conference.toml', 'secrets.toml', 'upload']
        )

    def test_missing_token_key_fails_when_that_server_is_used(self):
        with open('secrets.toml', 'w') as f:
            f.write("PUBLIC_TOKEN = 'only-public'\n")
        self.make_pdf()
        bib = self.write_csv(csv_row())
        with mock.patch('builtins.input') as prompt:
            result = self.run_cli('upload', bib)  # sandbox -> SANDBOX_TOKEN is missing

        self.assertEqual(result.exit_code, 1)
        self.assertIsNone(result.exception, result.output)
        self.assertIn('SANDBOX_TOKEN', result.output)
        prompt.assert_not_called()
        self.assertEqual(self.fake.calls, [])

    def test_only_the_token_of_the_chosen_server_is_needed(self):
        with open('secrets.toml', 'w') as f:
            f.write("PUBLIC_TOKEN = 'only-public'\n")
        self.make_pdf()
        bib = self.write_csv(csv_row())

        result = self.run_upload(bib, '--production')

        self.assertEqual(result.exit_code, 0, result.output)


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

    def test_secrets_file_is_not_needed_to_import_or_to_check(self):
        app = importlib.import_module(MODULE_NAME)
        self.make_pdf()
        path = self.write_csv(csv_row())
        self.app = app

        result = self.run_check(path)

        self.assertEqual(result.exit_code, 0, result.output)

    def test_upload_and_publish_explain_the_missing_file_before_the_prompt(self):
        self.app = importlib.import_module(MODULE_NAME)
        self.make_pdf()
        path = self.write_csv(csv_row())

        for command in ('upload', 'publish'):
            with self.subTest(command=command), mock.patch('builtins.input') as prompt:
                result = self.run_cli(command, path)

                self.assertEqual(result.exit_code, 1)
                self.assertIsNone(result.exception, result.output)
                self.assertIn('secrets.toml not found', result.output)
                prompt.assert_not_called()
        self.assertEqual(self.fake.calls, [])


class TestImportWithoutConferenceFile(WorkspaceTestCase):
    write_conference = False

    def test_missing_conference_file_fails_at_import(self):
        with self.assertRaises(FileNotFoundError):
            importlib.import_module(MODULE_NAME)


class TestIncompleteConferenceFile(WorkspaceTestCase):
    write_conference = False

    def test_missing_conference_key_fails_at_import(self):
        for key in ('CONFERENCE_URL', 'ZENODO_COMMUNITY'):
            with self.subTest(key=key):
                with open('conference.toml', 'w') as f:
                    f.writelines(
                        line for line in CONFERENCE_TOML.splitlines(keepends=True)
                        if not line.startswith(key)
                    )
                with self.assertRaises(KeyError):
                    importlib.import_module(MODULE_NAME)


class TestConfiguration(WorkspaceTestCase):
    def test_upload_folder_is_relative_upload_directory(self):
        self.assertEqual(os.path.normpath(self.app.UPLOAD_FOLDER), 'upload')

    def test_size_limits_are_100_mb(self):
        self.assertEqual(self.app.MAX_SUPP_BYTES, 100 * MB)
        self.assertEqual(self.app.MAX_PDF_BYTES, 100 * MB)

    def test_conference_constants_are_set(self):
        self.assertRegex(self.app.PUBLICATION_DATE, r'^\d{4}-\d{2}-\d{2}$')
        self.assertEqual(self.app.CONFERENCE_ACRONYM, 'EXC')
        self.assertEqual(self.app.CONFERENCE_TITLE, 'Example Conference on Sound')
        self.assertTrue(self.app.CONFERENCE_DATES)
        self.assertEqual(self.app.CONFERENCE_URL, 'https://exc.test/')
        self.assertEqual(self.app.ZENODO_COMMUNITY, 'example_community')

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
