"""Upload of one paper to Zenodo, resumable from the last step recorded in its row."""

import json
import os

from zenodo_upload.console import print_response, secho
from zenodo_upload.rows import STAGES, record
from zenodo_upload.zenodo import succeeded

UPLOAD_FOLDER = './upload/'

# Maximum size for automatic supplementary upload (100 MB)
MAX_SUPP_BYTES = 100 * 1024 * 1024


def upload_row(client, metadata, pdf_path, row, save):
    """
    Create the deposition and upload the .pdf and the supplementary files, through `client`
    (a ZenodoClient). The deposition stays a draft: publishing is `publish_row`.

    Every completed step is recorded in `row` and saved with `save()`; a row that stopped
    halfway continues from its last completed step. Returns True when the row is `uploaded`.
    """
    stage = STAGES.index(row['status'])

    secho(f"Starting new upload for: {pdf_path} to {client.url}", fg='yellow')

    if stage < 1 and not _create(client, metadata, pdf_path, row, save):
        return False
    if stage < 2 and not _upload_files(client, pdf_path, row, save, resumed=(stage == 1)):
        return False

    # If any supplementary files were skipped, they are listed in the skipped_files column.
    if row['skipped_files']:
        secho(
            f"Supplementary files skipped for {pdf_path}: {row['skipped_files']}. "
            f"Recorded in the skipped_files column.",
            fg='yellow'
        )
    return True


def publish_row(client, pdf_path, row, save):
    """
    Publish the uploaded deposition of a row and read its DOI, through `client`.
    A `published` row (DOI not read yet) only reads the DOI. Returns True when the row is done.
    """
    stage = STAGES.index(row['status'])

    secho(f"Starting publication of: {pdf_path} on {client.url}", fg='yellow')

    if stage < 3 and not _publish(client, pdf_path, row, save):
        return False
    return _confirm_doi(client, pdf_path, row, save)


def _fail(row, save, message, response, error, show_response=True):
    """Report a failed request and record it in the row; always returns False."""
    secho(f"{message}, status code: {response.status_code}", fg='red')
    if show_response:
        print_response(response)
    record(row, save, error=f"{error}: HTTP {response.status_code}")
    return False


def _create(client, metadata, pdf_path, row, save):
    new_deposition = client.create(metadata)
    if not succeeded(new_deposition):
        return _fail(
            row, save, f"Error happened during submission {pdf_path}", new_deposition,
            "create failed"
        )
    record(
        row, save, status='created', server=client.target, doi='', skipped_files='', error='',
        deposition_id=str(json.loads(new_deposition.text)["id"])
    )
    return True


def _upload_files(client, pdf_path, row, save, resumed):
    """Upload the PDF and its supplementary files; `resumed` if the deposition already exists."""
    submission_id = row['deposition_id']

    # A resumed deposition may already hold some of the files
    already_uploaded = set()
    if resumed:
        listing = client.list_files(submission_id)
        if not succeeded(listing):
            return _fail(
                row, save, f"Error happened while listing the files of {pdf_path}", listing,
                "file listing failed", show_response=False
            )
        already_uploaded = {item['filename'] for item in listing.json()}

    if pdf_path not in already_uploaded:
        add_file = client.upload_file(
            submission_id, pdf_path, os.path.join(UPLOAD_FOLDER, pdf_path)
        )
        if not succeeded(add_file):
            return _fail(
                row, save, f"Error happened during file upload of {pdf_path}", add_file,
                "file upload failed"
            )

    skipped = _upload_supplementary(client, submission_id, pdf_path, already_uploaded)

    secho(f"{pdf_path} submitted with ID {submission_id}", fg='green')
    record(row, save, status='uploaded', error='', skipped_files=';'.join(skipped))
    return True


def _upload_supplementary(client, submission_id, pdf_path, already_uploaded):
    """Upload `<pdfbase>_*` files; returns the names of those skipped or rejected."""
    skipped = []
    prefix = pdf_path[:-4] + "_"
    for name in os.listdir(UPLOAD_FOLDER):
        if not name.startswith(prefix) or name in already_uploaded:
            continue

        full_path = os.path.join(UPLOAD_FOLDER, name)
        file_size = os.path.getsize(full_path)

        # Pre-check size: skip if over MAX_SUPP_BYTES
        if file_size > MAX_SUPP_BYTES:
            secho(
                f"Skipping supplementary file {name} "
                f"({file_size / (1024 * 1024):.1f} MB) – above automatic upload limit "
                f"({MAX_SUPP_BYTES / (1024 * 1024):.0f} MB).",
                fg='yellow'
            )
            secho(
                "Upload this file manually via the Zenodo web UI and attach it to the deposition.",
                fg='yellow'
            )
            skipped.append(name)
            continue

        secho(f"Starting upload for supplementary file: {name} to {client.url}", fg='yellow')
        add_file = client.upload_file(submission_id, name, full_path)

        # If upload of file is unsuccessful, warn and continue with the other files
        if not succeeded(add_file):
            secho(
                f"Error happened during supplementary file upload of {name}, "
                f"status code: {add_file.status_code}",
                fg='red'
            )
            if add_file.status_code == 413:
                secho(
                    "Server reports the file is too large (HTTP 413). "
                    "You must upload this file manually via the Zenodo web UI.",
                    fg='red'
                )
            print_response(add_file)
            skipped.append(name)
    return skipped


def _publish(client, pdf_path, row, save):
    submission_id = row['deposition_id']
    publish_record = client.publish(submission_id)

    # If publish unsuccessful, abort (unless the answer was lost and it did get published)
    if not succeeded(publish_record):
        secho(
            f"Error happened during publish, status code: {publish_record.status_code}",
            fg='red'
        )
        print_response(publish_record)
        if not client.is_published(submission_id):
            record(row, save, error=f"publish failed: HTTP {publish_record.status_code}")
            return False
        secho("The deposition turns out to be published anyway.", fg='yellow')
    secho(f"{pdf_path} PUBLISHED with ID {submission_id}", fg='green')
    record(row, save, status='published', error='')
    return True


def _confirm_doi(client, pdf_path, row, save):
    """Get back the deposition to confirm the DOI."""
    submission_id = row['deposition_id']
    retrieved_deposition = client.get(submission_id)
    retrieved_doi = None
    if succeeded(retrieved_deposition):
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
    return True
