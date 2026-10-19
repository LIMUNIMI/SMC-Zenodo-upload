# zenodo-upload

This Python project is for uploading conference proceedings to Zenodo
for archiving submissions and generating DOIs. Everything that depends
on the conference is configured in `conference.toml` (see [Conference
Metadata](#conference-metadata)).

> [!CAUTION]
> Uploading and publishing to Zenodo should only happen ONCE
> for each proceedings entry. You **must** test the script using
> Zenodo's sandbox multiple times and make super sure that your metadata
> records (CSV file) are absolutely correct before uploading to
> production Zenodo.

The python script reads a CSV file with one row per paper (made manually
or from the conference's `.bib` file, see [The CSV file](#the-csv-file)) 
and creates a deposition record on the [Zenodo website](https://zenodo.org),
added to the conference's Zenodo community 
(e.g. [SMC](https://zenodo.org/communities/smc/)).

The metadata from the CSV rows are tied to the article (.pdf file) and
uploaded to Zenodo as a draft (`upload`); the drafts are then published
(`publish`), which creates the DOIs.

> [!NOTE]
> The result of every paper (status, Zenodo deposition id, DOI, errors) is
> written back to the same CSV file, in extra columns, after each step: an
> interrupted or partly failed run can simply be repeated and resumes
> where it stopped (see [Status and resuming](#status-and-resuming)).

This project requires Python 3.11 or newer; dependencies are listed in
`requirements.txt`.

For the proceedings chair of the conference, your workflow should be:

1. (before the conference) make sure **all** camera-ready submissions
   for each track are correct and hassle authors to update if there are
   errors—do this before the conference and emphasise that submissions
   cannot be updated after the conference.
2. (after the conference) create an accurate spreadsheet for all
   submissions that should be in the proceedings for each track. Save it
   as a CSV file, one row per paper (see [The CSV file](#the-csv-file)).
   All fields must be filled in except for `doi`. If you keep the
   bibliography in a `.bib` file, you can instead convert it to CSV with
   `bibcsv/bibcsv.py bib2csv` (see [Converting between `.bib` and
   CSV](#converting-between-bib-and-csv)).
3. put the `.csv` file and pdf submission files into the `upload`
   directory of this project.
4. follow the "Install" and "Run" instructions below and test multiple
   times with the Zenodo sandbox to make sure that your metadata is
   correct and working.
5. upload to production Zenodo, check the drafts, then publish them. The
   CSV file itself will show the DOI of each paper (`doi` column,
   `status` `done`).

Then you can pass the CSV file to whoever maintains the conference
bibliography and website, who will:

6. take the `key` and `doi` columns of the CSV file (and, if useful,
   `title`) to get the file associating each bibtex item key with the
   DOI; `python bibcsv/bibcsv.py csv2bib` gives a `.bib` file with the
   DOIs filled in.
7. add the DOIs to the conference bibliography using the key/DOI pairs
   of step 6, and update the website.

## Install

You can install the project by running:

```bash
python -m venv .venv
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

## Zenodo access tokens

The program talks to Zenodo through personal access tokens (API keys).
The production server (<https://zenodo.org>) and the sandbox
(<https://sandbox.zenodo.org>) are separate sites with separate
accounts, so you need one token for each:

1. Register (or log in) on the site. For the production token, use the
   account that should own the records and that is allowed to add them
   to the conference's Zenodo community.
2. Open the user menu, then *Applications* (direct link:
   `/account/settings/applications/` on the same site), then *Personal
   access tokens*, then *New token*.
3. Give it any name and tick the scopes `deposit:write` and
   `deposit:actions` (the second one is needed to publish).
4. Create it and copy the token **immediately**: Zenodo shows it only
   once. If you lose it, delete it and create a new one.
5. Put the production token in `PUBLIC_TOKEN` and the sandbox one in
   `SANDBOX_TOKEN` of `secrets.toml` (see [Run](#run)). Never commit
   this file or share the tokens.

If an upload stops with `access check failed: HTTP 401` in the `error`
column, the token for that server is wrong, still the placeholder of
`secrets.toml.example`, revoked, or missing one of the two scopes.

The records are added to the community set in `ZENODO_COMMUNITY`
([Conference Metadata](#conference-metadata)). Communities are separate
on the sandbox: if the sandbox refuses the records because of the
community, create a community with the same identifier on
<https://sandbox.zenodo.org> and run again.

## Run

You can test run the program by running:

```bash
python zenodo_upload --help
```

To run the program you will need to:

- place all pdfs to be uploaded into the `upload` directory
- find your CSV file (e.g., `proceedings.csv`) with metadata for the
  PDFs
- place a file named `secrets.toml` in the same directory as this readme
  file. The `secrets.toml` file should have two records (you can copy,
  rename and edit the `secrets.toml.example` scaffold; see [Zenodo
  access tokens](#zenodo-access-tokens) to get the tokens):

  ```toml
  PUBLIC_TOKEN = 'replace-with-your-zenodo-public-token'
  SANDBOX_TOKEN = 'replace-with-your-zenodo-sandbox-token'
  ```

Once you have your data in place, you can view the metadata that will be
created (without uploading) by running:

```bash
python zenodo_upload check upload/proceedings.csv
```

It's a good idea to check the author names carefully as they may have
been processed incorrectly:

```bash
python zenodo_upload check upload/proceedings.csv --authors
```

Typically you would run the checks many times to make sure the metadata
is perfect.

When your metadata is ready you can try uploading to the sandbox server:

```bash
python zenodo_upload upload upload/proceedings.csv
```

`upload` creates a draft for every paper and uploads its files, but does
**not** publish it: the drafts can still be checked on Zenodo (and
supplementary files that were skipped can be added, see below). To
publish them and get the DOIs:

```bash
python zenodo_upload publish upload/proceedings.csv
```

By default, the program works on the Zenodo sandbox. When you are
**absolutely ready to commit to the production server** you can run:

```bash
python zenodo_upload upload upload/proceedings.csv --production
python zenodo_upload publish upload/proceedings.csv --production
```

to do your final uploads. Publishing is irreversible.

Rows that were already taken as far as the command goes on the chosen
server (`uploaded` for `upload`, `done` for `publish`) are skipped, so
the same command can be run again after an error. `publish` handles only
rows uploaded to the same server; the others are reported as not
completed. Run the sandbox and the production upload on the same file: the `server` column records which
server each row refers to, and rows recorded for the sandbox restart
from scratch on production.

Before the first change of a run the file is copied to
`<name>.csv.<yyyymmdd_hhmmss>.bak` (e.g. `proceedings.csv.20261016_143205.bak`),
so every run keeps its own backup.

### Status and resuming

The program adds these columns to the CSV file and updates the file
after every step (the file must not be open in Excel while the program
runs):

| Column | Content |
|---|---|
| `status` | last completed step: `pending` (or empty), `created`, `uploaded`, `published`, `done` |
| `server` | `sandbox` or `production` |
| `deposition_id` | Zenodo deposition id |
| `doi` | the DOI, once `status` is `done` (a DOI that comes from the `.bib` is replaced) |
| `skipped_files` | supplementary files that were not uploaded, separated by `;` (see below) |
| `error` | why the last attempt stopped, empty when the row advanced |
| `updated_at` | time of the last change |

On a new run each row continues from its last step: a `created` row
reuses its Zenodo draft and only uploads the missing files (`upload`
ends with `uploaded`); with `publish`, an `uploaded` row is published and
a `published` row only reads its DOI (`publish` ends with `done`). A
publish whose answer got lost is recognised and not repeated. At the end
the program prints a summary and exits with an error code if some rows
are not completed.

Two safeguards:

- a run for the **sandbox** refuses to start if the file has rows
  recorded for the **production** server (it would overwrite their
  deposition ids and DOIs); use a copy of the file for tests after the
  production upload;
- all the checks on the file and on the PDFs (existence, size) happen
  before the first upload; if one fails nothing is uploaded and the
  program exits with an error code.

## Tests

Tests use the standard `unittest` module and never contact Zenodo:

```bash
python -m unittest discover -s tests -t .
```

## Conference Metadata

The conference metadata is read from `conference.toml` in the same
directory as this readme file. Update its records as needed for your
edition:

```toml
PUBLICATION_DATE = 'YYYY-MM-DD'
CONFERENCE_DATES = 'D Month - D Month, YYYY'
CONFERENCE_TITLE = 'Sound and Music Computing Conference'
CONFERENCE_ACRONYM = 'SMC'
CONFERENCE_URL = 'https://smcnetwork.org/'
ZENODO_COMMUNITY = 'smc'
LICENSE = 'cc-by-4.0'
ACCESS_RIGHT = 'open'
PUBLISHER = 'SMC Network'
CONFERENCE_PLACE = 'City, Country'
PROCEEDINGS_TITLE = 'Proceedings of the Sound and Music Computing Conference 2026'
ISBN = 'XXX-X-XXXXX-XXX-X'
ISSN = ''
```

Every command (`check` included) first validates these values and stops
before doing anything if they are unusable: the placeholders shown above
(date, URL, place, ISBN) are rejected, `PUBLICATION_DATE` must be a real
`YYYY-MM-DD` date, `ISBN` must be a valid ISBN-10 or ISBN-13, `ISSN` (if
given) must look like `1234-5678`, and `ACCESS_RIGHT` must be one of
`open`, `embargoed`, `restricted`, `closed`.

`ZENODO_COMMUNITY` is the identifier of the Zenodo community the records
are added to, i.e. the last part of its URL
(`https://zenodo.org/communities/smc/`). `LICENSE` is the Zenodo licence
identifier and must match the licence printed on the paper template;
`ACCESS_RIGHT` is `open` for public records; `PUBLISHER` is shown as the
record's publisher. `CONFERENCE_PLACE`, `PROCEEDINGS_TITLE`, `ISBN` and
`ISSN` are the same for all papers, so they are not read from the CSV
file. All records are required except `ISSN`, which can be left empty (no
ISSN is sent then).

## Additional files

### Naming convention

If a resource contains supplementary files that should be uploaded
together with the paper, each supplementary file should have the same
base file name as the paper PDF with an additional suffix such as
`_file01`, `_file02`, etc., appended **before** the extension. For
example:

```text
paper_10.pdf
paper_10_file01.mp4
paper_10_file02.mov
```

The script automatically searches the `upload` directory for files that
share the base name plus an underscore, i.e. `paper_10_…`, and attempts
to upload those as supplementary files for the corresponding deposition.
Zenodo displays files alphabetically in its UI.

### Handling of large supplementary files (≥ 100 MB)

Zenodo (and/or the reverse proxy in front of it) imposes a maximum HTTP
request body size. In practice, uploads larger than about 100 MB to both
the sandbox and production endpoints result in an HTTP `413 Request
Entity Too Large` response from nginx **before** the request reaches the
Zenodo application.

To avoid failed uploads and crashes, this script handles large
supplementary files as follows:

- Before uploading a supplementary file, it checks its size on disk.
- If a supplementary file is **larger than 100 MB**:
  - The script **does not attempt to upload it**.
  - A warning is printed to the console indicating that the file was
    skipped and must be uploaded manually via the Zenodo web UI.
  - The filename is recorded in the `skipped_files` column of the row.

- If the script does attempt an upload (for files ≤ 100 MB) and Zenodo
  still returns an error (including HTTP `413`), the script:
  - Prints the HTTP status and error body (handling both JSON and HTML
    responses),
  - Marks that supplementary file as skipped,
  - Continues with the rest of the files and the deposition instead of
    aborting the whole run.

### Entries with skipped supplementary files

When any supplementary files are skipped for a given paper (either
because they are larger than 100 MB or because the server rejected
them), their names are listed in the `skipped_files` column of its row,
separated by `;`, e.g. `paper_14_file01.mp4;paper_14_file02.mov`. The
paper itself is uploaded as a draft.

To finish: filter the rows with a non-empty `skipped_files`, and upload
those files manually to the draft `deposition_id` via the Zenodo web UI
(on the server given by `server`) **before running `publish`**: files
cannot be added to a published record.

## The CSV file

One row per paper, UTF-8 (a BOM from Excel is accepted),
comma-separated, with a header row. Column names are case-insensitive.
[`examples/proceedings_example.csv`](examples/proceedings_example.csv) is
a working example (complete row, row with an unknown affiliation, minimal
row): copy it to `upload/` and adapt it, together with PDFs named as in
its `pdf` column.

| Column | |
|---|---|
| `key` | required, unique (the bibtex key) |
| `pdf` | required, file name of the paper in `upload/`; supplementary files are `<pdf name without .pdf>_*` |
| `title` | required |
| `authors` | required, `Last, First; Last, First` |
| `affiliations` | optional, one per author in the same order, separated by `;` (leave an author's slot empty if unknown) |
| `abstract` | optional, `---` if empty |
| `pages`, `note` (session) | optional |

The other columns `bibcsv` writes (`address`, `booktitle`, `isbn`, `issn`, ...)
are ignored: these values are the same for every paper and come from
`conference.toml`.

The state columns described in [Status and
resuming](#status-and-resuming) are added by the program. Any other
column (`track`, `year`, `url`, ...) is ignored by the upload and kept
in the file. The whole file is checked before anything is sent: missing
columns, empty required cells, duplicate keys, unknown `status`/`server`,
a started row (`status` other than `pending`) without `server` or
`deposition_id`, and affiliations that do not match the authors are
reported together and nothing is uploaded. Column names are written back in lower case.

Special characters must be written with UTF-8 symbols and **not** in
LaTeX code, as in the bibliography repo.

### Converting between `.bib` and CSV

`bibcsv/bibcsv.py` is a standalone tool (its own
`bibcsv/requirements.txt`, which includes `pybtex`) that converts the
`.bib` file to the CSV above and back:

```bash
pip install -r bibcsv/requirements.txt
python bibcsv/bibcsv.py bib2csv proceedings.bib upload/proceedings.csv
python bibcsv/bibcsv.py csv2bib upload/proceedings.csv proceedings.bib
```

- `key`, `pdf` (last segment of `url`) and `authors` (`Last, First;
  Last, First`) come first; every other `.bib` field is kept as a
  lower-case column (`track`, `note`, ...), followed by the state
  columns (empty, except `doi` when the `.bib` has one).
- `csv2bib` leaves the state columns out of the `.bib`, except `doi`.
- Entries with unreadable author names are reported by key and nothing
  is written; `--skip-invalid` converts the readable entries anyway.
  `editor` is copied as it is.
- Empty fields are not written back to the `.bib`.

Tests: `python -m unittest discover -s bibcsv/tests`.

## Acknowledgements

- Thanks to [Benedikte
  Wallace](https://www.linkedin.com/in/benedikte-wallace-8b489782/) for
  developing the Zenodo upload script in 2017–2018 or so.
- Charles Martin did some work on this in 2024.
- Stefano Fasciani did some work on this in 2025 and 2026.
- Giorgio Presti refactored the script and made it conference-agnostic
  in 2026 (originally written for NIME).

## Differences from the NIME script

- Conference-agnostic: everything that depends on the edition lives in
  `conference.toml` (including licence, publisher, place, proceedings
  title and ISBN/ISSN, which are not repeated in every CSV row), nothing
  NIME-specific is left in the code, and placeholder values are rejected
  before anything is done.
- The input is a CSV file with one row per paper instead of the `.bib`
  file; `bibcsv/bibcsv.py` converts between the two.
- Progress is written back to the CSV (status, server, deposition id,
  DOI, errors), so interrupted runs resume and `nime_dois.txt` is gone.
- Uploading and publishing are two commands: `upload` leaves drafts that
  can be checked, `publish` makes them public and gets the DOIs.
- Fewer dependencies (no `click`, no `poetry`), code split into small
  modules, checks on the CSV and the PDFs before any upload, and a test
  suite that never contacts Zenodo.
