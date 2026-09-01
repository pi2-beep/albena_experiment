from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import tempfile
from ftplib import FTP, FTP_TLS, all_errors as FTP_ERRORS
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


# Official GitHub SSH host keys from https://api.github.com/meta.
# Keeping them locally avoids unauthenticated API rate limits on shared Render IPs.
GITHUB_KNOWN_HOSTS = """github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=
github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=
"""


class ResultArchiveError(RuntimeError):
    """Raised when a configured results archive cannot accept a PDF."""


def _enabled(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


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


def _ftp_directory(value: str) -> str:
    value = value.strip().replace("\\", "/") or "/albena-results"
    parts = [part for part in PurePosixPath(value).parts if part not in {"/", "."}]
    if any(part == ".." for part in parts):
        raise ResultArchiveError("FTP директорията е невалидна.")
    return "/" + "/".join(parts)


def _ensure_ftp_directory(client: FTP, directory: str) -> None:
    client.cwd("/")
    for part in PurePosixPath(directory).parts:
        if part in {"/", "."}:
            continue
        try:
            client.cwd(part)
        except FTP_ERRORS:
            client.mkd(part)
            client.cwd(part)


def _archive_to_ftp(pdf_path: Path, record: dict, session_id: str) -> str:
    host = os.environ.get("RESULTS_FTP_HOST", "").strip()
    username = os.environ.get("RESULTS_FTP_USERNAME", "").strip()
    password = os.environ.get("RESULTS_FTP_PASSWORD", "")
    if not host or not username or not password:
        raise ResultArchiveError("Конфигурацията на FTP архива е непълна.")
    try:
        port = int(os.environ.get("RESULTS_FTP_PORT", "21"))
    except ValueError as error:
        raise ResultArchiveError("FTP портът е невалиден.") from error
    if not 1 <= port <= 65535:
        raise ResultArchiveError("FTP портът е невалиден.")

    use_tls = _enabled(os.environ.get("RESULTS_FTP_TLS"), default=True)
    passive = _enabled(os.environ.get("RESULTS_FTP_PASSIVE"), default=True)
    tls_server_name = os.environ.get("RESULTS_FTP_TLS_SERVER_NAME", "").strip()
    if tls_server_name and not re.fullmatch(r"[A-Za-z0-9.-]+", tls_server_name):
        raise ResultArchiveError("TLS името на FTP сървъра е невалидно.")
    base_directory = _ftp_directory(os.environ.get("RESULTS_FTP_DIRECTORY", "/albena-results"))
    day, filename = _archive_name(record, session_id)
    remote_directory = f"{base_directory.rstrip('/')}/{day}"
    json_filename = f"{Path(filename).stem}.json"
    json_bytes = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")

    client: FTP
    if use_tls:
        client = FTP_TLS(context=ssl.create_default_context(), timeout=30)
    else:
        client = FTP(timeout=30)

    uploaded: list[str] = []
    try:
        client.connect(host, port, timeout=30)
        # Some hosting providers publish the FTP endpoint as an IP/domain alias,
        # while their verified TLS certificate uses the hosting server name.
        if isinstance(client, FTP_TLS) and tls_server_name:
            client.host = tls_server_name
        client.login(username, password)
        if isinstance(client, FTP_TLS):
            client.prot_p()
        client.set_pasv(passive)
        _ensure_ftp_directory(client, remote_directory)
        with pdf_path.open("rb") as pdf_file:
            client.storbinary(f"STOR {filename}", pdf_file)
        uploaded.append(filename)
        client.storbinary(f"STOR {json_filename}", io.BytesIO(json_bytes))
        uploaded.append(json_filename)
        try:
            client.quit()
        except FTP_ERRORS:
            client.close()
    except (OSError, ValueError, *FTP_ERRORS) as error:
        for remote_name in uploaded:
            try:
                client.delete(remote_name)
            except (OSError, *FTP_ERRORS):
                pass
        try:
            client.close()
        except OSError:
            pass
        raise ResultArchiveError("FTP архивът временно не е достъпен.") from error
    return f"{remote_directory}/{filename}"


def _archive_to_github(pdf_path: Path, record: dict, session_id: str) -> str | None:
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


def archive_pdf(pdf_path: Path, record: dict, session_id: str) -> str | None:
    """Archive a completed PDF and its data using the configured backend."""
    backend = os.environ.get("RESULTS_ARCHIVE_BACKEND", "").strip().lower()
    if backend == "ftp":
        return _archive_to_ftp(pdf_path, record, session_id)
    if backend == "github":
        return _archive_to_github(pdf_path, record, session_id)
    if backend:
        raise ResultArchiveError("Избраният архив не се поддържа.")
    return _archive_to_github(pdf_path, record, session_id)
