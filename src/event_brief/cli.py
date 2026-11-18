"""Local-only CLI. User inputs and output locations are explicit."""
import argparse
import base64
import json
import os
import stat
import tempfile
from pathlib import Path

from .core import render_html, render_markdown, validate

MAX_INPUT_BYTES = 2 * 1024 * 1024


def read_input(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("Input must be a regular file, not a link or device.")
        raw = source.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Input exceeds the 2 MiB limit.")
    data = json.loads(raw)
    errors, warnings, report = validate(data)
    if errors:
        raise ValueError("Invalid brief: " + "; ".join(errors))
    return data, warnings, report


def write_new(path, raw):
    """Never overwrite existing files, including links. Exports start owner-only."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate and render source-linked briefs offline.")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("validate")
    check.add_argument("input", type=Path)
    render = commands.add_parser("render")
    render.add_argument("input", type=Path)
    render.add_argument("output", type=Path)
    render.add_argument("--format", choices=["html", "markdown", "pdf"], required=True)
    render.add_argument("--portrait-dir", type=Path, help="Explicit directory of hash-pinned raster portraits")
    args = parser.parse_args(argv)
    try:
        data, warnings, report = read_input(args.input)
        if args.command == "validate":
            print(json.dumps({"valid": True, "warnings": warnings, "coverage": report}, sort_keys=True))
            return 0
        assets = {}
        if args.portrait_dir:
            from .pdf import portrait_assets
            assets, notes = portrait_assets(data, args.portrait_dir)
            if notes:
                raise ValueError("A requested portrait could not be loaded; check its filename, hash and limits.")
        if args.format == "pdf":
            from .pdf import reportlab_pdf
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "brief.pdf"
                reportlab_pdf(data, output, assets)
                raw = output.read_bytes()
        elif args.format == "html":
            portraits = {i: "data:image/png;base64," + base64.b64encode(v).decode("ascii") for i, v in assets.items()}
            raw = render_html(data, portrait_sources=portraits).encode("utf-8")
        else:
            raw = render_markdown(data).encode("utf-8")
        write_new(args.output, raw)
        print("Export created. Review its contents before sharing.")
        return 0
    except Exception as exc:
        # Never echo raw input, local filesystem locations or personal data on errors.
        print("Unable to complete command (" + type(exc).__name__ + "). Check input, dependencies, and a new output filename.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
