"""
Convert between a conference .bib file (one entry per paper, `url` ending with
the PDF name) and the CSV read by zenodo_upload.

    python bibcsv/bibcsv.py bib2csv proceedings.bib upload/proceedings.csv
    python bibcsv/bibcsv.py csv2bib upload/proceedings.csv proceedings.bib

CSV format: one row per entry, UTF-8, comma-separated, header row required.
  - key:        the bibtex key
  - pdf:        file name in upload/ (last segment of the .bib `url`)
  - authors:    "Last, First; Last, First" (`and` in the .bib)
  - every other .bib field is a lower-case column of its own (track, note, ...)
  - status, server, deposition_id, doi, skipped_files, error, updated_at are
    written by zenodo_upload and are left empty by bib2csv (`doi` is also
    filled from the .bib when it has one).
"""

import argparse
import csv
import sys

from pybtex.database.input import bibtex
from pybtex.exceptions import PybtexError

LEADING_COLUMNS = [
    'key', 'pdf', 'title', 'authors', 'affiliations', 'abstract', 'pages',
    'address', 'booktitle', 'note', 'isbn', 'issn', 'url',
]
STATE_COLUMNS = [
    'status', 'server', 'deposition_id', 'doi', 'skipped_files', 'error', 'updated_at',
]
# Only authors are parsed as names (the uploader needs them); `editor` is kept
# verbatim, so a badly formatted editor list does not make an entry unreadable.
PERSON_FIELDS = ['author']
PERSON_COLUMN = 'authors'
# Columns that are not written to the .bib (`pdf` only when there is no url)
NOT_BIB_FIELDS = {'key', 'status', 'server', 'deposition_id', 'skipped_files', 'error', 'updated_at'}


class _CollectingParser(bibtex.Parser):
    """pybtex parser that records the entries it cannot read instead of aborting."""

    def __init__(self):
        super().__init__(person_fields=PERSON_FIELDS)
        self.problems = []  # (key or None, message)

    def process_entry(self, entry_type, key, fields):
        try:
            super().process_entry(entry_type, key, fields)
        except PybtexError as error:
            self.problems.append((key, str(error)))

    def handle_error(self, error):
        self.problems.append((None, str(error)))


def _person_to_text(person):
    # Same clean-up the uploader applied to names read from the .bib.
    name = str(person)
    for char in ('{', '}', '\\"'):
        name = name.replace(char, '')
    return name


def read_bib(path):
    """Return (rows, problems): one dict per readable entry, and the entries that failed."""
    parser = _CollectingParser()
    try:
        data = parser.parse_file(path)
    except PybtexError as error:  # unrecoverable syntax errors
        parser.problems.append((None, str(error)))
        return [], parser.problems

    rows = []
    for key, entry in data.entries.items():
        row = {'key': key}
        for field, value in entry.fields.items():
            column = field.lower()
            if column in row:
                parser.problems.append((key, f"field '{field}' repeated or reserved"))
                continue
            row[column] = value
        for persons in entry.persons.values():
            row[PERSON_COLUMN] = '; '.join(_person_to_text(person) for person in persons)

        url = row.get('url', '')
        if url:
            row['pdf'] = url.rsplit('/', 1)[-1]
        rows.append(row)
    return rows, parser.problems


def write_csv(path, rows):
    extras = []
    for row in rows:
        for column in row:
            if column not in LEADING_COLUMNS and column not in STATE_COLUMNS and column not in extras:
                extras.append(column)
    fieldnames = LEADING_COLUMNS + extras + STATE_COLUMNS
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval='')
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [name.strip().lower() for name in reader.fieldnames or []]
        if 'key' not in reader.fieldnames:
            raise ValueError("the CSV has no 'key' column")
        return list(reader)


def _bib_value(value):
    if value.count('{') != value.count('}'):
        raise ValueError(f'unbalanced braces in {value!r}')
    return '{' + value + '}'


def format_entry(row):
    """Format one CSV row as a @inproceedings entry."""
    key = row['key'].strip()
    if not key:
        raise ValueError('empty key')
    fields = []
    for column, value in row.items():
        if column is None:  # more cells than header columns
            continue
        value = (value or '').strip()
        if not value or column in NOT_BIB_FIELDS:
            continue
        if column == 'pdf' and (row.get('url') or '').strip():
            continue  # derivable from the url
        if column == PERSON_COLUMN:
            field = 'author'
            value = ' and '.join(name.strip() for name in value.split(';') if name.strip())
        else:
            field = column
        fields.append((field, _bib_value(value)))
    body = ',\n'.join(f'  {field} = {value}' for field, value in fields)
    return f'@inproceedings{{{key},\n{body}\n}}\n'


def bib2csv(args):
    rows, problems = read_bib(args.bib)
    for key, message in problems:
        label = key if key is not None else '(file)'
        print(f'{label}: {message}', file=sys.stderr)
    if problems and not args.skip_invalid:
        print(
            f'{len(problems)} problem(s) found, nothing written. '
            'Fix the .bib or use --skip-invalid to convert the readable entries.',
            file=sys.stderr
        )
        return 1
    write_csv(args.csv, rows)
    print(f'{len(rows)} entries written to {args.csv}')
    return 0


def csv2bib(args):
    entries, problems = [], []
    for number, row in enumerate(read_csv(args.csv), start=2):  # row 1 is the header
        try:
            entries.append(format_entry(row))
        except ValueError as error:
            problems.append(f'row {number}: {error}')
    if problems:
        for message in problems:
            print(message, file=sys.stderr)
        print('Nothing written.', file=sys.stderr)
        return 1
    with open(args.bib, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(entries))
    print(f'{len(entries)} entries written to {args.bib}')
    return 0


def main(argv=None):
    cli = argparse.ArgumentParser(prog='bibcsv', description=__doc__.split('\n\n')[0])
    commands = cli.add_subparsers(dest='command', required=True)

    to_csv = commands.add_parser('bib2csv', help='Convert a .bib file to CSV.')
    to_csv.add_argument('bib')
    to_csv.add_argument('csv')
    to_csv.add_argument(
        '--skip-invalid',
        action='store_true',
        help='Write the readable entries even if some entries have errors.'
    )
    to_csv.set_defaults(func=bib2csv)

    to_bib = commands.add_parser('csv2bib', help='Convert a CSV file to .bib.')
    to_bib.add_argument('csv')
    to_bib.add_argument('bib')
    to_bib.set_defaults(func=csv2bib)

    args = cli.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
