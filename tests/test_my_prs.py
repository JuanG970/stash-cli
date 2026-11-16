"""Tests for the my-prs command: your pull requests at a glance.

Run from the repository root with an interpreter that has stash-cli installed
(for example the one behind `uv tool install -e .`):

    python -m unittest tests.test_my_prs
"""

import json
import os
import unittest
from unittest import mock

import requests
from rich.console import Console
from typer.testing import CliRunner

from stash_cli import main

DASHBOARD_URL = "https://stash.example.com/rest/api/1.0/dashboard/pull-requests"
REVIEW_PARAMS = {"role": "REVIEWER", "state": "OPEN", "participantStatus": "UNAPPROVED"}
AUTHOR_PARAMS = {"role": "AUTHOR", "state": "OPEN"}


def make_pr(pr_id, title, *, draft=False, properties=None):
    pr = {
        "id": pr_id,
        "title": title,
        "description": None,
        "state": "OPEN",
        "draft": draft,
        "author": {"user": {"name": "alicea", "displayName": "Alice Author"}},
        "fromRef": {"displayId": f"fet/ABC-{pr_id}"},
        "toRef": {
            "displayId": "develop",
            "repository": {"slug": "widgets", "project": {"key": "DL"}},
        },
        "links": {
            "self": [
                {
                    "href": "https://stash.example.com/projects/DL/repos/widgets"
                    f"/pull-requests/{pr_id}"
                }
            ]
        },
        "reviewers": [],
    }
    if properties is not None:
        pr["properties"] = properties
    return pr


def dashboard(reviewing=(), authored=()):
    """An `api_get` stand-in that answers each dashboard role with its list."""

    def api_get(url, token, params=None):
        return list(reviewing if params["role"] == "REVIEWER" else authored)

    return api_get


