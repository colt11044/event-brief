# Security and privacy

## Intended use and trust boundaries

This is an offline CLI for a trusted local operator. Research JSON, its strings,
and portrait bytes are untrusted input. The CLI does not browse, execute model
output, read credentials, or send data. Source links can lead elsewhere when a
reader deliberately clicks them. Use trusted input/output directories.

Validation checks citation references and identity-state consistency, not truth.
Instructions in source text are data. This tool does not make model calls and
cannot enforce how an external researcher or agent follows instructions.

HTML escapes text and attributes, omits the original JSON, and uses a restrictive
content policy. Markdown escapes markup in text. PDFs are constructed from the
validated model. Images must be explicitly supplied, regular local raster files
with matching hashes and bounded dimensions/size; they are re-encoded. No remote
image/resource fetch is part of rendering.

Input files are capped at 2 MiB. The tool is not a multitenant upload service or a
sandbox for hostile filesystem users. A caller who controls parent directories,
the Python environment, or installed packages is outside its security boundary.
Run untrusted bulk jobs with separate OS-level resource restrictions.

## Data handling

Input: research records and optional locally selected portraits. Output: an
explicitly requested brief. There is no server, telemetry, cloud storage, or
background processing. Local temporary PDF output is removed after rendering.
New CLI output files use mode 0600 and cannot overwrite existing files. Direct
Python rendering primitives require the caller to validate inputs and provide
equivalent safe output handling; they are not a separate security boundary.

Rendered names, claims, source URLs, identity notes and conversation hooks can
still be sensitive. No automated detector can certify publication consent.
Inspect all exports and remove data you lack permission to share. Delete your
inputs/exports using your normal local retention policy; the tool has no hidden
research database. A hash confirms bytes, not image rights or a person's identity.

## Reporting

Before public publication, report findings privately to the repository owner.
After publication, use GitHub private vulnerability reporting if enabled. Do not
post personal records or exploitable details in public issues. No security
response SLA is promised for this experimental release.
