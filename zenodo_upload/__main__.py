########################################################
'''
Written by Benedikte Wallace, 2018, edited by Charles Martin, 2024, and Stefano Fasciani 2025-2026.

This script reads a CSV file (one row per paper, see README; bibcsv/bibcsv.py
converts the conference's .bib file to it) and creates a deposition record on the Zenodo
website. The metadata from the CSV rows are tied to the article (.pdf file) and
are published to Zenodo resulting in the creation of a DOI. The outcome of every
row (status, deposition id, DOI, errors) is written back to the same CSV file after each step,
so an interrupted run can be repeated: finished rows are skipped and the others resume
from their last completed step.

Supplementary files:

If a resource contains supplementary files that should be uploaded together with the paper, each
supplementary file should have the same base file name as the paper PDF with an additional
suffix such as _file01, _file02, etc., appended before the extension, e.g.:

    paper_10.pdf
    paper_10_file01.mp4
    paper_10_file02.mov

Supplementary files larger than 100 MB are skipped by this script: they are NOT uploaded via
the API. The script:
  - prints a warning for each skipped file,
  - lists the skipped filenames, ";"-separated, in the skipped_files column of the CSV, so they
    can be uploaded manually via the Zenodo web UI.

Zenodo displays files alphabetically in its UI.
'''
########################################################


import json
import requests
import argparse
import csv
import datetime
import os
import shutil
import sys
import tomllib
import pprint

UPLOAD_FOLDER = './upload/'

# Per-edition conference metadata, edit conference.toml for each edition:
with open("conference.toml", "rb") as f:
    conference_data = tomllib.load(f)
PUBLICATION_DATE = conference_data['PUBLICATION_DATE']
CONFERENCE_DATES = conference_data['CONFERENCE_DATES']
CONFERENCE_TITLE = conference_data['CONFERENCE_TITLE']
CONFERENCE_ACRONYM = conference_data['CONFERENCE_ACRONYM']
CONFERENCE_URL = conference_data['CONFERENCE_URL']
ZENODO_COMMUNITY = conference_data['ZENODO_COMMUNITY']

# Maximum size for automatic supplementary upload (100 MB)
MAX_SUPP_BYTES = 100 * 1024 * 1024
# Maximum size for PDF upload (100 MB) – PDFs over this limit will abort the whole run.
MAX_PDF_BYTES = 100 * 1024 * 1024

# Columns written by the program, and the steps a row goes through. `status` is the last step
# completed; a run resumes at the following one.
STATE_COLUMNS = ('status', 'server', 'deposition_id', 'doi', 'skipped_files', 'error', 'updated_at')
STAGES = ('pending', 'created', 'uploaded', 'published', 'done')

# Tokens, replace with public and sandbox tokens from Zenodo:
with open("secrets.toml", "rb") as f:
    secret_data = tomllib.load(f)


ANSI_COLORS = {'red': 31, 'green': 32, 'yellow': 33}
if os.name == 'nt' and sys.stdout.isatty():
    os.system('')  # enables ANSI escape sequences in the Windows console


def secho(message, fg=None):
    """Print a message, coloured when writing to a terminal."""
    if fg in ANSI_COLORS and sys.stdout.isatty():
        print(f"\033[{ANSI_COLORS[fg]}m{message}\033[0m")
    else:
        print(message)


def _print_response_json_or_text(resp, color='red'):
    """Helper to print a requests.Response as JSON if possible, otherwise as raw text."""
    try:
        data = resp.json()
        secho(data, fg=color)
    except ValueError:
        # Not JSON (e.g., HTML 413 page); print raw text
        secho(resp.text, fg=color)


