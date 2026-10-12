"""Verify changed Python source reaches a rebuilt image with unchanged metadata."""

import io
import subprocess
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    archive = subprocess.check_output(
        ["git", "archive", "--format=zip", "HEAD", "backend"], cwd=root
    )
    tag = "cloudscope-source-rebuild:" + uuid4().hex
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
            for marker in ("first-source", "second-source"):
                package.write_text(
                    original + f"\nSOURCE_REBUILD_MARKER = {marker!r}\n",
                    encoding="utf-8",
                )
                assert (target / "backend/pyproject.toml").read_bytes() == metadata
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
                subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--entrypoint",
                        "python",
                        tag,
                        "-c",
                        f"import cloudscope; assert cloudscope.SOURCE_REBUILD_MARKER == {marker!r}",
                    ],
                    check=True,
                )
        finally:
            subprocess.run(
                ["docker", "image", "rm", tag], check=False, stdout=subprocess.DEVNULL
            )
    print(
        "PASS: both source changes reached installed package without pyproject changes."
    )


if __name__ == "__main__":
    main()
