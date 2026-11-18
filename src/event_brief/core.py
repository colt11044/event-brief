#!/usr/bin/env python3
"""Validation and rendering primitives for the Event Brief."""

from __future__ import annotations

import html
import re
import unicodedata
from collections import Counter
from typing import Any


FULL_NAME = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]*(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]*)+$")
STATUSES = {"confirmed", "probable", "ambiguous", "not_found", "insufficient_video"}
EXCLUSIONS = {"first_name_only", "unreadable", "non_person"}
BADGES = {"alumnus", "student", "veteran", "ai", "deep_tech"}


def badge_label(value: str) -> str:
    return value.replace("_", " ").title()


def text(value: Any) -> str:
    return str(value or "").replace("\n", " ").strip()


def key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", text(value))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", normalized).casefold()


def full_name(value: str) -> bool:
    return bool(FULL_NAME.fullmatch(text(value)))


def frame_candidates(data: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for frame in data.get("video_intake", {}).get("frames", []):
        if not isinstance(frame, dict):
            continue
        for candidate in frame.get("candidates", []):
            if isinstance(candidate, dict):
                result.append({**candidate, "timestamp_seconds": frame.get("timestamp_seconds")})
    return result


def evidence_ids(person: dict[str, Any]) -> set[str]:
    return {
        text(source.get("id"))
        for source in person.get("evidence", [])
        if isinstance(source, dict) and text(source.get("id"))
    }


def claim_source_ids(claim: Any) -> list[str]:
    if not isinstance(claim, dict):
        return []
    return [text(item) for item in claim.get("source_ids", []) if text(item)]


def substantive(claim: Any) -> bool:
    return isinstance(claim, dict) and any(
        text(claim.get(field))
        for field in ("title", "organization", "role", "detail", "school", "degree")
    )


def portrait_is_substantive(portrait: Any) -> bool:
    return isinstance(portrait, dict) and text(portrait.get("state")) == "verified_public"


def person_lookup_keys(person: dict[str, Any]) -> set[str]:
    values = [person.get("name"), *(person.get("transcription_aliases") or [])]
    return {key(text(value)) for value in values if full_name(text(value))}


def coverage_report(data: dict[str, Any]) -> dict[str, Any]:
    people = [person for person in data.get("people", []) if isinstance(person, dict)]
    candidates = frame_candidates(data)
    raw_full = [
        item for item in candidates
        if item.get("kind") == "full_name" and full_name(text(item.get("name")))
    ]
    appearances = Counter(key(text(item.get("name"))) for item in raw_full)
    statuses = Counter(text(person.get("identity_status")) for person in people)
    return {
        "full_name_roster": len(people),
        "raw_full_name_appearances": len(raw_full),
        "research_records": sum(bool(person.get("research_attempts")) for person in people),
        "confirmed_or_probable": sum(
            text(person.get("identity_status")) in {"confirmed", "probable"}
            for person in people
        ),
        "verified_portraits": sum(
            text((person.get("portrait") or {}).get("state")) == "verified_public"
            for person in people
        ),
        "status_counts": dict(sorted(statuses.items())),
        "duplicate_raw_appearances": {
            name: count for name, count in sorted(appearances.items()) if count > 1
        },
    }


def _finite_number(value: Any) -> bool:
    import math
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _public_url(value: Any) -> bool:
    from urllib.parse import urlsplit
    if not _nonempty_string(value) or any(ch.isspace() or ord(ch) < 32 for ch in value):
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port  # Force validation of malformed/out-of-range ports.
        return parsed.scheme.lower() in {"https", "http"} and bool(parsed.hostname) and parsed.username is None and parsed.password is None
    except (ValueError, TypeError):
        return False


def _retrieval_date(value: Any) -> bool:
    from datetime import date, datetime
    if not isinstance(value, str):
        return False
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            date.fromisoformat(value)
            return True
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", value):
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
    except ValueError:
        pass
    return False


def validate(data: dict[str, Any]) -> tuple[list[str], list[str], dict[str, Any]]:
    """Validate JSON types before using values, and fail closed before rendering."""
    errors: list[str] = []
    warnings: list[str] = []
    empty_report = {"full_name_roster": 0, "raw_full_name_appearances": 0, "research_records": 0,
                    "confirmed_or_probable": 0, "verified_portraits": 0,
                    "status_counts": {}, "duplicate_raw_appearances": {}}
    if not isinstance(data, dict):
        return ["top-level JSON must be an object"], [], empty_report
    if data.get("schema_version") != "event_brief.v1":
        errors.append("schema_version must be event_brief.v1")

    event = data.get("event")
    if not isinstance(event, dict):
        errors.append("event must be an object")
    else:
        for field in ("title", "date", "location", "host"):
            if not _nonempty_string(event.get(field)):
                errors.append("event needs non-empty string " + field)

    intake = data.get("video_intake")
    if not isinstance(intake, dict):
        errors.append("video_intake must be an object")
        intake = {}
    intake_state = text(intake.get("validation_state"))
    if intake_state not in {"locally_inspected", "reviewed_manifest", "frame_manifest_generated", "not_available"}:
        errors.append("video_intake.validation_state is invalid")
    frames = intake.get("frames")
    if not isinstance(frames, list):
        errors.append("video_intake.frames must be a list")
        frames = []
    if intake_state == "not_available":
        if not _nonempty_string(intake.get("limitation")):
            errors.append("not_available video intake needs a limitation")
    elif not frames:
        errors.append("available video intake needs frame records")
    duration = intake.get("duration_seconds")
    if duration is not None and (not _finite_number(duration) or duration < 0):
        errors.append("duration_seconds must be a non-negative finite number when supplied")
        duration = None
    interval = intake.get("frame_interval_seconds")
    if interval is not None and (not _finite_number(interval) or interval <= 0):
        errors.append("frame_interval_seconds must be a positive finite number when supplied")
    timestamps: list[float] = []
    candidates: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, dict):
            errors.append("each frame must be an object")
            continue
        timestamp = frame.get("timestamp_seconds")
        if not _finite_number(timestamp) or timestamp < 0:
            errors.append("every frame needs a non-negative finite numeric timestamp_seconds")
        else:
            timestamps.append(timestamp)
        observed = frame.get("candidates")
        if not isinstance(observed, list):
            errors.append("each frame needs a candidates list")
            continue
        for candidate in observed:
            if not isinstance(candidate, dict):
                errors.append("each frame candidate must be an object")
                continue
            candidates.append(candidate)
            if not _nonempty_string(candidate.get("name")):
                errors.append("each frame candidate needs a non-empty string name")
            kind = candidate.get("kind")
            if not isinstance(kind, str) or kind not in {"full_name", "first_name_only", "unreadable", "non_person"}:
                errors.append("frame candidate kind is invalid")
            elif kind == "full_name" and not full_name(text(candidate.get("name"))):
                errors.append("full_name candidate must contain a full name")
            confidence = candidate.get("confidence")
            if not _finite_number(confidence) or not 0 <= confidence <= 1:
                errors.append("frame candidate confidence must be a finite number from 0 to 1")
    if intake_state != "not_available" and _finite_number(duration) and duration > 2 and timestamps:
        if min(timestamps) > 1.5 or max(timestamps) < duration - 1.5:
            errors.append("frame coverage must include start and end of video")
        if not any(abs(item - duration / 2) <= max(1.5, duration * 0.1) for item in timestamps):
            errors.append("frame coverage must include middle of video")

    exclusions = data.get("name_exclusions")
    if not isinstance(exclusions, list):
        errors.append("name_exclusions must be a list")
        exclusions = []
    exclusion_keys: dict[str, set[str]] = {}
    for item in exclusions:
        if not isinstance(item, dict) or not _nonempty_string(item.get("value")):
            errors.append("each name exclusion needs a non-empty string value")
            continue
        reason = item.get("reason")
        if not isinstance(reason, str) or reason not in EXCLUSIONS:
            errors.append("name exclusion has invalid reason")
            continue
        exclusion_keys.setdefault(key(item["value"]), set()).add(reason)

    people = data.get("people")
    if not isinstance(people, list) or not people:
        errors.append("people must be a non-empty list")
        people = []
    shared_config = data.get("shared_affiliation_config", [])
    if not isinstance(shared_config, list):
        errors.append("shared_affiliation_config must be a list")
        shared_config = []
    shared_ids: dict[str, dict[str, Any]] = {}
    for item in shared_config:
        if not isinstance(item, dict) or any(not _nonempty_string(item.get(field)) for field in ("id", "label", "relationship_type")):
            errors.append("shared affiliation config needs string id, label, relationship_type")
            continue
        shared_id = item["id"].strip()
        if shared_id in shared_ids:
            errors.append("shared affiliation config IDs must be unique")
        shared_ids[shared_id] = item

    def sources_for(claim: dict[str, Any], ids: set[str], label: str, required: bool = True) -> None:
        cited = claim.get("source_ids", [])
        if not isinstance(cited, list) or any(not _nonempty_string(source_id) for source_id in cited):
            errors.append(label + " source_ids must be a list of non-empty string IDs")
            return
        if required and not cited:
            errors.append(label + " requires a person-level source")
        for source_id in cited:
            if source_id.strip() not in ids:
                errors.append(label + " cites missing source " + source_id)

    roster: dict[str, str] = {}
    lookup_keys: set[str] = set()
    safe_people: list[dict[str, Any]] = []
    for index, person in enumerate(people, start=1):
        label = "person " + str(index)
        if not isinstance(person, dict):
            errors.append(label + " must be an object")
            continue
        # These normalized containers are used only for safe coverage reporting.
        safe_people.append({**person, "portrait": person.get("portrait") if isinstance(person.get("portrait"), dict) else {},
                            "research_attempts": person.get("research_attempts") if isinstance(person.get("research_attempts"), list) else []})
        name = person.get("name")
        if not _nonempty_string(name) or not full_name(name):
            errors.append(label + " must have a full name; fragments belong in name_exclusions")
        else:
            name_id = key(name)
            if name_id in roster:
                errors.append("duplicate roster person: " + name + " duplicates " + roster[name_id])
            roster[name_id] = name
            lookup_keys.add(name_id)
            if name_id in exclusion_keys:
                errors.append(label + " is both a roster person and an exclusion")
        aliases = person.get("transcription_aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not full_name(alias) for alias in aliases):
            errors.append(label + " transcription_aliases must be a list of full names")
        else:
            lookup_keys.update(key(alias) for alias in aliases)
        confidence = person.get("visual_confidence")
        if not ("visual_confidence" in person and confidence is None and intake_state == "not_available") and (not _finite_number(confidence) or not 0 <= confidence <= 1):
            errors.append(label + " needs finite visual_confidence from 0 to 1, or null only when video is not_available")
        status = person.get("identity_status")
        if not isinstance(status, str) or status not in STATUSES:
            errors.append(label + " has invalid identity_status")
            status = ""
        attempts = person.get("research_attempts")
        if not isinstance(attempts, list) or not attempts:
            errors.append(label + " needs at least one research attempt")
            attempts = []
        distinct_attempts = set()
        for attempt in attempts:
            if not isinstance(attempt, dict) or not _nonempty_string(attempt.get("route")) or not _nonempty_string(attempt.get("query_or_note")):
                errors.append(label + " has an incomplete research attempt")
            else:
                distinct_attempts.add((key(attempt["route"]), key(attempt["query_or_note"])))
        if status in {"ambiguous", "not_found"} and len(distinct_attempts) < 2:
            errors.append(label + " needs two research attempts with distinct routes or notes for " + status)

        evidence = person.get("evidence")
        if not isinstance(evidence, list):
            errors.append(label + " evidence must be a list")
            evidence = []
        ids: set[str] = set()
        for source in evidence:
            if not isinstance(source, dict):
                errors.append(label + " each evidence entry must be an object")
                continue
            if any(not _nonempty_string(source.get(field)) for field in ("id", "title", "url", "source_type", "retrieved_at")):
                errors.append(label + " evidence needs non-empty string id, title, url, source_type, retrieved_at")
            if _nonempty_string(source.get("id")):
                source_id = source["id"].strip()
                if source_id in ids:
                    errors.append(label + " evidence IDs must be unique and non-empty")
                ids.add(source_id)
            if not _public_url(source.get("url")):
                errors.append(label + " evidence url must be an absolute HTTP(S) URL without credentials")
            if not _retrieval_date(source.get("retrieved_at")):
                errors.append(label + " evidence retrieved_at must be a valid ISO date or timestamp")

        claims = person.get("claims")
        if not isinstance(claims, dict):
            errors.append(label + " claims must be an object")
            claims = {}
        all_claims: list[dict[str, Any]] = []
        for field in ("current_role", "education"):
            claim = claims.get(field)
            if claim is not None and not isinstance(claim, dict):
                errors.append(label + " " + field + " must be an object or null")
            elif isinstance(claim, dict):
                all_claims.append(claim)
        for field in ("historical_roles", "notable_background", "recent_signals"):
            items = claims.get(field, [])
            if not isinstance(items, list):
                errors.append(label + " " + field + " must be a list")
                continue
            for claim in items:
                if not isinstance(claim, dict):
                    errors.append(label + " " + field + " entries must be objects")
                else:
                    all_claims.append(claim)
        for claim in all_claims:
            for field in ("title", "organization", "role", "detail", "school", "degree"):
                if field in claim and claim[field] is not None and not isinstance(claim[field], str):
                    errors.append(label + " claim " + field + " must be a string")
            sources_for(claim, ids, label + " claim", required=substantive(claim))

        signals = claims.get("recent_signals", [])
        if isinstance(signals, list):
            for signal in signals:
                if not isinstance(signal, dict):
                    continue
                if not _nonempty_string(signal.get("detail")):
                    errors.append(label + " recent signal requires detail")
                for field, allowed in {
                    "signal_type": {"person", "company", "public_interest", "affiliation"},
                    "evidence_type": {"official", "self_report", "independent_report", "inference"},
                    "confidence": {"high", "medium", "low"},
                }.items():
                    if not isinstance(signal.get(field), str) or signal[field] not in allowed:
                        errors.append(label + " recent signal has invalid " + field)
                if signal.get("activity_date") != "undated" and not _retrieval_date(signal.get("activity_date")):
                    errors.append(label + " recent signal requires ISO activity_date or undated")
        if "research_method_note" in person and not _nonempty_string(person["research_method_note"]):
            errors.append(label + " research_method_note must be a non-empty string")

        badges = person.get("badges", [])
        if not isinstance(badges, list):
            errors.append(label + " badges must be a list")
            badges = []
        for badge in badges:
            if not isinstance(badge, dict) or not isinstance(badge.get("type"), str) or badge["type"] not in BADGES:
                errors.append(label + " has invalid badge")
                continue
            sources_for(badge, ids, label + " badge " + badge["type"])

        relationships = person.get("relationship_flags", [])
        if not isinstance(relationships, list) or relationships:
            errors.append(label + " relationship_flags must remain an empty list until a relationship source standard is defined")
        shared_flags = person.get("shared_affiliation_flags", [])
        if not isinstance(shared_flags, list):
            errors.append(label + " shared_affiliation_flags must be a list")
            shared_flags = []
        for flag in shared_flags:
            if not isinstance(flag, dict) or not isinstance(flag.get("config_id"), str) or flag["config_id"] not in shared_ids:
                errors.append(label + " shared flag has unknown config_id")
                continue
            config = shared_ids[flag["config_id"]]
            if flag.get("relationship_type") != config.get("relationship_type"):
                errors.append(label + " shared flag relationship_type does not match config")
            sources_for(flag, ids, label + " shared flag")
            if config.get("requires_time_or_current_status") and not (
                _nonempty_string(flag.get("timeframe")) or _nonempty_string(flag.get("current_status"))
            ):
                errors.append(label + " shared flag needs timeframe or current_status")

        portrait = person.get("portrait")
        if not isinstance(portrait, dict) or not isinstance(portrait.get("state"), str) or portrait["state"] not in {
            "verified_public", "not_found", "withheld_ambiguous", "not_requested"
        }:
            errors.append(label + " needs a valid portrait state")
            portrait = {}
        if 'local_asset' in portrait or 'local_asset_sha256' in portrait:
            asset = portrait.get('local_asset')
            digest = portrait.get('local_asset_sha256')
            if not isinstance(asset, str) or not asset or asset in {'.', '..'} or '/' in asset or '\\' in asset or ':' in asset or any(ord(ch) < 32 for ch in asset):
                errors.append(label + ' local portrait asset must be a single filename')
            if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                errors.append(label + ' local portrait asset requires lowercase SHA-256')
            if not portrait_is_substantive(portrait):
                errors.append(label + ' local portrait asset requires verified_public portrait')
        if portrait_is_substantive(portrait):
            for field in ("image_url", "page_url", "source_id", "verification_rationale"):
                if not _nonempty_string(portrait.get(field)):
                    errors.append(label + " verified portrait missing " + field)
            for field in ("image_url", "page_url"):
                if not _public_url(portrait.get(field)):
                    errors.append(label + " portrait " + field + " must be an absolute HTTP(S) URL without credentials")
            if not isinstance(portrait.get("source_id"), str) or portrait["source_id"].strip() not in ids:
                errors.append(label + " portrait cites missing source")
            if status not in {"confirmed", "probable"}:
                errors.append(label + " cannot show verified portrait while identity is " + status)
        if status in {"ambiguous", "not_found", "insufficient_video"}:
            if any(substantive(claim) for claim in all_claims) or badges or shared_flags or portrait_is_substantive(portrait):
                errors.append(label + " cannot carry substantive profile claims or affiliation flags while identity is " + status)
        hooks = person.get("conversation_hooks", [])
        if not isinstance(hooks, list) or any(not _nonempty_string(hook) for hook in hooks):
            errors.append(label + " conversation_hooks must be a list of non-empty strings")

    priority_entries = data.get("priority_section", [])
    if not isinstance(priority_entries, list):
        errors.append("priority_section must be a list of name/reason objects")
        priority_entries = []
    roster_people = {key(person["name"]): person for person in safe_people
                     if isinstance(person.get("name"), str) and full_name(person["name"])}
    priority_names: set[str] = set()
    for entry in priority_entries:
        if not isinstance(entry, dict) or not _nonempty_string(entry.get("name")) or not _nonempty_string(entry.get("reason")):
            errors.append("each priority_section entry needs non-empty string name and reason")
            continue
        if set(entry) - {"name", "reason", "source_ids"}:
            errors.append("priority_section entries may contain only name, reason, and optional source_ids")
        name_id = key(entry["name"])
        if name_id not in roster_people:
            errors.append("priority_section name must be a roster attendee: " + entry["name"])
            continue
        if name_id in priority_names:
            errors.append("duplicate priority_section attendee: " + entry["name"])
        priority_names.add(name_id)
        person = roster_people[name_id]
        if not isinstance(person.get("identity_status"), str) or person["identity_status"] not in {"confirmed", "probable"}:
            errors.append("priority_section cannot publish profile-based reasons for an unresolved identity: " + entry["name"])
        if "source_ids" in entry:
            evidence = person.get("evidence", [])
            ids = {source["id"].strip() for source in evidence
                   if isinstance(source, dict) and _nonempty_string(source.get("id"))} if isinstance(evidence, list) else set()
            sources_for(entry, ids, "priority_section reason")

    raw_full = {key(candidate["name"]) for candidate in candidates
                if candidate.get("kind") == "full_name" and isinstance(candidate.get("name"), str) and full_name(candidate["name"])}
    for raw_name in raw_full:
        if raw_name not in lookup_keys:
            errors.append("raw full-name observation is missing from roster: " + raw_name)
    for candidate in candidates:
        kind = candidate.get("kind")
        if isinstance(kind, str) and kind in {"first_name_only", "unreadable"}:
            candidate_name = text(candidate.get("name"))
            if kind not in exclusion_keys.get(key(candidate_name), set()):
                errors.append(("first-name-only" if kind == "first_name_only" else kind) + " observation needs an explicit matching exclusion: " + candidate_name)
    regressions = data.get("expected_regressions", [])
    if not isinstance(regressions, list):
        errors.append("expected_regressions must be a list")
        regressions = []
    for regression in regressions:
        if not isinstance(regression, dict) or not isinstance(regression.get("name"), str) or not full_name(regression["name"]):
            errors.append("expected_regressions entries need a full name")
            continue
        regression_key = key(regression["name"])
        if regression_key not in roster:
            errors.append("regression attendee missing from roster: " + regression["name"])
        if regression_key not in raw_full:
            errors.append("regression attendee missing from raw frame observations: " + regression["name"])

    report = coverage_report({"people": safe_people, "video_intake": {"frames": [
        {"timestamp_seconds": 0, "candidates": candidates}
    ]}})
    if report["research_records"] != report["full_name_roster"]:
        errors.append("research record count does not reconcile to full roster")
    if report["full_name_roster"] and report["confirmed_or_probable"] / report["full_name_roster"] < 0.8:
        warnings.append("confirmed-or-probable resolution is below the 80% coverage target")
    if intake_state != "locally_inspected":
        warnings.append("video was not locally pixel-validated in this run")
    return errors, warnings, report


def visual_confidence_display(person: dict[str, Any]) -> str:
    value = person.get("visual_confidence")
    return "N/A (no video)" if value is None else format(float(value), ".0%")


def signal_display(signal: dict[str, Any]) -> dict[str, Any]:
    """Keep signal evidence labels visible across all renderers."""
    labels = " | ".join(text(signal.get(field)).replace("_", " ") for field in
                        ("signal_type", "activity_date", "evidence_type", "confidence"))
    return {**signal, "detail": labels + " confidence: " + text(signal.get("detail"))}


def markdown_text(value: Any) -> str:
    value = html.escape(text(value), quote=True)
    return re.sub(r"([\\`*_[\]{}()#+.!|>~-])", r"\\\1", value)


def markdown_url(value: Any) -> str:
    from urllib.parse import quote
    return quote(text(value), safe=":/?&=%#@+;,")


def source_links(person: dict[str, Any]) -> str:
    links = []
    for source in person.get("evidence", []):
        if isinstance(source, dict):
            links.append(
                "[" + markdown_text(source.get("id")) + "](" + markdown_url(source.get("url")) + ") "
                + markdown_text(source.get("title")) + " (retrieved " + markdown_text(source.get("retrieved_at")) + ")"
            )
    return "; ".join(links)


def render_markdown(data: dict[str, Any]) -> str:
    event = data["event"]
    report = coverage_report(data)
    lines = [
        "# " + markdown_text(event["title"]) + " - Event Brief",
        "",
        "**When/where:** " + markdown_text(event["date"]) + " - " + markdown_text(event["location"]),
        "**Host:** " + markdown_text(event["host"]),
        "**Video intake:** " + markdown_text(data["video_intake"].get("validation_state")),
        "",
        "## Coverage",
        "- Full-name roster: " + str(report["full_name_roster"]),
        "- Research records: " + str(report["research_records"]),
        "- Confirmed or probable identities: " + str(report["confirmed_or_probable"]),
        "- Verified public portraits: " + str(report["verified_portraits"]),
        "",
        "## People",
    ]
    for person in data["people"]:
        claims = person.get("claims") or {}
        current = claims.get("current_role") or {}
        role = ", ".join(filter(None, [markdown_text(current.get("title")), markdown_text(current.get("organization"))]))
        lines.extend([
            "### " + markdown_text(person["name"]),
            "**Identity:** " + markdown_text(person["identity_status"]) + " | video confidence " + visual_confidence_display(person),
            "**Current role:** " + (role or "Not sourced"),
            "**Portrait:** " + markdown_text((person.get("portrait") or {}).get("state")).replace("_", " "),
        ])
        education = claims.get("education") or {}
        if substantive(education):
            lines.append("**Education:** " + markdown_text(education.get("detail") or education.get("school")))
        historical = claims.get("historical_roles") or []
        if historical:
            lines.append("**Historical career:** " + "; ".join(markdown_text(item.get("detail") or item.get("role")) for item in historical))
        background = claims.get("notable_background") or []
        if background:
            lines.append("**Professional background:** " + "; ".join(markdown_text(item.get("detail")) for item in background))
        badges = person.get("badges") or []
        if badges:
            lines.append("**Flags:** " + ", ".join(markdown_text(item.get("type")).replace("_", " ") for item in badges))
        shared_flags = person.get("shared_affiliation_flags") or []
        if shared_flags:
            lines.append("**Shared background:** " + "; ".join(markdown_text(item.get("label") or item.get("config_id")).replace("_", " ") + " (" + markdown_text(item.get("relationship_type")) + (", " + markdown_text(item.get("timeframe")) if markdown_text(item.get("timeframe")) else "") + ")" for item in shared_flags))
        if claims.get("recent_signals") or person.get("conversation_hooks"):
            lines.append("**Recent signals & conversation hooks**")
        for signal in claims.get("recent_signals") or []:
            lines.append("- " + markdown_text(signal_display(signal)["detail"]) + " " + " ".join("[" + markdown_text(i) + "]" for i in claim_source_ids(signal)))
        if person.get("research_method_note"):
            lines.append("**Research method:** " + markdown_text(person["research_method_note"]))
        for hook in person.get("conversation_hooks") or []:
            lines.append("- **Conversation hook:** " + markdown_text(hook))
        lines.append("**Sources:** " + (source_links(person) or "No person-level facts claimed"))
        lines.append("")
    lines.extend(["## Full roster research ledger", "| Person | Video | Identity outcome | Research attempts | Portrait |", "|---|---:|---|---:|---|"])
    for person in data["people"]:
        lines.append("| " + markdown_text(person["name"]) + " | " + visual_confidence_display(person) + " | " + markdown_text(person.get("identity_status")) + " | " + str(len(person.get("research_attempts") or [])) + " | " + markdown_text((person.get("portrait") or {}).get("state")).replace("_", " ") + " |")
    return "\n".join(lines).rstrip() + "\n"


def render_html(data: dict[str, Any], portrait_sources: dict[int, str] | None = None) -> str:
    """Render the same validated profile model used by the print-PDF fallback."""
    import json
    esc = lambda value: html.escape(text(value), quote=True)
    portrait_sources = portrait_sources or {}
    event = data["event"]
    report = coverage_report(data)
    cards: list[str] = []
    def claim_html(label, claim):
        if not substantive(claim):
            return ""
        value = claim.get("detail") or ", ".join(filter(None, [text(claim.get("title") or claim.get("role") or claim.get("school")), text(claim.get("organization") or claim.get("degree"))]))
        cites = " ".join("[" + esc(i) + "]" for i in claim_source_ids(claim))
        return "<p><strong>" + label + ":</strong> " + esc(value) + ' <span class="quiet">' + cites + "</span></p>"
    for index, person in enumerate(data["people"], 1):
        claims = person.get("claims") or {}
        portrait = person.get("portrait") or {}
        if portrait.get("state") == "verified_public" and portrait_sources is not None and index - 1 not in portrait_sources:
            portrait_html = '<div class="portrait placeholder">Portrait omitted from this export</div>'
        elif portrait.get("state") == "verified_public":
            portrait_html = '<a href="' + esc(portrait.get("page_url")) + '"><img class="portrait" src="' + esc(portrait_sources[index - 1] if portrait_sources is not None else portrait.get("image_url")) + '" alt="Verified public professional portrait of ' + esc(person["name"]) + '"></a>'
        else:
            label = "Portrait withheld: identity unresolved" if portrait.get("state") == "withheld_ambiguous" else "No verified public portrait"
            portrait_html = '<div class="portrait placeholder">' + label + "</div>"
        badge_values = [badge_label(text(b.get("type"))) for b in person.get("badges", [])]
        badge_values += [text(f.get("label") or f.get("config_id")).replace("_", " ") + " · " + text(f.get("relationship_type")).replace("_", " ") + (" · " + text(f.get("timeframe") or f.get("current_status")) if f.get("timeframe") or f.get("current_status") else "") for f in person.get("shared_affiliation_flags", [])]
        badges = "".join('<span class="badge">' + esc(value) + "</span>" for value in badge_values)
        details = claim_html("Current role", claims.get("current_role") or {})
        if not details:
            details = '<p class="quiet">Current role not responsibly established.</p>'
        details += claim_html("Education", claims.get("education") or {})
        for claim in claims.get("historical_roles") or []:
            details += claim_html("Historical career", claim)
        for claim in claims.get("notable_background") or []:
            details += claim_html("Professional background", claim)
        rationale = person.get("identity_rationale") or person.get("ambiguity_note")
        if rationale:
            details += '<p class="quiet"><strong>Identity note:</strong> ' + esc(rationale) + "</p>"
        if claims.get("recent_signals") or person.get("conversation_hooks"):
            details += "<h4>Recent signals &amp; conversation hooks</h4>"
        for signal in claims.get("recent_signals") or []:
            details += claim_html("Signal", signal_display(signal))
        if person.get("research_method_note"):
            details += '<p class="quiet"><strong>Research method:</strong> ' + esc(person["research_method_note"]) + "</p>"
        hooks = "".join("<li>" + esc(hook) + "</li>" for hook in person.get("conversation_hooks") or [])
        sources = "".join('<li><a href="' + esc(source.get("url")) + '">[' + esc(source.get("id")) + "] " + esc(source.get("title")) + '</a> <span class="quiet"> · retrieved ' + esc(source.get("retrieved_at")) + "</span></li>" for source in person.get("evidence") or [])
        cards.append('<article class="person" id="person-' + str(index) + '"><div class="profile-top">' + portrait_html + '<div><h3>' + esc(person["name"]) + '</h3><p class="meta">' + esc(person.get("identity_status")).replace("_", " ") + ' identity · transcription confidence ' + visual_confidence_display(person) + '</p><div>' + badges + '</div></div></div>' + details + ("<p><strong>Conversation hooks</strong></p><ul>" + hooks + "</ul>" if hooks else "") + ('<details open><summary>Sources</summary><ul>' + sources + "</ul></details>" if sources else '<p class="quiet">No person-level facts claimed.</p>') + "</article>")
    priority = "".join("<li><strong>" + esc(item.get("name")) + ":</strong> " + esc(item.get("reason")) + "</li>" for item in data.get("priority_section", []) if isinstance(item, dict))
    priority_section = '<section class="summary"><h2>Who to meet first</h2><ul>' + priority + "</ul></section>" if priority else ""
    ledger = "".join("<tr><td>" + esc(person["name"]) + "</td><td>" + visual_confidence_display(person) + "</td><td>" + esc(person.get("identity_status")).replace("_", " ") + "</td><td>" + str(len(person.get("research_attempts") or [])) + "</td><td>" + esc((person.get("portrait") or {}).get("state")).replace("_", " ") + "</td></tr>" for person in data["people"])
    summary = "".join('<div class="stat"><strong>' + str(report[k]) + "</strong>" + label + "</div>" for k,label in [("full_name_roster","full-name roster"),("research_records","research records"),("confirmed_or_probable","confirmed or probable"),("verified_portraits","verified portraits")])
    note = text(event.get("resolution_note") or data.get("resolution_note"))
    limitation = text(data["video_intake"].get("limitation"))

    return '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<title>''' + esc(event["title"]) + ''' - Event Brief</title>
<style>
:root{--ink:#18212b;--muted:#536171;--line:#d7dde5;--accent:#0d5c63}*{box-sizing:border-box}body{margin:0;background:#f5f7fa;color:var(--ink);font:17px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:860px;margin:auto;padding:24px 16px 56px}h1{font-size:clamp(1.8rem,6vw,2.6rem);line-height:1.12;margin:0 0 8px}h2{margin:0 0 16px;font-size:1.35rem}h3{margin:0 0 4px;font-size:1.3rem}.meta,.quiet{color:var(--muted)}.summary,.person{background:#fff;border:1px solid var(--line);border-radius:14px;padding:20px;margin:16px 0}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px}.stat{background:#e9f5f4;border-radius:10px;padding:12px}.stat strong{display:block;font-size:1.4rem}.profile-top{display:flex;gap:18px;align-items:center}.profile-top>div{min-width:0}.portrait{width:100px;height:100px;flex-shrink:0;object-fit:cover;border-radius:10px;background:#edf1f5}.placeholder{display:flex;align-items:center;justify-content:center;padding:8px;color:var(--muted);font-size:.8rem;text-align:center}.badge{display:inline-block;margin:0 6px 6px 0;padding:3px 8px;border-radius:999px;background:#eaf0ff;font-size:.85rem}details{margin-top:14px;border-top:1px solid var(--line);padding-top:10px}summary{font-weight:600}details ul{padding-left:20px;font-size:.9rem}.ledger{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:.94rem}th,td{text-align:left;vertical-align:top;padding:9px 6px;border-bottom:1px solid var(--line)}a{color:#075e9f;overflow-wrap:anywhere}script{display:none}@page{size:letter;margin:.6in}@media print{body{background:#fff;font-size:11pt}main{max-width:none;padding:0}.person,.summary{break-inside:avoid;box-shadow:none}details{display:block}a{color:#075e9f;text-decoration:underline}.ledger{overflow:visible}thead{display:table-header-group}tr{break-inside:avoid}}@media(max-width:520px){main{padding:18px 12px 40px}.person,.summary{padding:16px}.portrait{width:76px;height:76px}.profile-top{gap:12px}table{font-size:.85rem}th,td{padding:8px 4px}}
</style></head><body><main><header><h1>''' + esc(event["title"]) + '</h1><p class="meta">' + esc(event["date"]) + ' · ' + esc(event["location"]) + ' · Hosted by ' + esc(event["host"]) + '</p><p>' + esc(event.get("purpose")) + '</p><p class="meta">Video intake: ' + esc(data["video_intake"].get("validation_state")).replace("_", " ") + (' · ' + esc(limitation) if limitation else '') + '</p></header>' + priority_section + '<section class="summary"><h2>Coverage</h2><div class="stats">' + summary + '</div>' + ('<p class="quiet">' + esc(note) + '</p>' if note else '') + '</section><section><h2>People</h2>' + ''.join(cards) + '</section><section class="ledger"><h2>Full roster research ledger</h2><table><thead><tr><th>Person</th><th>Transcription</th><th>Identity outcome</th><th>Research attempts</th><th>Portrait</th></tr></thead><tbody>' + ledger + '</tbody></table></section></main></body></html>'
