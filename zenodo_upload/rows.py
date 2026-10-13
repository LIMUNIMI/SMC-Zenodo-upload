"""The CSV file: reading and validating the rows, saving their state."""

import csv
import datetime
import os


class CsvError(Exception):
    """The CSV file cannot be read or written; the message says why."""


REQUIRED_COLUMNS = ('key', 'pdf', 'title', 'authors')

# Columns written by the program, and the steps a row goes through. `status` is the last step
# completed; a run resumes at the following one.
STATE_COLUMNS = ('status', 'server', 'deposition_id', 'doi', 'skipped_files', 'error', 'updated_at')
STAGES = ('pending', 'created', 'uploaded', 'published', 'done')


def split_authors(value):
    return [name.strip() for name in value.split(';') if name.strip()]


def field(row, name, default=None):
    """Value of a CSV column, or default when the column is missing or empty."""
    return row.get(name) or default


def read_rows(csvfilename):
    """
    Read the CSV file. Returns (fieldnames, rows): column names in lower case with the state
    columns added when missing, and one dict per row with stripped values.
    Raises CsvError, listing all problems, before anything is uploaded.
    """
    header, rows = _read_csv(csvfilename)

    missing_columns = [name for name in REQUIRED_COLUMNS if name not in header]
    if missing_columns:
        raise CsvError(f"{csvfilename}: missing column(s): {', '.join(missing_columns)}")

    fieldnames = header + [name for name in STATE_COLUMNS if name not in header]
    problems = _check_rows(rows)
    if problems:
        raise CsvError(f"{csvfilename}:\n  " + "\n  ".join(problems))
    return fieldnames, rows


def _read_csv(csvfilename):
    """Lower-cased header and rows as dicts of stripped values."""
    with open(csvfilename, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        header = [name.strip().lower() for name in reader.fieldnames or []]
        reader.fieldnames = header
        rows = [
            {name: (value or '').strip() for name, value in row.items() if name is not None}
            for row in reader
        ]
    return header, rows


def _check_rows(rows):
    """Fill in the state columns of every row and return the list of problems found."""
    problems = []
    seen_keys = set()
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        for name in STATE_COLUMNS:
            row.setdefault(name, '')
        row['status'] = row['status'] or 'pending'
        label = f"row {number} ({row['key'] or 'no key'})"
        empty = [name for name in REQUIRED_COLUMNS if not row[name]]
        if empty:
            problems.append(f"{label}: empty {', '.join(empty)}")
        if row['key'] in seen_keys:
            problems.append(f"{label}: duplicate key")
        seen_keys.add(row['key'])
        affiliations = row.get('affiliations')
        if affiliations and len(affiliations.split(';')) != len(split_authors(row['authors'])):
            problems.append(f"{label}: affiliations do not match the number of authors")
        if row['status'] not in STAGES:
            problems.append(f"{label}: unknown status '{row['status']}'")
        if row['server'] not in ('', 'sandbox', 'production'):
            problems.append(f"{label}: unknown server '{row['server']}'")
    return problems


def save_rows(csvfilename, fieldnames, rows):
    """Rewrite the CSV file atomically: temporary file in the same folder, then replace."""
    temp = csvfilename + '.tmp'
    try:
        with open(temp, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, restval='')
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp, csvfilename)
    except OSError as error:
        if os.path.exists(temp):
            os.remove(temp)
        raise CsvError(
            f"Cannot write {csvfilename}: {error}. If the file is open in another program, "
            "close it and run again: rows resume from the last step that was saved."
        ) from error


def record(row, save, **changes):
    """Update the state columns of a row and write the CSV file."""
    row.update(changes)
    row['updated_at'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save()
