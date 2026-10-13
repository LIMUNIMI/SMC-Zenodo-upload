"""Tests for bibcsv. Run from the repo root:

    .venv\\Scripts\\python -m unittest discover -s bibcsv/tests
"""

import contextlib
import csv
import io
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
FIXTURES = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'tests', 'fixtures')

import bibcsv  # noqa: E402


class BibCsvTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='bibcsv_test_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.tmp, name)

    def write(self, name, text, encoding='utf-8'):
        with open(self.path(name), 'w', encoding=encoding, newline='') as f:
            f.write(text)
        return self.path(name)

    def read_rows(self, name):
        with open(self.path(name), encoding='utf-8', newline='') as f:
            return list(csv.DictReader(f))

    def read_header(self, name):
        with open(self.path(name), encoding='utf-8', newline='') as f:
            return next(csv.reader(f))

    def run_tool(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = bibcsv.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def fixture_to_csv(self, fixture, *flags):
        src = os.path.join(FIXTURES, fixture)
        dest = self.path(fixture.replace('.bib', '.csv'))
        code, out, err = self.run_tool('bib2csv', src, dest, *flags)
        return code, dest, err

    def bib_text(self, **fields):
        body = ',\n'.join(f'  {name} = {{{value}}}' for name, value in fields.items())
        return f'@inproceedings{{k1,\n{body}\n}}\n'


class TestBib2Csv(BibCsvTestCase):
    def test_valid_paper(self):
        code, dest, _ = self.fixture_to_csv('valid_paper.bib')

        self.assertEqual(code, 0)
        (row,) = self.read_rows('valid_paper.csv')
        self.assertEqual(row['key'], 'nime2006_Nishibori')
        self.assertEqual(row['pdf'], 'nime2006_172.pdf')
        self.assertEqual(row['url'], 'https://nime.org/proceedings/2006/nime2006_172.pdf')
        self.assertEqual(row['title'], 'TENORI-ON')
        self.assertEqual(row['authors'], 'Nishibori, Yu; Iwai, Toshio')
        self.assertEqual(row['pages'], '172--175')
        self.assertEqual(row['doi'], '10.5281/zenodo.1176979')
        self.assertEqual(row['status'], '')

    def test_unused_fields_are_kept_as_columns(self):
        self.fixture_to_csv('valid_installation.bib')

        (row,) = self.read_rows('valid_installation.csv')
        self.assertEqual(row['track'], 'Installations')
        self.assertEqual(row['articleno'], '3')
        self.assertEqual(row['editor'], 'Corrado Canepa')

    def test_column_order(self):
        self.fixture_to_csv('valid_installation.bib')

        header = self.read_header('valid_installation.csv')
        self.assertEqual(header[:3], ['key', 'pdf', 'title'])
        self.assertEqual(header[-7:], bibcsv.STATE_COLUMNS)
        self.assertEqual(len(header), len(set(header)))

    def test_canonical_template_keeps_hyphenated_and_numbered_fields(self):
        self.fixture_to_csv('canonical_template.bib')

        header = self.read_header('canonical_template.csv')
        for column in ('url2', 'urlsuppl1', 'presentation-video', 'translations'):
            self.assertIn(column, header)

    def test_missing_url_gives_empty_pdf(self):
        code, _, _ = self.fixture_to_csv('missing_url.bib')

        self.assertEqual(code, 0)
        (row,) = self.read_rows('missing_url.csv')
        self.assertEqual(row['pdf'], '')
        self.assertEqual(row['url'], '')

    def test_editor_list_is_kept_verbatim(self):
        # pybtex would reject this editor list if it were parsed as names.
        code, _, _ = self.fixture_to_csv('comma_separated_editors.bib')

        self.assertEqual(code, 0)
        (row,) = self.read_rows('comma_separated_editors.csv')
        self.assertTrue(row['editor'].startswith('Andrew Johnston, Sam Ferguson'))

    def test_unreadable_authors_abort_and_name_the_key(self):
        src = self.write('bad.bib', self.bib_text(title='T', author='A, B, C, D'))

        code, _, err = self.run_tool('bib2csv', src, self.path('bad.csv'))

        self.assertEqual(code, 1)
        self.assertIn('k1', err)
        self.assertFalse(os.path.exists(self.path('bad.csv')))

    def test_skip_invalid_converts_the_readable_entries(self):
        good = self.bib_text(title='Good', author='Doe, Jane', url='https://x/2025/a.pdf')
        bad = '@inproceedings{k2,\n  title = {Bad},\n  author = {A, B, C, D}\n}\n'
        src = self.write('mixed.bib', good + bad)

        code, out, err = self.run_tool('bib2csv', src, self.path('mixed.csv'), '--skip-invalid')

        self.assertEqual(code, 0)
        self.assertIn('k2', err)
        self.assertEqual([r['key'] for r in self.read_rows('mixed.csv')], ['k1'])

    def test_names_lose_braces_and_latex_umlaut_marks(self):
        src = self.write('n.bib', self.bib_text(
            title='T', author='M{\\"u}ller, Jan and {Doe}, Jane', url='https://x/2025/a.pdf'
        ))

        self.run_tool('bib2csv', src, self.path('n.csv'))

        (row,) = self.read_rows('n.csv')
        self.assertEqual(row['authors'], 'Muller, Jan; Doe, Jane')

    def test_utf8_is_preserved(self):
        src = self.write('u.bib', self.bib_text(
            title='Música ✓', author='Dvořák, Antonín', url='https://x/2025/a.pdf'
        ))

        self.run_tool('bib2csv', src, self.path('u.csv'))

        (row,) = self.read_rows('u.csv')
        self.assertEqual(row['title'], 'Música ✓')
        self.assertEqual(row['authors'], 'Dvořák, Antonín')

    def test_entry_without_author_has_empty_authors(self):
        src = self.write('a.bib', self.bib_text(title='T', url='https://x/2025/a.pdf'))

        self.run_tool('bib2csv', src, self.path('a.csv'))

        (row,) = self.read_rows('a.csv')
        self.assertEqual(row['authors'], '')

    def test_missing_input_file(self):
        code, _, err = self.run_tool('bib2csv', self.path('nope.bib'), self.path('o.csv'))

        self.assertEqual(code, 1)
        self.assertTrue(err)


class TestCsv2Bib(BibCsvTestCase):
    def write_csv(self, rows, fieldnames, name='in.csv', encoding='utf-8'):
        path = self.path(name)
        with open(path, 'w', encoding=encoding, newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def convert(self, rows, fieldnames, **kwargs):
        src = self.write_csv(rows, fieldnames, **kwargs)
        code, _, err = self.run_tool('csv2bib', src, self.path('out.bib'))
        text = ''
        if os.path.exists(self.path('out.bib')):
            with open(self.path('out.bib'), encoding='utf-8') as f:
                text = f.read()
        return code, text, err

    def test_entry_is_written_without_state_columns(self):
        code, text, _ = self.convert(
            [{'key': 'k1', 'title': 'T', 'authors': 'Doe, Jane; Roe, Rick', 'status': 'done',
              'server': 'sandbox', 'deposition_id': '5', 'doi': '10.5281/zenodo.5',
              'skipped_files': '', 'error': '', 'updated_at': 'now'}],
            ['key', 'title', 'authors', 'status', 'server', 'deposition_id', 'doi',
             'skipped_files', 'error', 'updated_at'],
        )

        self.assertEqual(code, 0)
        self.assertIn('@inproceedings{k1,', text)
        self.assertIn('author = {Doe, Jane and Roe, Rick}', text)
        self.assertIn('doi = {10.5281/zenodo.5}', text)
        for name in ('status', 'server', 'deposition_id', 'skipped_files', 'error', 'updated_at'):
            self.assertNotIn(name, text)

    def test_empty_values_are_omitted(self):
        _, text, _ = self.convert(
            [{'key': 'k1', 'title': 'T', 'pages': '', 'doi': ''}], ['key', 'title', 'pages', 'doi']
        )

        self.assertNotIn('pages', text)
        self.assertNotIn('doi', text)

    def test_pdf_is_written_only_when_there_is_no_url(self):
        _, with_url, _ = self.convert(
            [{'key': 'k1', 'pdf': 'a.pdf', 'url': 'https://x/2025/a.pdf'}], ['key', 'pdf', 'url']
        )
        _, no_url, _ = self.convert([{'key': 'k1', 'pdf': 'a.pdf', 'url': ''}], ['key', 'pdf', 'url'])

        self.assertNotIn('pdf =', with_url)
        self.assertIn('pdf = {a.pdf}', no_url)

    def test_bom_and_header_case_are_tolerated(self):
        path = self.write('bom.csv', '﻿Key,Title\nk1,T\n')

        code, _, _ = self.run_tool('csv2bib', path, self.path('out.bib'))

        self.assertEqual(code, 0)

    def test_empty_key_is_an_error_and_nothing_is_written(self):
        code, text, err = self.convert(
            [{'key': 'k1', 'title': 'T'}, {'key': '', 'title': 'U'}], ['key', 'title']
        )

        self.assertEqual(code, 1)
        self.assertIn('row 3', err)
        self.assertEqual(text, '')

    def test_unbalanced_braces_are_an_error(self):
        code, _, err = self.convert([{'key': 'k1', 'title': 'a { b'}], ['key', 'title'])

        self.assertEqual(code, 1)
        self.assertIn('row 2', err)

    def test_missing_key_column(self):
        path = self.write('nokey.csv', 'title\nT\n')

        code, _, err = self.run_tool('csv2bib', path, self.path('out.bib'))

        self.assertEqual(code, 1)
        self.assertIn("'key' column", err)

    def test_utf8_is_preserved(self):
        _, text, _ = self.convert([{'key': 'k1', 'title': 'Música ✓'}], ['key', 'title'])

        self.assertIn('Música ✓', text)


class TestRoundTrip(BibCsvTestCase):
    def rows_of(self, fixture):
        self.fixture_to_csv(fixture)
        return self.read_rows(fixture.replace('.bib', '.csv'))

    def test_bib_csv_bib_csv_is_stable(self):
        for fixture in ('valid_paper.bib', 'valid_installation.bib', 'canonical_template.bib',
                        'missing_url.bib', 'comma_separated_editors.bib'):
            with self.subTest(fixture=fixture):
                first = self.rows_of(fixture)
                bib2 = self.path('again.bib')
                csv_path = self.path(fixture.replace('.bib', '.csv'))
                code, _, _ = self.run_tool('csv2bib', csv_path, bib2)
                self.assertEqual(code, 0)
                code, _, _ = self.run_tool('bib2csv', bib2, self.path('again.csv'))
                self.assertEqual(code, 0)

                # Empty fields are not written to the .bib, so compare filled values only.
                self.assertEqual(
                    [{k: v for k, v in row.items() if v} for row in self.read_rows('again.csv')],
                    [{k: v for k, v in row.items() if v} for row in first],
                )

    def test_unknown_columns_survive_the_round_trip(self):
        rows = self.rows_of('valid_installation.bib')

        self.assertEqual(rows[0]['track'], 'Installations')
        self.assertEqual(rows[0]['issn'], '2220-4806')


if __name__ == '__main__':
    unittest.main()
