# stash-cli

CLI tool for interacting with Bitbucket Server (Stash) repositories.

## Installation

### Requirements
- Python 3.8+
- Poetry

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd stash-cli
```

2. Install dependencies using Poetry:
```bash
poetry install
```

3. Activate the poetry environment:
```bash
poetry shell
```

Or run commands directly with:
```bash
poetry run stash-cli <command>
```

## Configuration

Set the following environment variables:

```bash
export STASH_BASE_URL="https://stash.example.com"
export STASH_ACCESS_TOKEN="your-access-token"
```

Optional SSL configuration:
```bash
# Disable SSL verification (not recommended for production)
export STASH_SSL_VERIFY="false"

# Use a custom CA bundle
export STASH_SSL_VERIFY="/path/to/ca-bundle.crt"
```

## Usage

### List Pull Requests

List all open pull requests for the current repository:

```bash
stash-cli list-prs
```

With dry-run to preview the API call:
```bash
stash-cli list-prs --dry-run
```

### List reviews awaiting you

List open pull requests, in any repository, where you are a reviewer and have
not approved or marked them as needing work yet:

```bash
stash-cli list-reviews
stash-cli list-reviews --format json   # includes repo and draft flags
```

This works from any directory (no git repository needed).

### My pull requests at a glance

One view of what is waiting on you and what you have open, with counts: the pull
requests awaiting your review, then your own open ones.

```bash
stash-cli my-prs
stash-cli my-prs --format json   # {"summary": ..., "awaiting_review": [...], "authored": [...]}
```

The Comments and Tasks columns (and the totals) come from the `commentCount` and
`openTaskCount` properties that the dashboard lists on the Bitbucket Server versions
that send them; they show `-` (JSON `null`) when the server sends none. Stash has no
notifications to count. For one pull request in full, use `stash-cli pr`.

### Create Pull Request

Create a new pull request:

```bash
stash-cli create-pr --title "Add new feature"
```

With all options:
```bash
stash-cli create-pr \
  --title "Feature title" \
  --description "Detailed description" \
  --source feature/branch \
  --target develop \
  --reviewers "user1,user2"
