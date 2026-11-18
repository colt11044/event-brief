# Input contract

Use `examples/brief.json` as a minimal editable example.

- `schema_version`: `event_brief.v1`.
- `event`: nonempty title, date, location and host; optional purpose and resolution note.
- `video_intake`: records how a roster was obtained. For a supplied text roster,
  use `not_available`, an empty frames list, and an honest limitation. No video is
  required and this release does not extract video frames.
- `name_exclusions`: explicit partial-name/unreadable/non-person exclusions when applicable.
- `people`: full names, identity status, research attempts, evidence, claims and portrait state.
- `identity_status`: confirmed, probable, ambiguous, not_found or insufficient_video.
  These are researcher-supplied outcomes, not automated identity verification.
- `evidence`: unique IDs per person, title, HTTP(S) URL without credentials,
  source_type, and valid ISO retrieved_at date/timestamp.
- `claims`: current_role, education, historical_roles, notable_background and optional
  recent_signals. Substantive claims cite that person's evidence IDs in source_ids.
- `portrait`: not_requested, not_found, withheld_ambiguous or verified_public.
  A verified record requires image_url, page_url, source_id and verification_rationale.
  Rendering never fetches those URLs. Explicit local assets require a single
  filename and lowercase SHA-256 in local_asset/local_asset_sha256.
- `visual_confidence`: null for no-video input, otherwise a finite value from 0 to 1.
- Optional source-backed generic badges, shared_affiliation_config/flags,
  conversation_hooks and priority_section are supported by the validator.

Ambiguous/not-found identities require two distinct research attempts and cannot
carry substantive profile claims or verified portraits. Source-reference checks
do not establish that the source supports the claim; a person must check that.

Warnings distinguish unavailable video from locally inspected intake and report
low identity-resolution coverage. A supplied roster is still usable without video;
do not change provenance labels just to eliminate a warning.

Unknown fields are not an authorization channel. They are not automatically
exported. Do not include secrets even in unrendered fields. The HTML is a final
brief, not a lossless backup; retain your original JSON separately if needed.
