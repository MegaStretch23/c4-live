"""Turn a CLI argument (directory or git ref) into a directory to scan."""
from __future__ import annotations

import io
import os
import subprocess
import tarfile
import tempfile


class SourceError(Exception):
    pass


def _git(repo: str, *args: str) -> bytes:
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    except FileNotFoundError:
        raise SourceError("git is not installed (needed to read a ref)")
    if r.returncode != 0:
        raise SourceError(r.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} failed")
    return r.stdout


def export_ref(repo: str, ref: str, dest: str) -> None:
    if ref.startswith("-"):
        raise SourceError(f"refusing ref that starts with '-': {ref!r}")
    _git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    data = _git(repo, "archive", "--format=tar", ref)
    root = os.path.realpath(dest)
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf:
            if not m.isreg():
                continue  # no symlinks, hardlinks, devices
            target = os.path.realpath(os.path.join(root, m.name))
            if not target.startswith(root + os.sep):
                continue  # path escape
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(tf.extractfile(m).read())


def materialize(arg: str, repo: str, tmp: tempfile.TemporaryDirectory | None = None):
    """-> (directory, label). A directory argument is used as is; anything else is a git ref in `repo`."""
    if os.path.isdir(arg):
        return os.path.abspath(arg), os.path.basename(os.path.abspath(arg)) or arg
    if tmp is None:
        raise SourceError("internal: temp dir missing")
    dest = tempfile.mkdtemp(dir=tmp.name)
    export_ref(repo, arg, dest)
    return dest, arg
