import unittest
from unittest import mock

from tests.support import WorkspaceTestCase, csv_row


class TestUploadCommand(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.make_pdf()
        self.bib = self.write_csv(csv_row())

    def test_sandbox_banner_is_shown_by_default(self):
        result = self.run_upload(self.bib)

        self.assertIn('sandbox', result.output.lower())
        self.assertNotIn('production Zenodo server', result.output)

    def test_production_banner_is_a_warning(self):
        result = self.run_upload(self.bib, '--production')

        self.assertIn('WARNING', result.output)
        self.assertIn('production Zenodo server', result.output)

    def test_user_must_confirm_with_enter_before_upload(self):
        with mock.patch('builtins.input', side_effect=KeyboardInterrupt) as prompt:
            result = self.run_cli('upload', self.bib)

        prompt.assert_called_once()
        self.assertEqual(self.fake.calls, [])
        self.assertNotEqual(result.exit_code, 0)

    def test_confirmation_is_requested_once_per_run(self):
        self.make_pdf('nime2025_2')
        bib = self.write_csv(
            csv_row(key='nime2025_1'), csv_row(key='nime2025_2'), name='two.csv'
        )
        with mock.patch('builtins.input', return_value='') as prompt:
            self.run_cli('upload', bib)

        prompt.assert_called_once()

    def test_bibfile_must_exist(self):
        result = self.run_upload('upload/missing.csv')

        self.assertEqual(result.exit_code, 2)
        self.assertEqual(self.fake.calls, [])

    def test_title_flag_no_longer_exists(self):
        result = self.run_upload(self.bib, '--title')

        self.assertEqual(result.exit_code, 2)
        self.assertEqual(self.fake.calls, [])

    def test_unknown_option_is_rejected(self):
        result = self.run_upload(self.bib, '--nope')

        self.assertEqual(result.exit_code, 2)


class TestCheckCommandOptions(WorkspaceTestCase):
    def test_check_does_not_ask_for_confirmation(self):
        self.make_pdf()
        bib = self.write_csv(csv_row())
        with mock.patch('builtins.input') as prompt:
            result = self.run_cli('check', bib)

        self.assertEqual(result.exit_code, 0, result.output)
        prompt.assert_not_called()

    def test_check_has_no_production_option(self):
        self.make_pdf()
        bib = self.write_csv(csv_row())

        result = self.run_check(bib, '--production')

        self.assertEqual(result.exit_code, 2)


if __name__ == '__main__':
    unittest.main()
