from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


# Official GitHub SSH host keys from https://api.github.com/meta.
# Keeping them locally avoids unauthenticated API rate limits on shared Render IPs.
GITHUB_KNOWN_HOSTS = """github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=
github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=
"""


class ResultArchiveError(RuntimeError):
    """Raised when a configured results archive cannot accept a PDF."""


def _run_git(arguments: list[str], *, cwd: Path | None, environment: dict[str, str]) -> None:
    try:
        subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            env=environment,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=45,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ResultArchiveError("GitHub архивът временно не е достъпен.") from error


def _archive_name(record: dict, session_id: str) -> tuple[str, str]:
    code = re.sub(r"[^A-Za-zА-Яа-я0-9_-]", "-", str(record.get("participant_code", "participant")))
    code = code.strip("-")[:50] or "participant"
    completed = str(record.get("completed_at", ""))
    day = completed[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", completed) else datetime.now(timezone.utc).date().isoformat()
    secret = os.environ.get("SECRET_KEY", "local-development-key")
    digest = hashlib.sha256(f"{secret}:{session_id}".encode()).hexdigest()[:12]
    return day, f"{code}-{digest}.pdf"


def archive_pdf(pdf_path: Path, record: dict, session_id: str) -> str | None:
    """Commit a PDF to a private GitHub repository, or return None when not configured."""
    repository = os.environ.get("RESULTS_GITHUB_REPOSITORY", "").strip()
    private_key = os.environ.get("RESULTS_GITHUB_SSH_KEY", "").strip()
    if not repository and not private_key:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not private_key:
        raise ResultArchiveError("Конфигурацията на GitHub архива е непълна.")
    if "\\n" in private_key:
        private_key = private_key.replace("\\n", "\n")

    day, filename = _archive_name(record, session_id)
    relative_path = Path("results") / day / filename
    with tempfile.TemporaryDirectory(prefix="albena-results-") as temporary:
        temporary_path = Path(temporary)
        key_path = temporary_path / "deploy-key"
        hosts_path = temporary_path / "known-hosts"
        checkout = temporary_path / "repository"
        key_path.write_text(f"{private_key.rstrip()}\n", encoding="utf-8")
        key_path.chmod(0o600)
        hosts_path.write_text(GITHUB_KNOWN_HOSTS, encoding="utf-8")

        environment = os.environ.copy()
        environment["GIT_SSH_COMMAND"] = (
            f"ssh -i {key_path} -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "
            f"-o UserKnownHostsFile={hosts_path}"
        )
        remote = f"git@github.com:{repository}.git"
        _run_git(["clone", "--depth", "1", remote, str(checkout)], cwd=None, environment=environment)

        destination = checkout / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf_path, destination)
        _run_git(["config", "user.name", "Albena Experiment"], cwd=checkout, environment=environment)
        _run_git(
            ["config", "user.email", "albena-experiment@users.noreply.github.com"],
            cwd=checkout,
            environment=environment,
        )
        _run_git(["add", "--", str(relative_path)], cwd=checkout, environment=environment)
        try:
            subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=checkout,
                env=environment,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
            )
        except subprocess.CalledProcessError as difference:
            if difference.returncode != 1:
                raise ResultArchiveError("GitHub архивът не можа да провери PDF файла.") from difference
        else:
            return str(relative_path)

        _run_git(["commit", "-m", f"Archive results for {filename}"], cwd=checkout, environment=environment)
        _run_git(["push", "origin", "HEAD:main"], cwd=checkout, environment=environment)
    return str(relative_path)
