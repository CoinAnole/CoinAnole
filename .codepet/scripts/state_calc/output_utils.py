"""Output helpers shared by script entrypoints."""

import os


def set_output(key: str, value: str) -> None:
    """
    Write output for GitHub Actions or print for local testing.

    In GitHub Actions, writes to GITHUB_OUTPUT file.
    Locally, prints ::set-output for compatibility with local debugging.
    """
    output_file = os.environ.get("GITHUB_OUTPUT")

    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")
    else:
        print(f"::set-output name={key}::{value}")

    print(f"  {key}={value}")
