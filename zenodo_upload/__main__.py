########################################################
'''
Written by Benedikte Wallace, 2018, edited by Charles Martin, 2024, and Stefano Fasciani 2025-2026.
Originally written for NIME; refactored and made conference-agnostic by Giorgio Presti, 2026.

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


import argparse
import os
import sys
import tomllib

if __package__ in (None, ''):
    # Started as `python zenodo_upload`: make the package importable by its absolute name.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zenodo_upload.console import secho
from zenodo_upload.metadata import Conference
from zenodo_upload.rows import CsvError, STAGES, STATE_COLUMNS, read_rows
from zenodo_upload.run import MAX_PDF_BYTES, process_csv
from zenodo_upload.uploader import MAX_SUPP_BYTES, UPLOAD_FOLDER

# Per-edition conference metadata, edit conference.toml for each edition:
with open("conference.toml", "rb") as f:
    conference_data = tomllib.load(f)
PUBLICATION_DATE = conference_data['PUBLICATION_DATE']
CONFERENCE_DATES = conference_data['CONFERENCE_DATES']
CONFERENCE_TITLE = conference_data['CONFERENCE_TITLE']
CONFERENCE_ACRONYM = conference_data['CONFERENCE_ACRONYM']
CONFERENCE_URL = conference_data['CONFERENCE_URL']
ZENODO_COMMUNITY = conference_data['ZENODO_COMMUNITY']
CONFERENCE = Conference(
    PUBLICATION_DATE, CONFERENCE_DATES, CONFERENCE_TITLE, CONFERENCE_ACRONYM, CONFERENCE_URL,
    ZENODO_COMMUNITY
)

# Tokens, replace with public and sandbox tokens from Zenodo:
with open("secrets.toml", "rb") as f:
    secret_data = tomllib.load(f)


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
    return process_csv(
        csvfile,
        CONFERENCE,
        secret_data,
        upload_pdf=True,
        verbose=False,
        print_authors=False,
        production_zenodo=production
    )


def check(csvfile, authors):
    """Process metadata from a CSV file and print out to check it."""
    return process_csv(
        csvfile,
        CONFERENCE,
        secret_data,
        upload_pdf=False,
        verbose=not authors,
        print_authors=authors,
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
