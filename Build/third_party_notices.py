"""Write THIRD_PARTY_NOTICES.md for the environment that runs this script.

Usage:
    python Build/third_party_notices.py OUTPUT_PATH [--ignore NAME ...]

The packaging script runs this with the release's runtime-only interpreter,
so the inventory lists exactly what the launcher installs and nothing from
the developer tools. Only the standard library is used.

pip-licenses' --python mode cannot do this job. It reads the target
interpreter's sys.path as a space-joined string and splits it on spaces, so
an install path with a space in it (this repository's own name has three)
falls apart and the inventory comes back empty.
"""

from __future__ import annotations

import argparse
import sys
from importlib import metadata
from pathlib import Path

HEADER = (
    "# Third-Party Notices",
    "",
    "Packages installed into the Workbench's private environment, with their",
    "declared licenses. Generated at packaging time from the package metadata",
    "of the runtime environment.",
    "",
    "| Package | Version | License | Project |",
    "|---|---|---|---|",
)

# Project-URL labels in the order a reader would want them.
PREFERRED_URL_LABELS = (
    "homepage",
    "home",
    "source",
    "repository",
    "source code",
    "documentation",
)


def license_of(meta: metadata.PackageMetadata) -> str:
    """Return the declared license, preferring the machine-readable fields."""
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    names: list[str] = []
    for classifier in meta.get_all("Classifier") or []:
        if not classifier.startswith("License :: "):
            continue
        name = classifier.split(" :: ")[-1].strip()
        if name and name not in names:
            names.append(name)
    if names:
        return ", ".join(names)
    text = (meta.get("License") or "").strip()
    if text and "\n" not in text and len(text) <= 80:
        return text
    return "See package metadata"


def url_of(meta: metadata.PackageMetadata) -> str:
    """Return the project's home page, or its best Project-URL entry."""
    home = (meta.get("Home-page") or "").strip()
    if home:
        return home
    urls: dict[str, str] = {}
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        urls.setdefault(label.strip().lower(), url.strip())
    for label in PREFERRED_URL_LABELS:
        if urls.get(label):
            return urls[label]
    return next(iter(urls.values()), "")


def inventory(ignore: set[str]) -> list[dict[str, str]]:
    """Return one row per installed distribution, sorted by name."""
    rows: dict[str, dict[str, str]] = {}
    for dist in metadata.distributions():
        name = (dist.metadata.get("Name") or "").strip()
        if not name or name.lower() in ignore or name.lower() in rows:
            continue
        rows[name.lower()] = {
            "Name": name,
            "Version": dist.version or "",
            "License": license_of(dist.metadata),
            "URL": url_of(dist.metadata),
        }
    return [rows[key] for key in sorted(rows)]


def render(rows: list[dict[str, str]]) -> str:
    lines = list(HEADER)
    for row in rows:
        project = f"<{row['URL']}>" if row["URL"] else ""
        lines.append(
            f"| {row['Name']} | {row['Version']} | {row['License']} | {project} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "output", type=Path, help="Path of the THIRD_PARTY_NOTICES.md to write"
    )
    parser.add_argument(
        "--ignore",
        nargs="*",
        default=[],
        metavar="NAME",
        help="Distributions to leave out",
    )
    args = parser.parse_args(argv)

    rows = inventory({name.lower() for name in args.ignore})
    if not rows:
        print(
            "No distributions found in this environment. The notices would be empty.",
            file=sys.stderr,
        )
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(rows), encoding="utf-8")
    print(f"Notices : {len(rows)} packages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