def record(row, save, **changes):
    """Update the state columns of a row and write the CSV file."""
    row.update(changes)
    row['updated_at'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save()


def upload_to_zenodo(metadata, pdf_path, row, save, production_zenodo=False):
    '''
    upload_to_zenodo(metadata, pdf_path, row, save):
    - connects to zenodo REST API,
    - creates a new record,
    - enters metadata,
    - uploads the .pdf and supplementary files
    - publishes it and reads its DOI

    Every completed step is recorded in `row` and saved with `save()`; a row that stopped
    halfway continues from its last completed step. Returns True when the row is done.
    '''

    target = 'production' if production_zenodo else 'sandbox'
    if production_zenodo:
        ZENODO_URL = 'https://zenodo.org'
        TOKEN = secret_data['PUBLIC_TOKEN']  # either SANDBOX_TOKEN or PUBLIC_TOKEN
    else:
        ZENODO_URL = 'https://sandbox.zenodo.org'
        TOKEN = secret_data['SANDBOX_TOKEN']

    stage = STAGES.index(row['status'])

    # Track supplementary files that were too large or otherwise skipped
    skipped_supplementary = []

    secho(f"Starting new upload for: {pdf_path} to {ZENODO_URL}", fg='yellow')
    url = ZENODO_URL + '/api/deposit/depositions'
    access_depositions = requests.get(url, params={'access_token': TOKEN})
    secho(f"Access depositions: {access_depositions.status_code}", fg='yellow')

    # Create new paper submission - add parsed metadata
    if stage < 1:
        headers = {"Content-Type": "application/json"}
        new_deposition = requests.post(
            url,
            params={'access_token': TOKEN},
            json=metadata,
            headers=headers
        )

        # If creation of new deposition is unsuccessful, abort
        if new_deposition.status_code > 210:
            secho(
                f"Error happened during submission {pdf_path}, status code: "
                f"{new_deposition.status_code}",
                fg='red'
            )
            _print_response_json_or_text(new_deposition, color='red')
            record(row, save, error=f"create failed: HTTP {new_deposition.status_code}")
            return False

        record(
            row, save, status='created', server=target, doi='', skipped_files='', error='',
            deposition_id=str(json.loads(new_deposition.text)["id"])
        )

    submission_id = row['deposition_id']

    # Upload the pdf and the supplementary files
    if stage < 2:
        url_files = (
            ZENODO_URL +
            "/api/deposit/depositions/{id}/files?access_token={token}".format(
                id=submission_id,
                token=TOKEN
            )
        )

        # A resumed deposition may already hold some of the files
        already_uploaded = set()
        if stage == 1:
            listing = requests.get(
                f"{ZENODO_URL}/api/deposit/depositions/{submission_id}/files",
                params={'access_token': TOKEN}
            )
            if listing.status_code > 210:
                secho(
                    f"Error happened while listing the files of {pdf_path}, status code: "
                    f"{listing.status_code}",
                    fg='red'
                )
                record(row, save, error=f"file listing failed: HTTP {listing.status_code}")
                return False
            already_uploaded = {item['filename'] for item in listing.json()}

        if pdf_path not in already_uploaded:
            upload_metadata = {'filename': pdf_path}
            pdf_full_path = os.path.join(UPLOAD_FOLDER, pdf_path)
            with open(pdf_full_path, 'rb') as pdf_file:
                add_file = requests.post(url_files, data=upload_metadata, files={'file': pdf_file})

            # If upload of file is unsuccessful, abort
            if add_file.status_code > 210:
                secho(
                    f"Error happened during file upload of {pdf_path}, status code: "
                    f"{add_file.status_code}",
                    fg='red'
                )
                _print_response_json_or_text(add_file, color='red')
                record(row, save, error=f"file upload failed: HTTP {add_file.status_code}")
                return False

        # Upload supplementary files (if any)
        all_files = os.listdir(UPLOAD_FOLDER)
        pdf_fname_prefix = pdf_path[:-4] + "_"
        matching_files = [file for file in all_files if file.startswith(pdf_fname_prefix)]

        for extra_file_path in matching_files:
            if extra_file_path == pdf_path or extra_file_path in already_uploaded:
                continue

            full_extra_path = os.path.join(UPLOAD_FOLDER, extra_file_path)
            file_size = os.path.getsize(full_extra_path)

            # Pre-check size: skip if over MAX_SUPP_BYTES
            if file_size > MAX_SUPP_BYTES:
                secho(
                    f"Skipping supplementary file {extra_file_path} "
                    f"({file_size / (1024 * 1024):.1f} MB) – above automatic upload limit "
                    f"({MAX_SUPP_BYTES / (1024 * 1024):.0f} MB).",
                    fg='yellow'
                )
                secho(
                    "Upload this file manually via the Zenodo web UI and attach it to the deposition.",
                    fg='yellow'
                )
                skipped_supplementary.append(extra_file_path)
                continue

            secho(
                f"Starting upload for supplementary file: {extra_file_path} to {ZENODO_URL}",
                fg='yellow'
            )
            upload_metadata = {'filename': extra_file_path}
            with open(full_extra_path, 'rb') as extra_file:
                add_file = requests.post(url_files, data=upload_metadata, files={'file': extra_file})

            # If upload of file is unsuccessful, warn and continue
            if add_file.status_code > 210:
                secho(
                    f"Error happened during supplementary file upload of {extra_file_path}, "
                    f"status code: {add_file.status_code}",
                    fg='red'
                )

                if add_file.status_code == 413:
                    secho(
                        "Server reports the file is too large (HTTP 413). "
                        "You must upload this file manually via the Zenodo web UI.",
                        fg='red'
                    )

                _print_response_json_or_text(add_file, color='red')
                skipped_supplementary.append(extra_file_path)
                # Do not abort the whole deposition; continue with other files
                continue

        secho(f"{pdf_path} submitted with ID {submission_id}", fg='green')
        record(row, save, status='uploaded', error='',
               skipped_files=';'.join(skipped_supplementary))

    # publish the new deposition
    if stage < 3:
        publish_record = requests.post(
            f"{ZENODO_URL}/api/deposit/depositions/{submission_id}/actions/publish",
            params={'access_token': TOKEN}
        )

        # If publish unsuccessful, abort (unless the answer was lost and it did get published)
        if publish_record.status_code > 210:
            secho(
                f"Error happened during publish, status code: {publish_record.status_code}",
                fg='red'
            )
            _print_response_json_or_text(publish_record, color='red')
            if not deposition_is_published(ZENODO_URL, submission_id, TOKEN):
                record(row, save, error=f"publish failed: HTTP {publish_record.status_code}")
                return False
            secho("The deposition turns out to be published anyway.", fg='yellow')
        secho(f"{pdf_path} PUBLISHED with ID {submission_id}", fg='green')
        record(row, save, status='published', error='')

    # get back the deposition to confirm the DOI
    retrieved_deposition = requests.get(
        f"{ZENODO_URL}/api/deposit/depositions/{submission_id}",
        params={'access_token': TOKEN}
    )
    retrieved_doi = None
    if retrieved_deposition.status_code <= 210:
        retrieved_doi = retrieved_deposition.json().get('doi')
    if not retrieved_doi:
        secho(
            f"{pdf_path} is published (ID {submission_id}) but its DOI could not be read; "
            "run again to retry.",
            fg='red'
        )
        record(row, save, error="doi not available")
        return False
    secho(f"{pdf_path} confirmed DOI is {retrieved_doi}", fg='green')
    record(row, save, status='done', doi=retrieved_doi, error='')

    # If any supplementary files were skipped, they are listed in the skipped_files column.
    if row['skipped_files']:
        secho(
            f"Supplementary files skipped for {pdf_path}: {row['skipped_files']}. "
            f"Recorded in the skipped_files column.",
            fg='yellow'
        )
    return True


def deposition_is_published(zenodo_url, submission_id, token):
    """True if Zenodo reports the deposition as already published."""
    response = requests.get(
        f"{zenodo_url}/api/deposit/depositions/{submission_id}",
        params={'access_token': token}
    )
    try:
        return response.status_code <= 210 and bool(response.json().get('submitted'))
    except ValueError:
        return False


class CsvError(Exception):
    """The CSV file cannot be read or written; the message says why."""


REQUIRED_COLUMNS = ('key', 'pdf', 'title', 'authors')


def split_authors(value):
    return [name.strip() for name in value.split(';') if name.strip()]


def read_rows(csvfilename):
    """
    Read the CSV file. Returns (fieldnames, rows): column names in lower case with the state
    columns added when missing, and one dict per row with stripped values.
    Raises CsvError, listing all problems, before anything is uploaded.
    """
    with open(csvfilename, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        header = [name.strip().lower() for name in reader.fieldnames or []]
        reader.fieldnames = header
        rows = [
            {name: (value or '').strip() for name, value in row.items() if name is not None}
            for row in reader
        ]

    missing_columns = [name for name in REQUIRED_COLUMNS if name not in header]
    if missing_columns:
        raise CsvError(f"{csvfilename}: missing column(s): {', '.join(missing_columns)}")

    fieldnames = header + [name for name in STATE_COLUMNS if name not in header]
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
    if problems:
        raise CsvError(f"{csvfilename}:\n  " + "\n  ".join(problems))
    return fieldnames, rows


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


def field(row, name, default=None):
    """Value of a CSV column, or default when the column is missing or empty."""
    return row.get(name) or default


def format_metadata(
    csvfilename,
    verbose=False,
    upload_pdf=False,
    print_authors=False,
    production_zenodo=False
):
    '''
    format_metadata(csvfilename):
    - formats contents of the rows in the CSV file referenced by csvfilename
    - for each row, metadata is formatted and the upload function
      above is called in order to publish record
    Returns the number of rows that could not be completed.
    '''
    fieldnames, rows = read_rows(csvfilename)
    target = 'production' if production_zenodo else 'sandbox'

    def save():
        save_rows(csvfilename, fieldnames, rows)

    def is_done(row):
        return row['status'] == 'done' and row['server'] == target

    # If we are going to upload PDFs, pre-check that none of them exceed MAX_PDF_BYTES.
    if upload_pdf:
        # A sandbox run would restart (and so overwrite) rows recorded for the production server.
        protected = [
            row['key'] for row in rows
            if row['server'] == 'production' and row['status'] != 'pending' and target == 'sandbox'
        ]
        if protected:
            raise CsvError(
                "These rows are recorded for the production server and a sandbox run would "
                "overwrite them: " + ', '.join(protected) + ". Use --production, or run on a "
                "copy of the file."
            )

        todo = [row for row in rows if not is_done(row)]
        oversized_pdfs = []
        missing_pdfs = []
        for row in todo:
            pdf_name = row['pdf']
            pdf_path = os.path.join(UPLOAD_FOLDER, pdf_name)

            if not os.path.exists(pdf_path):
                missing_pdfs.append(pdf_name)
                continue

            size = os.path.getsize(pdf_path)
            if size > MAX_PDF_BYTES:
                oversized_pdfs.append((pdf_name, size))

        if missing_pdfs:
            secho(
                "The following PDFs referenced in the CSV file do not exist in the upload folder:",
                fg='red'
            )
            for name in sorted(set(missing_pdfs)):
                secho(f"  - {name}", fg='red')
            secho(
                "Fix the missing files before running the upload.",
                fg='red'
            )
            # Abort before any upload.
            return 0

        if oversized_pdfs:
            secho(
                "One or more PDFs are larger than 100 MB and will fail to upload:",
                fg='red'
            )
            for name, size in sorted(set(oversized_pdfs)):
                secho(
                    f"  - {name}: {size / (1024 * 1024):.1f} MB",
                    fg='red'
                )
            secho(
                "Zenodo rejects these large PDF uploads (HTTP 413). "
                "Please compress or split these PDFs to be under 100 MB and try again.",
                fg='red'
            )
            secho(
                "Aborting before starting any uploads. No Zenodo records were created.",
                fg='red'
            )
            return 0

        if not todo:
            secho(f"Nothing to upload: all {len(rows)} rows are done on {target}.", fg='green')
            return 0

        # Rows recorded for the other server restart from scratch.
        restarted = [row for row in todo if row['server'] not in ('', target)]
        for row in restarted:
            row.update(status='pending', server='', deposition_id='', doi='',
                       skipped_files='', error='')
        if restarted:
            secho(
                f"{len(restarted)} row(s) were recorded for the other server and restart from "
                "scratch on " + target + ": " + ', '.join(row['key'] for row in restarted),
                fg='yellow'
            )

        # Keep a copy of the file as it was before this run.
        shutil.copy2(csvfilename, csvfilename + '.bak')

    done_now = already_done = failed = 0

    # loop through the individual rows
    for row in rows:
        pdf_name = row['pdf']

        if upload_pdf and is_done(row):
            secho(f"Skipping {pdf_name}: already done ({row['doi']}).", fg='green')
            already_done += 1
            continue

        if not os.path.exists(UPLOAD_FOLDER + pdf_name):
            secho(f'PDF: {pdf_name} does not exist in the upload folder!', fg='red')
            raise Exception(f'The PDF {pdf_name} did not exist in the upload folder.')

        affiliations = [a.strip() for a in field(row, 'affiliations', '').split(';')]
        creators = []
        for index, author_name in enumerate(split_authors(row['authors'])):
            creator = {'name': author_name}
            if field(row, 'affiliations') and affiliations[index]:
                creator['affiliation'] = affiliations[index]
            creators.append(creator)
            if print_authors:
                pprint.pp(author_name)

        pages = field(row, 'pages')
        partof_title = field(row, 'booktitle')
        conf_session = field(row, 'note')

        data = {
            'metadata': {
                'title': row['title'],
                'upload_type': 'publication',
                'publication_type': 'conferencepaper',
                'description': field(row, 'abstract', '---'),  # '---' if no abstract is given
                'conference_title': CONFERENCE_TITLE,
                'conference_acronym': CONFERENCE_ACRONYM,
                'conference_dates': CONFERENCE_DATES,
                'conference_place': field(row, 'address', 'Address'),
                'conference_url': CONFERENCE_URL,
                'publication_date': PUBLICATION_DATE,
                'partof_title': partof_title,
                'imprint_title': partof_title,
                'creators': creators,
                'communities': [{'identifier': ZENODO_COMMUNITY}],  # adds to the conference's community
                'imprint_isbn': field(row, 'isbn'),
                'imprint_issn': field(row, 'issn')
            }
        }

        if conf_session is not None:
            data['metadata']['conference_session'] = conf_session

        if pages is not None:
            data['metadata']['partof_pages'] = pages

        if verbose:
            pprint.pp(data['metadata'])

        if upload_pdf:
            if upload_to_zenodo(
                data,
                pdf_name,
                row,
                save,
                production_zenodo=production_zenodo
            ):
                done_now += 1
            else:
                failed += 1

    if upload_pdf:
        secho(
            f"Summary: {done_now} uploaded, {already_done} already done, {failed} not completed"
            + (" (see the error column, then run again to resume)." if failed else "."),
            fg='red' if failed else 'green'
        )
    return failed


def upload(csvfile, production):
    """Process metadata from a CSV file and upload to Zenodo."""
    read_rows(csvfile)  # fail on an unusable file before asking for confirmation
    if production:
        secho(
            "WARNING! You are uploading to the production Zenodo server! "
            "Make sure you are ready! Cancel if not!",
            fg="red"
        )
    else:
        secho(
            "You are uploading to the sandbox Zenodo server! Test here as much as you want.",
            fg="green"
        )
    input("Press Enter to continue or Ctrl-C to abort.")
    return format_metadata(
        csvfile,
        upload_pdf=True,
        verbose=False,
        print_authors=False,
        production_zenodo=production
    )


def check(csvfile, authors):
    """Process metadata from a CSV file and print out to check it."""
    if authors:
        format_metadata(
            csvfile,
            upload_pdf=False,
            verbose=False,
            print_authors=True,
            production_zenodo=False
        )
    else:
        format_metadata(
            csvfile,
            upload_pdf=False,
            verbose=True,
            print_authors=False,
            production_zenodo=False
        )


def existing_file(path):
    if not os.path.exists(path):
        raise argparse.ArgumentTypeError(f"path '{path}' does not exist")
    return path


def main(argv=None):
    cli = argparse.ArgumentParser(prog='zenodo_upload')
    commands = cli.add_subparsers(dest='command', required=True)

    upload_cmd = commands.add_parser(
        'upload', help='Process metadata from a CSV file and upload to Zenodo.'
    )
    upload_cmd.add_argument('csvfile', type=existing_file)
    upload_cmd.add_argument('--production', action='store_true')

    check_cmd = commands.add_parser(
        'check', help='Process metadata from a CSV file and print out to check it.'
    )
    check_cmd.add_argument('csvfile', type=existing_file)
    check_cmd.add_argument('--authors', action='store_true')

    args = cli.parse_args(argv)
    try:
        if args.command == 'upload':
            failed = upload(args.csvfile, args.production)
        else:
            failed = check(args.csvfile, args.authors)
    except CsvError as error:
        secho(str(error), fg='red')
        sys.exit(1)
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
