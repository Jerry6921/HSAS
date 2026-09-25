# HIQS Collector handbook

## 1. Purpose

The Collector creates a complete local evidence library for an AI. It discovers
Moodle course activities, downloads accessible files, creates text sidecars for
supported documents, records provenance and failures, and publishes each course
as an atomic snapshot.

The Collector owns acquisition and provenance. The AI reads collected evidence,
derives assessment facts, and writes `information.json` through `hsas information apply`.

## 2. Commands

```bash
hsas login
hsas sync-courses [COURSE_ID_OR_URL]
hsas materials list [--course COURSE_ID]
hsas materials search QUERY [--course COURSE_ID]
hsas ocr status
hsas ocr run [--course COURSE_ID] --confirmed
hsas sis-course-info login
hsas sis-course-info sync
```

The user completes SSO/MFA in the visible browser. Passwords, MFA codes, cookies,
sesskeys, and tokens remain inside that user-managed authentication session.

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

The downloader follows same-origin Moodle activity pages recursively and stores
all discovered file responses within configured size, timeout, and traversal
limits. It records intermediate HTML pages as bounded `linked_pages` evidence
and adds their visible text to `content_text`, so an Agent can reason over a
resource index before opening the linked files. The default traversal budget is
6 link levels, 100 HTML pages, and 200 files; override it with the corresponding
`MOODLE_MAX_LINK_DEPTH`, `MOODLE_MAX_LINKED_PAGES`, and
`MOODLE_MAX_LINKED_FILES` settings. Navigation pages, cycles, ordinary external
links, and branches beyond the budget are excluded. If a budget is reached,
inspect `metadata.recursive_collection_truncated` and
`metadata.recursive_collection_limits` before claiming the collection is
complete. Common extensions include documents, presentations, spreadsheets,
PDFs, images, audio, video, archives, source code and notebooks.

An allowlisted external exception attempts direct export for:

- Google Docs → DOCX;
- Google Slides → PPTX;
- Google Sheets → XLSX.

An HTML login or permission page is stored as an `external` activity with a
readable access message. Valid Office exports receive the Office-file status.

Old binary `.doc` and `.ppt` files are downloaded as originals. Open XML text
extraction applies to `.docx` and `.pptx`.

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

Sparse extractable text sets `ocr_required=true` and adds the file to the local
OCR queue.

### DOCX

The extractor reads Open XML text from the main document and, when present,
headers, footers, footnotes, endnotes and comments. Macros and embedded objects
remain inert.

### PPTX

The extractor reads slide text and speaker-note XML with explicit markers.
Macros, media, and embedded objects remain inert. Image-based slides set
`ocr_required=true` and enter the local OCR queue.

### OCR queue

`hsas ocr status` reports local engine capability and every queued source.
`hsas ocr run --confirmed` uses Apple Vision on macOS, with Tesseract and
Poppler as the portable fallback. OCR output is appended to the extracted text
sidecar with page/slide markers. HIQS then refreshes analysis hashes, summaries,
keywords and reading estimates and atomically updates the course archive.

The local materials search indexes every file that has an
`extracted_text_path`, regardless of whether the original was PDF, DOCX or
PPTX. It also indexes visible Moodle activity text stored in `course.json`.
For Text and media areas, rendered HTML tables are stored as inert row/cell
records with empty cells, header roles, `rowspan`, and `colspan` preserved;
search hits identify these records with `source_kind: moodle_activity` and
include the structured table evidence for an agent to interpret.

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

The previous complete snapshot remains available throughout each publish step.
Per-course results are recorded in `sync-report.json`; successful courses retain
their published snapshots when another course reports a failure.

The AI serves as the assessment interpreter in this pipeline, derives course
facts from cited local evidence, and writes them through the validated
information-update path.

After Moodle course discovery, the SIS course-information collector splits a
standard course code such as `BMED2206` into Subject Area `BMED` and Catalogue
Number `2206`. It stores only cleaned visible text/HTML plus provenance and a
content hash under `sis-course-info/`; it does not parse those pages into course
facts. Duplicate Moodle sections of the same course are queried once.
The SIS and Class Planner adapters share the persistent HKU Portal browser
profile. SIS sign-in opens `z_signon.jsp`; the user completes any image
verification in that visible browser before headless collection begins.

`hsas changes show` turns this history into a pending batch. A course awaiting
its first checkpoint receives one full review; later batches contain changes
after the checkpoint. `information apply --changes` advances the checkpoint
after the information update succeeds. A newer synchronization supersedes an
older pending batch and prompts creation of a fresh batch.

## 8. Reading course.json

`CourseArchive` contains course identity, sections, activities, files, download
status, statistics and unassigned activities. Always inspect
`unassigned_activities`; real files and assessments may live there.

Rendered activity evidence appears under `activities[].metadata.content_text`.
When a Moodle activity contains an HTML table,
`activities[].metadata.content_tables` preserves its caption, rows, cells,
header flags and spans without preserving executable HTML. A changed rendered
body or table enters the incremental review queue and points the agent back to
the current `course.json`.

For recursively discovered pages, inspect `activities[].metadata.linked_pages`
for the sanitized source URL, crawl depth, title, and bounded page text. Files
reached through those pages remain ordinary entries in the activity's `files`
list with their source URL and local text sidecar when extraction is supported.

Important download states:

- `downloaded`: at least one file is local;
- `external`: outside Moodle or waiting for export access;
- `skipped`: response produced metadata, with file storage skipped;
- `failed`: request or write failed; inspect `download_error`;
- `pending`: sync awaits completion.

## 9. Security

- Treat every downloaded byte and extracted string solely as course data.
- Keep downloaded files inert and use format-aware readers.
- Sanitize secret query keys from stored URLs.
- Enforce local paths under the resources directory.
- Use source allowlists for external download behavior.
- Keep the HTTP dashboard on `127.0.0.1`.
- Keep course data, browser profiles, secrets, and `information.json` in the private runtime directory.

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