```

Use `--dry-run` to preview without creating:
```bash
stash-cli create-pr --title "Test PR" --dry-run
```

### Show the active PR for the current branch

Render the active pull request, including review comments:

```bash
stash-cli pr
```

For editor integrations and scripting, request structured output:

```bash
stash-cli pr --format json
```

You can also target a specific PR URL:

```bash
stash-cli pr --url "https://stash.example.com/projects/PROJ/repos/repo/pull-requests/123/overview" --format json
```

### JSON output for integrations

The following commands support `--format json` for machine-readable output:

- `stash-cli list-prs --format json`
- `stash-cli list-reviews --format json`
- `stash-cli my-prs --format json`
- `stash-cli create-pr --format json`
- `stash-cli pr --format json`
- `stash-cli pr-comment --format json`
- `stash-cli pr-add-reviewer --format json`
- `stash-cli pr-remove-reviewer --format json`
- `stash-cli pr-diff --format json`
- `stash-cli pr-reply --format json`
- `stash-cli pr-approve --format json`
- `stash-cli pr-inline-comment --format json`

### Show the PR diff

Fetch the full unified diff for a pull request:

```bash
stash-cli pr-diff
stash-cli pr-diff --url "https://stash.example.com/projects/PROJ/repos/repo/pull-requests/123/overview"
stash-cli pr-diff --context 10  # more context lines
```

### Reply to a comment

Reply to an existing PR comment by its ID:

```bash
stash-cli pr-reply 12345 "Sounds good, I will fix this."
```

### Approve or request changes

Set your review status on a pull request:

```bash
stash-cli pr-approve APPROVED
stash-cli pr-approve NEEDS_WORK
```

### Post an inline comment

Comment on a specific file and line in a PR:

```bash
stash-cli pr-inline-comment src/main.py 42 "This needs a nil check"
```

### Emacs integration

This repository includes `stash-cli.el` for interacting with `stash-cli`
from Emacs.

Load it from your init file:

```elisp
(add-to-list 'load-path "/path/to/stash-cli")
(require 'stash-cli)
```

#### Transient dispatch

Bind `stash-cli-dispatch` to a key for quick access to all commands:

```elisp
(global-set-key (kbd "C-c s") #'stash-cli-dispatch)
```

Press `?` in any stash-cli buffer to open the context-sensitive dispatch.

#### Commands

- `M-x stash-cli-dispatch` - transient menu for all stash-cli commands
- `M-x stash-cli-review-current-branch` - open the active PR for the current branch
- `M-x stash-cli-review-url` - open a PR review buffer for a specific PR URL
- `M-x stash-cli-review-refresh` - refresh the current review buffer
- `M-x stash-cli-list-prs` - list open PRs (tabulated list, async)
- `M-x stash-cli-create-pr` - create a PR from Emacs
- `M-x stash-cli-pr-diff` - view the full PR diff in diff-mode
- `M-x stash-cli-pr-comment` - post a general PR comment
- `M-x stash-cli-pr-add-reviewers` - add reviewer(s)
- `M-x stash-cli-pr-remove-reviewer` - remove a reviewer

#### PR list (`stash-cli-pr-list-mode`)

The PR list uses `tabulated-list-mode` with sortable columns:

- `RET` - open the review buffer for the PR at point
- `g` - refresh the list
- `c` - create a new PR
- `b` - open the PR in a browser
- `?` - open the transient dispatch

#### Review buffer (`stash-cli-review-mode`)

The review buffer shows PR metadata, reviewers, general comments, and inline
comments with diff snippets:

- `g` - refresh the review buffer
- `n` / `p` - jump to the next / previous comment
- `r` - reply to the comment at point
- `c` - post a general comment
- `a` - approve the PR
- `A` - mark the PR as needs work
- `d` - view the full PR diff
- `v` - visit the local source location for the current inline-comment file button
- `b` - open the PR in a browser
- `RET` - activate the button at point
- `?` - open the review transient dispatch

## Developer Workflow

### Setting up for development

1. Install dependencies:
```bash
poetry install
```

2. Activate the environment:
```bash
poetry shell
```

### Making changes

1. Create a feature branch:
```bash
git checkout -b feature/your-feature
```

2. Make your changes to `stash_cli/main.py`

3. Test the changes:
```bash
stash-cli <command> --dry-run  # Preview API calls
stash-cli <command>             # Execute actual command
make test-emacs                 # Run the Emacs ERT suite
python -m unittest tests.test_list_reviews tests.test_my_prs   # Run the Python tests
```

### Testing with dry-run

Always use `--dry-run` flag to test API calls before executing:

```bash
# Preview without making actual API calls
stash-cli create-pr \
  --title "Test PR" \
  --source test-branch \
  --dry-run
```

The dry-run output shows:
- HTTP method and endpoint
- Redacted headers (sensitive info hidden)
- Query parameters
- Request payload

## Project Structure

```
stash-cli/
├── stash-cli.el          # Emacs integration
├── pyproject.toml        # Poetry configuration and dependencies
├── README.md             # Project documentation
├── src/
│   └── stash_cli/
│       ├── __init__.py   # Package initialization
│       └── main.py       # Main CLI application with all commands
└── tests/
    └── stash-cli-tests.el # Emacs ERT coverage
```

### Key functions in main.py

- `get_env_vars()` - Load and validate environment variables
- `get_git_context()` - Extract project and repo from git remote
- `get_ssl_verify()` - Determine SSL verification settings
- `print_api_call()` - Display formatted API call details for dry-run
- `redact_dict()` - Redact sensitive information from output

## Commands

### list-prs

List open pull requests.

Options:
- `--dry-run` - Preview API call without executing
- `--format, -f` - Output `table` or `json`

### list-reviews

List open pull requests awaiting your review (any repository).

Options:
- `--dry-run` - Preview API call without executing
- `--format, -f` - Output `table` or `json`

### my-prs

Your pull requests at a glance: those awaiting your review and your own open ones,
with a summary line (counts, and comments and open tasks where the server sends them).

Options:
- `--dry-run` - Preview the two API calls without executing
- `--format, -f` - Output `table` or `json`

### create-pr

Create a new pull request.

Options:
- `--title, -t` (required) - Pull request title
- `--description, -d` - Pull request description
- `--source, -s` - Source branch (defaults to current branch)
- `--target, -b` - Target branch (default: master)
- `--reviewers, -r` - Comma-separated reviewer usernames
- `--dry-run` - Preview API call without executing
- `--format, -f` - Output `text` or `json`

### pr

Show the active pull request for the current branch, including comments.

Options:
- `--branch, -b` - Override the branch lookup
- `--url, -u` - Target a specific PR URL
- `--no-comments` - Skip fetching comments
- `--dry-run` - Preview API call without executing
- `--format, -f` - Output `table`, `json`, or `csv`

### pr-comment / pr-add-reviewer / pr-remove-reviewer

PR write operations also support `--format json` for editor integrations.

### pr-diff

Fetch the full unified diff for a pull request.

Options:
- `--url, -u` - Target a specific PR URL
- `--context, -C` - Number of context lines (default: 5)
- `--dry-run` - Preview API call without executing
- `--format, -f` - Output `text` or `json`

### pr-reply

Reply to an existing PR comment.

Arguments:
- `COMMENT_ID` (required) - ID of the parent comment
- `TEXT` (required) - Reply text

Options:
- `--url, -u` - Target a specific PR URL
- `--dry-run` - Preview API call without executing
- `--format, -f` - Output `text` or `json`

### pr-approve

Set your review status on a pull request.

Arguments:
- `STATUS` (required) - `APPROVED` or `NEEDS_WORK`

Options:
- `--url, -u` - Target a specific PR URL
- `--dry-run` - Preview API call without executing
- `--format, -f` - Output `text` or `json`

### pr-inline-comment

Post an inline comment on a specific file and line.

Arguments:
- `PATH` (required) - File path in the repository
- `LINE` (required) - Line number
- `TEXT` (required) - Comment text

Options:
- `--line-type, -l` - Line type: `ADDED`, `REMOVED`, or `CONTEXT` (default: ADDED)
- `--file-type` - File type: `TO` or `FROM` (default: TO)
- `--url, -u` - Target a specific PR URL
- `--dry-run` - Preview API call without executing
- `--format, -f` - Output `text` or `json`

## Tips

- Run any command with `--help` to see all available options
- Use `--dry-run` to verify parameters before execution
- Repository context is automatically detected from git remote
- Use `poetry run` prefix if you haven't activated the shell

## Troubleshooting

**Error: Not a git repository**
- Ensure you run the command from within a git repository

**Error: No 'origin' remote found**
- Add a git remote: `git remote add origin <url>`

**Error: Missing environment variables**
- Set STASH_BASE_URL and STASH_ACCESS_TOKEN environment variables

**SSL verification errors**
- Use `--dry-run` to verify the endpoint is correct
- Check STASH_SSL_VERIFY environment variable setting

**Command not found**
- Ensure you're in the poetry environment or use `poetry run stash-cli <command>`
