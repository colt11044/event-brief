# Event Brief

Turn a structured research record into a source-linked meeting brief. Event Brief
checks that claims cite available sources, keeps unresolved identities visible,
and produces HTML, Markdown, or PDF without fetching remote resources.

## Try the fictional example

Python 3.11+ on macOS or Linux. HTML and Markdown need no runtime dependencies.
With [uv](https://docs.astral.sh/uv/):

```sh
uv sync --frozen
mkdir -p output
uv run event-brief validate examples/brief.json
uv run event-brief render examples/brief.json output/brief.html --format html
uv run event-brief render examples/brief.json output/brief.pdf --format pdf
```

Open `output/brief.html` locally. The example uses invented people and reserved
example URLs; no research or real identity verification occurred. Commands refuse
an existing output file. Choose a new name to make another export.

For installation without development tools, use `python -m pip install .` or
`python -m pip install '.[pdf]'`. The lockfile pins the development environment;
ordinary pip installation resolves the declared dependency ranges.

## What it does

- Validates the full roster, research attempts, identity states, citations, and
  portrait provenance before rendering.
- Keeps source dates, confidence, uncertainty, and coverage counts in the brief.
- Rejects substantive profile claims for unresolved identities.
- Emits self-contained HTML with no JavaScript, remote fonts, or automatic image
  requests. Source links are clickable and are accessed only if the reader opens them.
- Optionally embeds explicitly selected, hash-pinned local PNG/JPEG/WebP portraits.
- Produces PDFs directly from validated JSON, without interpreting supplied HTML.

The validator checks **structure and source references**, not whether a source is
true, whether identities match, or whether research is complete. A researcher
must review those judgments. It does not search people, run a model, fetch websites,
connect to calendars/CRM, or send a brief.

## Input and portraits

Start from [`examples/brief.json`](examples/brief.json). The schema identifier is
`event_brief.v1`; the original internal identifier is intentionally unsupported.
[`docs/input.md`](docs/input.md) explains fields and identity outcomes.

Portraits are omitted by default, even when an image URL appears in the research
record. To embed a portrait, add `local_asset` (one filename) and
`local_asset_sha256` to its verified portrait record, and pass
`--portrait-dir /explicit/directory`. The image is decoded and re-encoded, removing
its original metadata. A requested invalid portrait makes the CLI fail closed.

## Privacy and security

Inputs can contain personal data. Keep them outside this repository and review
every export before sharing. Exports include the selected names, claims, links,
notes and conversation hooks; they omit raw research attempts, arbitrary extra
input fields, local portrait filenames, and the full JSON payload. PDF metadata
contains the event title and a generic author. No telemetry is implemented.

Inputs are limited to 2 MiB. Input leaf symlinks/devices are rejected. New outputs
use owner-only permissions and never overwrite existing files. The CLI runs with
your filesystem permissions; it is not a sandbox against another process running
as your user. Explicit input/output directories must be trusted.

See [security and privacy boundaries](SECURITY.md) and [provenance](NOTICE.md).

## Development

```sh
uv sync --frozen
uv run python -m unittest discover -s tests -v
uv run bandit -r src -q
uv build
```

The CLI is in `src/event_brief/cli.py`, validation and HTML/Markdown rendering in
`core.py`, and bounded portrait loading/PDF rendering in `pdf.py`.
CI repeats tests on Linux with Python 3.11 and 3.14 when enabled; a committed
workflow is not evidence that hosted CI has run.

## Attribution and license

Colton Gingrass developed the original workflow and this portable successor with
AI assistance. It grew from private Hermes-era source-grounded briefing work;
it does not require Hermes or any particular model. MIT for this package's code;
bundled DejaVu fonts retain their separate license in `src/event_brief/assets/fonts/LICENSE`.
