"""Offline tests for stash-cli.

Everything here runs without network access and without real STASH_* credentials.
"""

import json
from datetime import datetime, timezone

import pytest
import typer
from git import Repo
from typer.testing import CliRunner

from stash_cli.main import (
    Secret,
    _format_timestamp,
    _parse_pr_url,
    _pr_to_dict,
    app,
    get_git_context,
)

TOKEN = "abc123-xyz789"
BASE_URL = "https://stash.example.com"
PR_URL = f"{BASE_URL}/projects/PROJ/repos/repo/pull-requests/42"

SAMPLE_PR = {
    "id": 42,
    "title": "Add tests",
    "description": None,
    "state": "OPEN",
    "author": {"user": {"displayName": "Ann"}},
    "fromRef": {"displayId": "feat/tests"},
    "toRef": {"displayId": "master"},
    "links": {"self": [{"href": PR_URL}]},
    "reviewers": [
        {"user": {"name": "bob", "displayName": "Bob"}, "status": "APPROVED"}
    ],
}


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    repo = Repo.init(tmp_path)
    repo.create_remote("origin", "ssh://git@stash.example.com:7999/PROJ/repo.git")
    monkeypatch.chdir(tmp_path)
    return repo


@pytest.fixture
def stash_env(monkeypatch):
    monkeypatch.setenv("STASH_BASE_URL", BASE_URL + "/")
    monkeypatch.setenv("STASH_ACCESS_TOKEN", TOKEN)


@pytest.fixture
def no_network(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("network call attempted")

    for name in ("get", "post", "delete"):
        monkeypatch.setattr(f"stash_cli.main.requests.{name}", explode)


def test_secret_redacts_in_str_repr_and_fstrings():
    secret = Secret(TOKEN)
    assert secret.get() == TOKEN
    assert str(secret) == "***REDACTED***"
    assert repr(secret) == "***REDACTED***"
    assert f"{secret}" == "***REDACTED***"
    assert TOKEN not in f"{ {'Authorization': secret} }"


def test_parse_pr_url_extracts_context():
    assert _parse_pr_url(PR_URL) == (BASE_URL, "PROJ", "repo", "42")


@pytest.mark.parametrize(
    "bad_url",
    [
        "nonsense",
        f"{BASE_URL}/projects/PROJ",
        f"{BASE_URL}/projects/PROJ/repos/repo/pull-requests/not-a-number",
    ],
)
def test_parse_pr_url_rejects_invalid_urls(bad_url):
    with pytest.raises(typer.Exit) as excinfo:
        _parse_pr_url(bad_url)
    assert excinfo.value.exit_code == 1


def _local_format(seconds):
    return datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone().strftime(
        "%Y-%m-%d %H:%M %Z"
    )


def test_format_timestamp_handles_missing_values():
    assert _format_timestamp(None) == ""
    assert _format_timestamp(0) == ""
    assert _format_timestamp("not-a-timestamp") == ""


def test_format_timestamp_treats_input_as_milliseconds():
    assert _format_timestamp(1_700_000_000_000) == _local_format(1_700_000_000)
    # A seconds-sized value is not auto-detected; it is read as milliseconds.
    assert _format_timestamp(1_700_000_000) == _local_format(1_700_000)


@pytest.mark.parametrize(
    "remote",
    [
        "ssh://git@stash.example.com:7999/PROJ/repo.git",
        "https://stash.example.com/scm/PROJ/repo.git",
        "git@stash.example.com:PROJ/repo.git",
    ],
)
def test_get_git_context_parses_documented_remote_shapes(
    tmp_path, monkeypatch, remote
):
    repo = Repo.init(tmp_path)
    repo.create_remote("origin", remote)
    monkeypatch.chdir(tmp_path)
    assert get_git_context() == ("PROJ", "repo")


def test_pr_to_dict_serializes_nested_fields():
    result = _pr_to_dict(SAMPLE_PR, {"general": [{"id": 1}], "inline": []})

    assert result["id"] == 42
    assert result["description"] == ""
    assert result["author"] == "Ann"
    assert result["source_branch"] == "feat/tests"
    assert result["target_branch"] == "master"
    assert result["url"] == PR_URL
    assert result["reviewers"] == [
        {"username": "bob", "display_name": "Bob", "status": "APPROVED"}
    ]
    assert result["comments"] == {"general": [{"id": 1}], "inline": []}
    assert json.loads(json.dumps(result)) == result


@pytest.mark.parametrize(
    "args",
    [
        ["list-prs", "--dry-run"],
        ["create-pr", "--title", "T", "--dry-run"],
        ["pr", "--url", PR_URL, "--dry-run"],
        ["pr-comment", "hello", "--url", PR_URL, "--dry-run"],
        ["pr-add-reviewer", "bob", "--url", PR_URL, "--dry-run"],
        ["pr-remove-reviewer", "bob", "--url", PR_URL, "--dry-run"],
    ],
)
def test_dry_run_commands_are_offline_and_redacted(
    git_repo, stash_env, no_network, args
):
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert TOKEN not in result.stdout
    assert "***REDACTED***" in result.stdout
