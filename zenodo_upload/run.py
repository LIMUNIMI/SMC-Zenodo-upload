"""Processing of a whole CSV file: pre-checks, metadata display, upload of every row."""

import os
import pprint
import shutil

from zenodo_upload.console import secho
from zenodo_upload.metadata import build_deposition
from zenodo_upload.rows import CsvError, read_rows, save_rows, split_authors
from zenodo_upload.uploader import UPLOAD_FOLDER, upload_row
from zenodo_upload.zenodo import ZenodoClient

# Maximum size for PDF upload (100 MB) – PDFs over this limit will abort the whole run.
MAX_PDF_BYTES = 100 * 1024 * 1024


def process_csv(
    csvfilename,
    conference,
    secrets,
    verbose=False,
    upload_pdf=False,
    print_authors=False,
    production_zenodo=False
):
    """
    Build the metadata of every row of the CSV file and, when `upload_pdf`, upload it
    to Zenodo (`conference`: metadata.Conference; `secrets`: the tokens).
    Returns the number of rows that could not be completed.
    """
    fieldnames, rows = read_rows(csvfilename)
    target = 'production' if production_zenodo else 'sandbox'

    def save():
        save_rows(csvfilename, fieldnames, rows)

    if upload_pdf and not _prepare_upload(csvfilename, rows, target):
        return 0

    client = None
    done_now = already_done = failed = 0

    # loop through the individual rows
    for row in rows:
        pdf_name = row['pdf']

        if upload_pdf and is_done(row, target):
            secho(f"Skipping {pdf_name}: already done ({row['doi']}).", fg='green')
            already_done += 1
            continue

        if not os.path.exists(UPLOAD_FOLDER + pdf_name):
            raise CsvError(f'The PDF {pdf_name} does not exist in the upload folder.')

        if print_authors:
            for author_name in split_authors(row['authors']):
                pprint.pp(author_name)

        data = build_deposition(row, conference)
        if verbose:
            pprint.pp(data['metadata'])

        if upload_pdf:
            client = client or ZenodoClient.for_target(target, secrets)
            if upload_row(client, data, pdf_name, row, save):
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


def is_done(row, target):
    return row['status'] == 'done' and row['server'] == target


def _prepare_upload(csvfilename, rows, target):
    """
    Checks and preparations before the first upload. Returns False when the run must stop
    without uploading anything (nothing is left to do).
    Raises CsvError if a sandbox run would overwrite rows recorded for production, or if
    some PDFs are missing or too large.
    """
    _refuse_to_overwrite_production(rows, target)

    todo = [row for row in rows if not is_done(row, target)]
    if not _pdfs_are_usable(todo):
        raise CsvError("Upload aborted: fix the PDFs listed above.")  # before any upload

    if not todo:
        secho(f"Nothing to upload: all {len(rows)} rows are done on {target}.", fg='green')
        return False

    _restart_rows_of_other_server(todo, target)

    # Keep a copy of the file as it was before this run.
    shutil.copy2(csvfilename, csvfilename + '.bak')
    return True


def _refuse_to_overwrite_production(rows, target):
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


def _pdfs_are_usable(todo):
    """Check that no PDF of the rows still to do is missing or exceeds MAX_PDF_BYTES."""
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
        secho("Fix the missing files before running the upload.", fg='red')
        return False

    if oversized_pdfs:
        secho("One or more PDFs are larger than 100 MB and will fail to upload:", fg='red')
        for name, size in sorted(set(oversized_pdfs)):
            secho(f"  - {name}: {size / (1024 * 1024):.1f} MB", fg='red')
        secho(
            "Zenodo rejects these large PDF uploads (HTTP 413). "
            "Please compress or split these PDFs to be under 100 MB and try again.",
            fg='red'
        )
        secho("Aborting before starting any uploads. No Zenodo records were created.", fg='red')
        return False

    return True


def _restart_rows_of_other_server(todo, target):
    """Rows recorded for the other server restart from scratch."""
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
