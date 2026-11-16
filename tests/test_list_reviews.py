"""Tests for the list-reviews command and the shared PR summary.

Run from the repository root with an interpreter that has stash-cli installed
(for example the one behind `uv tool install -e .`):

    python -m unittest tests.test_list_reviews
"""

import json
import os
import unittest
from unittest import mock

import requests
from rich.console import Console
from typer.testing import CliRunner

from stash_cli import main

DASHBOARD_PR = {
    "id": 10122,
    "title": "Improve report evaluation (ABC-123)",
    "description": None,
    "state": "OPEN",
    "draft": False,
    "author": {"user": {"name": "alicea", "displayName": "Alice Author"}},
    "fromRef": {"displayId": "fet/ABC-123-improve-report-evaluation"},
    "toRef": {
        "displayId": "develop",
        "repository": {"slug": "widgets", "project": {"key": "DL"}},
    },
    "links": {
        "self": [
            {
                "href": "https://stash.example.com/projects/DL/repos/widgets"
                "/pull-requests/10122"
            }
        ]
    },
    "reviewers": [
        {
            "user": {"name": "juang", "displayName": "Juan Gonzalez"},
            "status": "UNAPPROVED",
        }
    ],
}


class PrSummaryTests(unittest.TestCase):
    def test_includes_repo_and_draft(self):
        summary = main._pr_summary_to_dict(DASHBOARD_PR)
        self.assertEqual(summary["repo"], "DL/widgets")
        self.assertIs(summary["draft"], False)

    def test_reports_draft_pull_requests(self):
        summary = main._pr_summary_to_dict({**DASHBOARD_PR, "draft": True})
        self.assertIs(summary["draft"], True)

    def test_repo_is_empty_when_the_target_repository_is_missing(self):
        pr = {key: value for key, value in DASHBOARD_PR.items() if key != "toRef"}
        self.assertEqual(main._pr_summary_to_dict(pr)["repo"], "")

    def test_draft_defaults_to_false_for_older_servers(self):
        pr = {key: value for key, value in DASHBOARD_PR.items() if key != "draft"}
        self.assertIs(main._pr_summary_to_dict(pr)["draft"], False)


class ListReviewsTests(unittest.TestCase):
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
        return self.runner.invoke(main.app, ["list-reviews", *args])

    def test_json_output_is_pure_json_on_stdout(self):
        with mock.patch.object(main, "api_get", return_value=[DASHBOARD_PR]):
            result = self.invoke("--format", "json")
        self.assertEqual(result.exit_code, 0, result.stderr)
        pull_requests = json.loads(result.stdout)["pull_requests"]
        self.assertEqual([pr["id"] for pr in pull_requests], [10122])
        self.assertEqual(pull_requests[0]["repo"], "DL/widgets")
        self.assertEqual(
            pull_requests[0]["source_branch"], "fet/ABC-123-improve-report-evaluation"
        )

    def test_empty_result_is_an_empty_list(self):
        with mock.patch.object(main, "api_get", return_value=[]):
            result = self.invoke("--format", "json")
        self.assertEqual(json.loads(result.stdout), {"pull_requests": []})

    def test_asks_the_dashboard_for_unapproved_reviewer_requests(self):
        with mock.patch.object(main, "api_get", return_value=[]) as api_get:
            self.invoke("--format", "json")
        url = api_get.call_args.args[0]
        self.assertEqual(
            url, "https://stash.example.com/rest/api/1.0/dashboard/pull-requests"
        )
        self.assertEqual(
            api_get.call_args.kwargs["params"],
            {"role": "REVIEWER", "state": "OPEN", "participantStatus": "UNAPPROVED"},
        )

    def test_does_not_need_a_git_repository(self):
        with mock.patch.object(main, "api_get", return_value=[]), mock.patch.object(
            main, "get_git_context", side_effect=AssertionError("git context used")
        ):
            self.assertEqual(self.invoke("--format", "json").exit_code, 0)

    def test_table_output_escapes_markup_in_titles(self):
        pr = {**DASHBOARD_PR, "title": "Fix [/bold] handling"}
        with mock.patch.object(main, "api_get", return_value=[pr]), mock.patch.object(
            main, "console", Console(width=200)
        ):
            result = self.invoke()
        # Unescaped, Rich would raise a MarkupError for the stray closing tag.
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Fix [/bold] handling", result.stdout)

    def test_failed_request_exits_nonzero_and_keeps_stdout_empty(self):
        error = requests.exceptions.ConnectionError("network down")
        with mock.patch.object(main, "api_get", side_effect=error):
            result = self.invoke("--format", "json")
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("network down", result.stderr)

    def test_dry_run_makes_no_request_and_hides_the_token(self):
        with mock.patch.object(main, "api_get") as api_get:
            result = self.invoke("--dry-run")
        api_get.assert_not_called()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("s3cret-token", result.output)


if __name__ == "__main__":
    unittest.main()
