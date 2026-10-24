"""Package the committed main tree, supplied models, materials and built frontend."""

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    for command in [["git", "diff", "--quiet"], ["git", "diff", "--cached", "--quiet"]]:
        subprocess.run(command, cwd=ROOT, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=ROOT, text=True
    ).strip()
    if branch != "main":
        raise ValueError("package the reviewed main branch")
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    dist = ROOT / "frontend/dist"
    if not (dist / "index.html").exists():
        raise ValueError("build the frontend before packaging")
    output = ROOT / "submission/多电梯群控_源码与作业材料.zip"
    temporary = output.with_suffix(".zip.tmp")
    prefix = "elevator-coursework"
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for name in files:
            if not name:
                continue
            source = ROOT / name
            if source == output:
                continue
            if not source.is_file() or source.is_symlink():
                raise ValueError(f"unsupported tracked payload: {name}")
            package.write(source, f"{prefix}/{name}")
        frontend = []
        for source in sorted(dist.rglob("*")):
            if source.is_file():
                relative = str(source.relative_to(ROOT))
                package.write(source, f"{prefix}/{relative}")
                frontend.append(
                    dict(path=relative, sha256=hashlib.sha256(source.read_bytes()).hexdigest())
                )
        package.writestr(
            f"{prefix}/SUBMISSION.json",
            json.dumps(
                dict(
                    commit=commit,
                    branch=branch,
                    frozen_dev="bc0fef6",
                    frontend=frontend,
                    includes="source, frozen models, actual curves, documents, PPTX, screenshots and built UI",
                    excludes="Git internals, Python/Node installations, caches and 10GB research archives",
                ),
                ensure_ascii=False,
                indent=2,
            ),
        )
    temporary.replace(output)
    print(json.dumps(dict(path=str(output), bytes=output.stat().st_size, commit=commit)))


if __name__ == "__main__":
    main()
