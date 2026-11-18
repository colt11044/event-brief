# Provenance

Event Brief is a portable successor to Colton Gingrass's AI-assisted Hermes-era
briefing workflow. The release adapts the local validator and renderer, with a new
standalone CLI, offline export defaults, removal of hidden input payloads, generic
affiliation categories, packaging, and regression tests.

The original design drew on structured source inventories from a company
tear-sheet workflow and source-grounded meeting briefs from a private command
center. Those upstream plugins, private instructions and operational records are
not distributed here. This package does not require the retired Hermes runtime.

The earlier delivery-receipt helper is intentionally excluded: it depended on a
separate private handoff service. Successful export here means a local file was
written; it is never presented as proof of upload, sending or recipient acceptance.

Code: MIT, as provided in `LICENSE`. Fonts: DejaVu Sans regular and bold; retain
the full Bitstream Vera/DejaVu notice in `src/event_brief/assets/fonts/LICENSE`.
Pillow and ReportLab are installed dependencies, not copied source, and retain
their own licenses. Fixtures are fictional and contain no portraits of real people.
