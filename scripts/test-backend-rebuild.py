"""Verify changed Python source reaches a rebuilt image with unchanged metadata."""

import io
import subprocess
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4


def marker_check(expected: str) -> str:
    return (
        "import cloudscope, sys; "
        f"sys.exit(0 if cloudscope.SOURCE_REBUILD_MARKER == {expected!r} else 1)"
    )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    archive = subprocess.check_output(
        ["git", "archive", "--format=zip", "HEAD", "backend"], cwd=root
    )
    identifier = uuid4().hex
    builds = [
        (f"cloudscope-source-rebuild:{identifier}-first", "first-source"),
        (f"cloudscope-source-rebuild:{identifier}-second", "second-source"),
    ]
    with tempfile.TemporaryDirectory(prefix="cloudscope-source-rebuild-") as directory:
        target = Path(directory).resolve()
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            for member in source.infolist():
                destination = (target / member.filename).resolve()
                if not destination.is_relative_to(target):
                    raise RuntimeError("Unexpected archive path")
            source.extractall(target)
        package = target / "backend/cloudscope/__init__.py"
        original = package.read_text(encoding="utf-8")
        metadata = (target / "backend/pyproject.toml").read_bytes()
        try:
            for tag, marker in builds:
                package.write_text(
                    original + f"\nSOURCE_REBUILD_MARKER = {marker!r}\n",
                    encoding="utf-8",
                )
                if (target / "backend/pyproject.toml").read_bytes() != metadata:
                    raise RuntimeError("Project metadata changed during the source-only test")
                subprocess.run(
                    [
                        "docker",
                        "build",
                        "--platform",
                        "linux/amd64",
                        "-t",
                        tag,
                        str(target / "backend"),
                    ],
                    check=True,
                )
                probe = ["docker", "run", "--rm", "--entrypoint", "python", tag, "-O", "-c"]
                subprocess.run([*probe, marker_check(marker)], check=True)
                mismatch = subprocess.run([*probe, marker_check("wrong-source")], check=False)
                if mismatch.returncode != 1:
                    raise RuntimeError("Optimized Python must reject an incorrect source marker")
        finally:
            for tag, _ in builds:
                subprocess.run(
                    ["docker", "image", "rm", tag], check=False, stdout=subprocess.DEVNULL
                )
    print("PASS: both source changes reached installed package without pyproject changes.")


if __name__ == "__main__":
    main()
