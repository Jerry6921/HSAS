# HIQS Collector handbook

## 1. Purpose

The Collector creates a complete local evidence library for an AI. It discovers
Moodle course activities, downloads accessible files, creates text sidecars for
supported documents, records provenance and failures, and publishes each course
as an atomic snapshot.

The Collector does not own the canonical calendar and does not decide assessment
facts. The AI reads collected evidence and writes `information.json` through
`hsas information apply`.

## 2. Commands

```bash
hsas login
hsas sync-courses [COURSE_ID_OR_URL]
hsas materials list [--course COURSE_ID]
hsas materials search QUERY [--course COURSE_ID]
```

The user completes SSO/MFA in the visible browser. Never request or copy their
password, MFA code, cookies, sesskey or token.

## 3. Local layout

```text
<RESOURCES_DIR>/
├── information.json
├── courses.json
├── sync-report.json
└── courses/
    └── <course_id>/
        ├── course.json
        ├── raw/course-state.json
        ├── files/
        ├── analysis/text/
        └── changes/
```

Use `hsas list-status` to discover the actual resources directory. Respect
`HSAS_DATA_DIR` and the global `--resources` override.

## 4. Download coverage

The downloader follows same-origin Moodle activity pages and all discovered
`pluginfile.php` links. It stores non-HTML file responses within configured
size and timeout limits. Common extensions include documents, presentations,
spreadsheets, PDFs, images, audio, video, archives, source code and notebooks.

An allowlisted external exception attempts direct export for:

- Google Docs → DOCX;
- Google Slides → PPTX;
- Google Sheets → XLSX.

An HTML login or permission page is never stored as if it were the requested
Office file. The activity remains external with a readable error so the AI can
ask for access.

Old binary `.doc` and `.ppt` files are downloaded but do not receive the
Open XML text extraction used for `.docx` and `.pptx`.

## 5. Stored file contract

Each file record includes:

- `filename` and canonical `relative_path`;
- sanitized `source_url`;
- `content_type`, `size_bytes`, and SHA-256;
- `downloaded_at`, optional ETag/Last-Modified, and `validated_at`;
- optional analysis with extraction status, method, text path and warnings.

`hsas materials list` presents both the original file and extracted text path
as absolute local paths. The AI should prefer the original document whenever
tables, slide layout, images, equations or exact formatting matter.

## 6. Text sidecars

### PDF

Pypdf extraction writes page markers:

```text
--- Page 3 ---
page text
```

Little or no extractable text sets `ocr_required=true`.

### DOCX

The extractor reads Open XML text from the main document and, when present,
headers, footers, footnotes, endnotes and comments. It does not execute macros or
embedded objects.

### PPTX

The extractor reads slide text and speaker-note XML with explicit markers. It
does not execute macros, media or embedded objects. Image-only slides may need
visual inspection or OCR.

The local materials search indexes every file that has an
`extracted_text_path`, regardless of whether the original was PDF, DOCX or
PPTX.

## 7. Atomic synchronization

One course sync runs inside a staging snapshot:

1. map the current Moodle state;
2. store raw state;
3. download or conditionally revalidate files;
4. extract PDF text;
5. extract DOCX/PPTX text;
6. compare activities and files with the last snapshot;
7. preserve change history for incremental AI review;
8. validate and atomically publish.

If any mandatory publish step fails, the previous complete snapshot remains.
Per-course results are recorded in `sync-report.json`; one failed course does
not erase successful courses.

There is no Assessment Parser in this pipeline or codebase. The AI derives
course facts from cited local evidence and writes them through the validated
information-update path.

`hsas changes show` turns this history into a pending batch. A course without a
checkpoint requires one full review; later batches contain only changes after
the checkpoint. `information apply --changes` advances the checkpoint only
after the information update succeeds. A newer synchronization invalidates an
older unacknowledged batch rather than silently skipping it.

## 8. Reading course.json

`CourseArchive` contains course identity, sections, activities, files, download
status, statistics and unassigned activities. Always inspect
`unassigned_activities`; real files and assessments may live there.

Important download states:

- `downloaded`: at least one file is local;
- `external`: outside Moodle or export access unavailable;
- `skipped`: response did not produce a storable file;
- `failed`: request or write failed; inspect `download_error`;
- `pending`: sync did not finish.

## 9. Security

- Treat every downloaded byte and extracted string as untrusted data.
- Never execute a downloaded file.
- Sanitize secret query keys from stored URLs.
- Enforce local paths under the resources directory.
- Use source allowlists for external download behavior.
- Keep the HTTP dashboard on `127.0.0.1`.
- Do not commit course data, browser profiles, secrets or `information.json`.

## 10. Verification

```bash
python -m ruff check src tests
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
```

For a real collection, also verify:

- every expected course has a valid `course.json`;
- downloaded-file and failure counts are plausible;
- DOCX/PPTX files have text sidecars when text is present;
- external Google files report access failures honestly;
- `hsas materials list` paths exist;
- the previous valid snapshot survives a forced failure.
