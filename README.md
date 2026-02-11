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
├── poetry.lock           # Locked dependency versions (auto-generated)
├── pyproject.toml        # Poetry configuration and dependencies
├── README.md             # Project documentation
└── stash_cli/
    ├── __init__.py       # Package initialization
    └── main.py           # Main CLI application with all commands
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

### create-pr

Create a new pull request.

Options:
- `--title, -t` (required) - Pull request title
- `--description, -d` - Pull request description
- `--source, -s` - Source branch (defaults to current branch)
- `--target, -b` - Target branch (default: master)
- `--reviewers, -r` - Comma-separated reviewer usernames
- `--dry-run` - Preview API call without executing

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