class MyPrsTests(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(
            os.environ,
            {
                "STASH_BASE_URL": "https://stash.example.com/",
                "STASH_ACCESS_TOKEN": "s3cret-token",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.runner = CliRunner()

    def invoke(self, *args):
        return self.runner.invoke(main.app, ["my-prs", *args])

    def test_asks_the_dashboard_for_reviews_awaited_and_for_your_own(self):
        with mock.patch.object(main, "api_get", side_effect=dashboard()) as api_get:
            result = self.invoke("--format", "json")
        self.assertEqual(result.exit_code, 0, result.stderr)
        self.assertEqual(api_get.call_count, 2)
        asked = [(call.args[0], call.kwargs["params"]) for call in api_get.call_args_list]
        self.assertIn((DASHBOARD_URL, REVIEW_PARAMS), asked)
        self.assertIn((DASHBOARD_URL, AUTHOR_PARAMS), asked)

    def test_json_output_is_pure_json_with_a_summary_and_both_lists(self):
        reviewing = [make_pr(1, "Review me"), make_pr(2, "Review me too")]
        authored = [make_pr(3, "Mine", draft=True)]
        with mock.patch.object(main, "api_get", side_effect=dashboard(reviewing, authored)):
            result = self.invoke("--format", "json")
        self.assertEqual(result.exit_code, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([pr["id"] for pr in data["awaiting_review"]], [1, 2])
        self.assertEqual([pr["id"] for pr in data["authored"]], [3])
        self.assertEqual(data["awaiting_review"][0]["repo"], "DL/widgets")
        self.assertEqual(data["summary"]["awaiting_review"], 2)
        self.assertEqual(data["summary"]["authored"], 1)
        self.assertEqual(data["summary"]["drafts"], 1)

    def test_nothing_open_gives_empty_lists_and_zero_counts(self):
        with mock.patch.object(main, "api_get", side_effect=dashboard()):
            result = self.invoke("--format", "json")
        data = json.loads(result.stdout)
        self.assertEqual(data["awaiting_review"], [])
        self.assertEqual(data["authored"], [])
        self.assertEqual(data["summary"]["awaiting_review"], 0)
        self.assertEqual(data["summary"]["authored"], 0)

    def test_comment_and_task_counts_come_from_the_properties_the_server_sends(self):
        reviewing = [make_pr(1, "A", properties={"commentCount": 3, "openTaskCount": 1})]
        authored = [make_pr(2, "B", properties={"commentCount": 2, "openTaskCount": 0})]
        with mock.patch.object(main, "api_get", side_effect=dashboard(reviewing, authored)):
            result = self.invoke("--format", "json")
        data = json.loads(result.stdout)
        self.assertEqual(data["awaiting_review"][0]["comments"], 3)
        self.assertEqual(data["awaiting_review"][0]["open_tasks"], 1)
        self.assertEqual(data["summary"]["comments"], 5)
        self.assertEqual(data["summary"]["open_tasks"], 1)

    def test_counts_are_null_when_the_server_sends_none(self):
        with mock.patch.object(
            main, "api_get", side_effect=dashboard([make_pr(1, "A")], [make_pr(2, "B")])
        ):
            result = self.invoke("--format", "json")
        data = json.loads(result.stdout)
        self.assertIsNone(data["awaiting_review"][0]["comments"])
        self.assertIsNone(data["authored"][0]["open_tasks"])
        self.assertIsNone(data["summary"]["comments"])
        self.assertIsNone(data["summary"]["open_tasks"])

    def test_a_pull_request_without_counts_does_not_hide_the_ones_with(self):
        reviewing = [
            make_pr(1, "A"),
            make_pr(2, "B", properties={"commentCount": 4, "openTaskCount": 2}),
        ]
        with mock.patch.object(main, "api_get", side_effect=dashboard(reviewing)):
            result = self.invoke("--format", "json")
        summary = json.loads(result.stdout)["summary"]
        self.assertEqual(summary["comments"], 4)
        self.assertEqual(summary["open_tasks"], 2)

    def test_does_not_need_a_git_repository(self):
        with mock.patch.object(
            main, "api_get", side_effect=dashboard()
        ), mock.patch.object(
            main, "get_git_context", side_effect=AssertionError("git context used")
        ):
            self.assertEqual(self.invoke("--format", "json").exit_code, 0)

    def test_table_output_has_the_summary_and_both_lists_with_markup_escaped(self):
        reviewing = [make_pr(1, "Fix [/bold] handling")]
        authored = [make_pr(2, "My own change")]
        with mock.patch.object(
            main, "api_get", side_effect=dashboard(reviewing, authored)
        ), mock.patch.object(main, "console", Console(width=200)):
            result = self.invoke()
        # Unescaped, Rich would raise a MarkupError for the stray closing tag.
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("1 awaiting your review", result.stdout)
        self.assertIn("1 of yours open", result.stdout)
        self.assertIn("Fix [/bold] handling", result.stdout)
        self.assertIn("My own change", result.stdout)

    def test_table_output_says_so_when_a_list_is_empty(self):
        with mock.patch.object(
            main, "api_get", side_effect=dashboard([], [make_pr(2, "Mine")])
        ), mock.patch.object(main, "console", Console(width=200)):
            result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("No pull requests awaiting your review", result.stdout)

    def test_a_failed_request_exits_nonzero_and_keeps_stdout_empty(self):
        error = requests.exceptions.ConnectionError("network down")
        with mock.patch.object(main, "api_get", side_effect=error):
            result = self.invoke("--format", "json")
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("network down", result.stderr)

    def test_dry_run_makes_no_request_shows_both_calls_and_hides_the_token(self):
        with mock.patch.object(main, "api_get") as api_get:
            result = self.invoke("--dry-run")
        api_get.assert_not_called()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("REVIEWER", result.output)
        self.assertIn("AUTHOR", result.output)
        self.assertNotIn("s3cret-token", result.output)


if __name__ == "__main__":
    unittest.main()
