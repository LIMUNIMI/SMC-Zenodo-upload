
# Zenodo-upload Quick Guide

The script reads a CSV file and a set of PDFs, creates the Zenodo entries, retrieves the DOIs, and writes them back to the CSV.

It works in two steps, so you can check the result before anything becomes public:

1. `upload` creates a draft on Zenodo for every paper and uploads its files;
2. `publish` publishes the drafts and retrieves the DOIs.

Both can target the sandbox (default) or the production server (`--production`).

To use this tool you need:
- A [Zenodo](https://zenodo.org) account and token
- A [Zenodo Sandbox](https://sandbox.zenodo.org) account and token (optional, but recommended)
- A CSV with the data of the conference papers
- All the PDFs cited by the CSV

For the full documentation see the [README](README.md).

## 0. Get the Zenodo tokens and set up the sandbox

Prepare the environment:
- Install the dependencies (Python 3.11 or newer, see [Install](README.md#install)): `pip install -r requirements.txt`
- Duplicate the [secrets.toml.example](secrets.toml.example) file and rename it `secrets.toml`

Get the production token:
- Log in to [Zenodo](https://zenodo.org)
- Click on your username -> [Applications](https://zenodo.org/account/settings/applications/)
- Under *Personal access tokens* click *New token* (check the scopes `deposit:write` and `deposit:actions`)
- Copy the generated token into `secrets.toml` (`PUBLIC_TOKEN`). Zenodo shows it only once

Get the sandbox token:
- Log in to the [Zenodo Sandbox](https://sandbox.zenodo.org) (it requires a separate account: the Zenodo credentials do not work there)
- Click on your username -> [Applications](https://sandbox.zenodo.org/account/settings/applications/)
- Under *Personal access tokens* click *New token* (check the scopes `deposit:write` and `deposit:actions`)
- Copy the generated token into `secrets.toml` (`SANDBOX_TOKEN`)

Never share `secrets.toml` and never commit it: it is already ignored by git.

Create a sandbox community:
- Create a [community](https://sandbox.zenodo.org/communities/) in the Zenodo Sandbox that will collect your test runs (or ask to become a member of the community, if it already exists)
- Take note of the community identifier of your choice: it goes into [conference.toml](conference.toml) (`ZENODO_COMMUNITY`). Ideally it should be the same as on the production server; otherwise remember to change it before going to production

## 1. Get the data (PDFs and CSV)

- Use your conference manager portal (e.g. EasyChair) to get an xlsx/csv file of the publications
- Also download the actual PDFs of the papers
- Edit the xlsx/csv to match the required columns (see [examples/proceedings_example.csv](examples/proceedings_example.csv)); the column names are not case-sensitive:
	- `key`: required, unique identifier of the paper (e.g. the bibtex key)
	- `pdf`: required, file name of the paper's PDF in the `upload` folder
	- `title`: required
	- `authors`: required, `Last, First; Last, First`
	- `affiliations`: optional, one per author, in the same order, separated by `;` (leave an author's slot empty if unknown)
	- `abstract`: optional
	- `pages`: optional
	- `note`: optional, the session of the paper
	
	Any other column is ignored. Special characters must be written as UTF-8 symbols, not as LaTeX code. If a paper has supplementary files, see [Additional files](README.md#additional-files).
- Save the data as a CSV file, and place it and the PDFs in the `upload` folder
- Open [conference.toml](conference.toml) and fill in all the fields (see [Conference Metadata](README.md#conference-metadata)). Ask the conference board if you are missing some information:
	- `PUBLICATION_DATE`, `CONFERENCE_DATES`, `CONFERENCE_PLACE`
	- `CONFERENCE_TITLE`, `CONFERENCE_ACRONYM`, `CONFERENCE_URL`
	- `PROCEEDINGS_TITLE`, `ISBN` (optional, can be added later by editing the published records), `ISSN` (optional), `PUBLISHER`
	- `LICENSE`, `ACCESS_RIGHT`, `ZENODO_COMMUNITY`

## 2. Run the script

For a detailed guide see the [README](README.md#run). The commands ask you to press Enter before they start.

- First, run a check to see if the CSV is OK:
```
python zenodo_upload check upload/proceedings.csv
```
and check how the author names have been processed:
```
python zenodo_upload check upload/proceedings.csv --authors
```

- When everything looks good, you can upload to the sandbox. Once it finishes, go to the [Zenodo Sandbox](https://sandbox.zenodo.org) portal to see if everything is in its right place
```
python zenodo_upload upload upload/proceedings.csv
```

- If you also want to test the publication, publish the drafts on the sandbox
```
python zenodo_upload publish upload/proceedings.csv
```
The progress of every paper (status, deposition id, DOI, errors) is written back to the CSV, so an interrupted run can simply be repeated. To repeat a sandbox test from scratch, start again from a fresh copy of the CSV.

- Now you can upload to production as a draft (remember to check the `conference.toml` metadata and the correct Zenodo community). The rows tested on the sandbox are restarted from scratch on the production server
```
python zenodo_upload upload upload/proceedings.csv --production
```

- Check the drafts on [Zenodo](https://zenodo.org) (your *Uploads* page). If some supplementary files were skipped because they are too big (see the `skipped_files` column), upload them manually to the draft now: files cannot be added after publication

- If everything looks OK, you can publish the drafts

 > [!WARNING]
 > This will create the entries on the Zenodo production server!
 > This is a permanent action and it cannot be undone!

```
python zenodo_upload publish upload/proceedings.csv --production
```

- Now the entries will be submitted for inclusion in the community set in `conference.toml`. If you are a community manager, you can go to Zenodo and manually accept the entries; otherwise a community manager will have to accept them.

The DOI of every paper is in the `doi` column of the CSV.
