import os
import re
import json
import typer
import requests
from datetime import datetime, timezone
import urllib.parse
import urllib3
from git import Repo, InvalidGitRepositoryError
from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree
from rich.markup import escape

app = typer.Typer()
console = Console()


class Secret:
    """Wrapper for sensitive values that redacts them when converted to string."""
    
    def __init__(self, value):
        self._value = value
    
    def __str__(self):
        return "***REDACTED***"
    
    def __repr__(self):
        return "***REDACTED***"
    
    def get(self):
        """Get the actual secret value."""
        return self._value

def print_api_call(method, url, headers=None, params=None, payload=None):
    """Print formatted API call details for dry-run mode."""
    console.print("\n[bold yellow]DRY RUN - API Call Details[/bold yellow]")
    console.print(f"[bold]Method:[/bold] [cyan]{method}[/cyan]")
    console.print(f"[bold]Endpoint:[/bold] {url}")
    
    if headers:
        console.print(f"\n[bold]Headers:[/bold]")
        headers_json = json.dumps(headers, indent=2)
        syntax = Syntax(headers_json, "json", theme="monokai", line_numbers=False)
        console.print(syntax)
    
    if params:
        console.print(f"\n[bold]Query Parameters:[/bold]")
        params_json = json.dumps(params, indent=2)
        syntax = Syntax(params_json, "json", theme="monokai", line_numbers=False)
        console.print(syntax)
    
    if payload:
        console.print(f"\n[bold]Payload:[/bold]")
        payload_json = json.dumps(payload, indent=2)
        syntax = Syntax(payload_json, "json", theme="monokai", line_numbers=False)
        console.print(syntax)
    
    console.print("\n[bold yellow]Note:[/bold yellow] No actual API request will be made in dry-run mode.\n")


def get_ssl_verify():
    """Determine the SSL verify parameter for requests.

    Checks STASH_SSL_VERIFY env var:
      - "false" / "0" / "no"  -> False (disable verification)
      - a file path           -> use as CA bundle
      - unset / "true"        -> True (default verification)
    """
    val = os.environ.get("STASH_SSL_VERIFY", "").strip()
    if val.lower() in ("false", "0", "no"):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return False
    if val and os.path.isfile(val):
        return val
    return True

@app.callback()
def callback():
    """
    Stash CLI tool.
    """

def get_env_vars():
    base_url = os.environ.get("STASH_BASE_URL")
    token = Secret(os.environ.get("STASH_ACCESS_TOKEN", ""))

    if not base_url or not token.get():
        console.print("[bold red]Error:[/bold red] Missing environment variables.")
        console.print("Please set the following environment variables:")
        if not base_url:
            console.print("  - [bold yellow]STASH_BASE_URL[/bold yellow] (e.g., https://stash.example.com)")
        if not token:
            console.print("  - [bold yellow]STASH_ACCESS_TOKEN[/bold yellow]")
        raise typer.Exit(code=1)

    return base_url.rstrip("/"), token


def get_access_token():
    token = Secret(os.environ.get("STASH_ACCESS_TOKEN", ""))
    if not token.get():
        console.print("[bold red]Error:[/bold red] Missing environment variables.")
        console.print("Please set the following environment variables:")
        console.print("  - [bold yellow]STASH_ACCESS_TOKEN[/bold yellow]")
        raise typer.Exit(code=1)
    return token


def api_get(url, token, params=None):
    """Make an authenticated GET request to the Stash API with pagination support.

    Returns the full list of values across all pages.
    """
    headers = {"Authorization": f"Bearer {token.get()}"}
    verify = get_ssl_verify()
    all_values = []
    start = 0

    while True:
        paged_params = dict(params or {})
        paged_params["start"] = start
        paged_params.setdefault("limit", 100)

        response = requests.get(
            url, headers=headers, params=paged_params, timeout=30, verify=verify
        )
        response.raise_for_status()
        data = response.json()

        all_values.extend(data.get("values", []))

        if data.get("isLastPage", True):
            break
        start = data.get("nextPageStart", start + data.get("limit", 100))

    return all_values

def get_git_context():
    try:
        repo = Repo(os.getcwd(), search_parent_directories=True)
    except InvalidGitRepositoryError:
        console.print("[bold red]Error:[/bold red] Not a git repository.")
        raise typer.Exit(code=1)

    try:
        remote_url = repo.remote("origin").url
    except ValueError:
        console.print("[bold red]Error:[/bold red] No 'origin' remote found.")
        raise typer.Exit(code=1)

    # Parsing logic
    # Common formats:
    # ssh://git@stash.example.com:7999/PROJ/repo.git
    # https://stash.example.com/scm/PROJ/repo.git
    # git@stash.example.com:PROJ/repo.git
    
    # Remove .git suffix
    if remote_url.endswith(".git"):
        remote_url = remote_url[:-4]
    
    # Regex for standard Bitbucket Server URLs
    # Matches /PROJ/repo at the end
    match = re.search(r"/(?P<project>[^/]+)/(?P<repo>[^/]+)$", remote_url)
    if match:
        project_key = match.group("project")
        repo_slug = match.group("repo")
    else:
        # Fallback for scp-like syntax git@host:PROJ/repo
        match_scp = re.search(r":(?P<project>[^/]+)/(?P<repo>[^/]+)$", remote_url)
        if match_scp:
            project_key = match_scp.group("project")
            repo_slug = match_scp.group("repo")
        else:
            console.print(f"[bold red]Error:[/bold red] Could not parse project and repo from remote URL: {remote_url}")
            raise typer.Exit(code=1)

    return project_key, repo_slug

@app.command()
def list_prs(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print API call details without executing")
):
    """List open Pull Requests for the current repository."""
    base_url, token = get_env_vars()
    project_key, repo_slug = get_git_context()

    console.print(f"Fetching PRs for [cyan]{project_key}/{repo_slug}[/cyan]...")

    api_url = f"{base_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests"
    headers = {"Authorization": f"Bearer {token.get()}"}
    params = {"state": "OPEN"}
    verify = get_ssl_verify()

    if dry_run:
        safe_headers = {"Authorization": f"Bearer {token}"}
        print_api_call("GET", api_url, headers=safe_headers, params=params)
        return

    try:
        response = requests.get(api_url, headers=headers, params=params, timeout=10, verify=verify)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Error fetching PRs:[/bold red] {e}")
        if hasattr(e, 'response') and e.response is not None:
             console.print(f"Status: {e.response.status_code}")
             # Try to print error message from Stash if available
             try:
                 err_data = e.response.json()
                 errors = err_data.get("errors", [])
                 for err in errors:
                     console.print(f"[red]{err.get('message')}[/red]")
             except:
                 pass
        raise typer.Exit(code=1)

    values = data.get("values", [])

    if not values:
        console.print("[yellow]No open pull requests found.[/yellow]")
        return

    table = Table(title=f"Open Pull Requests ({len(values)})")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="white")
    table.add_column("Author", style="green")
    table.add_column("Source", style="magenta")
    table.add_column("Target", style="magenta")
    table.add_column("Link", style="blue")

    for pr in values:
        pr_id = str(pr.get("id"))
        title = pr.get("title")
        author = pr.get("author", {}).get("user", {}).get("displayName", "Unknown")
        from_ref = pr.get("fromRef", {}).get("displayId")
        to_ref = pr.get("toRef", {}).get("displayId")
        links = pr.get("links", {}).get("self", [])
        link = links[0].get("href") if links else ""

        table.add_row(pr_id, title, author, from_ref, to_ref, link)

    console.print(table)

@app.command()
def create_pr(
    title: str = typer.Option(..., "--title", "-t", help="Pull request title"),
    description: str = typer.Option("", "--description", "-d", help="Pull request description"),
    source_branch: str = typer.Option(None, "--source", "-s", help="Source branch (defaults to current branch)"),
    target_branch: str = typer.Option("master", "--target", "-b", help="Target branch (default: master)"),
    reviewers: str = typer.Option("", "--reviewers", "-r", help="Comma-separated list of reviewer usernames"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print API call details without executing"),
):
    """Create a Pull Request in Stash/Bitbucket Server."""
    base_url, token = get_env_vars()
    project_key, repo_slug = get_git_context()
    
    # Get current branch if source not specified
    if not source_branch:
        try:
            repo = Repo(os.getcwd(), search_parent_directories=True)
            source_branch = repo.active_branch.name
            console.print(f"Using current branch as source: [cyan]{source_branch}[/cyan]")
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] Could not determine current branch: {e}")
            raise typer.Exit(code=1)
    
    console.print(f"Creating PR: [cyan]{source_branch}[/cyan] -> [cyan]{target_branch}[/cyan]")
    
    api_url = f"{base_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests"
    headers = {
        "Authorization": f"Bearer {token.get()}",
        "Content-Type": "application/json"
    }
    verify = get_ssl_verify()
    
    # Build the payload
    payload = {
        "title": title,
        "description": description,
        "fromRef": {
            "id": f"refs/heads/{source_branch}",
            "repository": {
                "slug": repo_slug,
                "project": {
                    "key": project_key
                }
            }
        },
        "toRef": {
            "id": f"refs/heads/{target_branch}",
            "repository": {
                "slug": repo_slug,
                "project": {
                    "key": project_key
                }
            }
        }
    }
    
    # Add reviewers if provided
    if reviewers:
        reviewer_list = [r.strip() for r in reviewers.split(",") if r.strip()]
        payload["reviewers"] = [{"user": {"name": username}} for username in reviewer_list]
    
    if dry_run:
        safe_headers = {"Authorization": f"Bearer {token}"}
        print_api_call("POST", api_url, headers=safe_headers, payload=payload)
        return
    
    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=10, verify=verify)
        response.raise_for_status()
        pr_data = response.json()
        
        # Display success message
        pr_id = pr_data.get("id")
        pr_links = pr_data.get("links", {}).get("self", [])
        pr_url = pr_links[0].get("href") if pr_links else ""
        
        console.print(f"[bold green]✓[/bold green] Pull Request created successfully!")
        console.print(f"  ID: [cyan]{pr_id}[/cyan]")
        console.print(f"  Title: {title}")
        console.print(f"  URL: [blue]{pr_url}[/blue]")
        
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Error creating PR:[/bold red] {e}")
        if hasattr(e, 'response') and e.response is not None:
            console.print(f"Status: {e.response.status_code}")
            # Try to print error message from Stash if available
            try:
                err_data = e.response.json()
                errors = err_data.get("errors", [])
                for err in errors:
                    console.print(f"[red]{err.get('message')}[/red]")
            except:
                pass
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# pr command – show the active PR for the current (or given) branch
# ---------------------------------------------------------------------------

def _find_pr_for_branch(base_url, token, project_key, repo_slug, branch):
    """Return the first OPEN pull request whose source branch matches *branch*."""
    url = f"{base_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests"
    params = {"state": "OPEN", "direction": "OUTGOING", "at": f"refs/heads/{branch}"}
    prs = api_get(url, token, params=params)
    if prs:
        return prs[0]
    return None


def _parse_pr_url(pr_url):
    parsed = urllib.parse.urlparse(pr_url)
    if not parsed.scheme or not parsed.netloc:
        console.print(f"[bold red]Error:[/bold red] Invalid URL: {pr_url}")
        raise typer.Exit(code=1)

    match = re.search(
        r"/projects/(?P<project>[^/]+)/repos/(?P<repo>[^/]+)/pull-requests/(?P<id>\d+)",
        parsed.path,
    )
    if not match:
        console.print(f"[bold red]Error:[/bold red] Could not parse PR URL: {pr_url}")
        raise typer.Exit(code=1)

    base_url = f"{parsed.scheme}://{parsed.netloc}"
    project_key = match.group("project")
    repo_slug = match.group("repo")
    pr_id = match.group("id")
    return base_url, project_key, repo_slug, pr_id


def _render_pr_header(pr, base_url, project_key, repo_slug):
    """Print a rich panel with the PR summary."""
    pr_id = pr.get("id")
    title = pr.get("title", "")
    description = pr.get("description", "") or ""
    state = pr.get("state", "UNKNOWN")
    author = pr.get("author", {}).get("user", {}).get("displayName", "Unknown")
    from_ref = pr.get("fromRef", {}).get("displayId", "?")
    to_ref = pr.get("toRef", {}).get("displayId", "?")
    links = pr.get("links", {}).get("self", [])
    link = links[0].get("href") if links else ""

    reviewers = pr.get("reviewers", [])
    reviewer_strs = []
    for r in reviewers:
        name = r.get("user", {}).get("displayName", "?")
        status = r.get("status", "UNAPPROVED")
        icon = {"APPROVED": "[green]APPROVED[/green]",
                "NEEDS_WORK": "[yellow]NEEDS WORK[/yellow]"}.get(status, "[dim]UNAPPROVED[/dim]")
        reviewer_strs.append(f"  {name}: {icon}")

    body = Text.from_markup(
        f"[bold]#{pr_id}[/bold] {escape(title)}\n"
        f"[dim]{escape(from_ref)}[/dim] -> [dim]{escape(to_ref)}[/dim]\n"
        f"Author: [green]{escape(author)}[/green]  State: [cyan]{state}[/cyan]\n"
    )
    if link:
        body.append_text(Text.from_markup(f"Link: [blue]{escape(link)}[/blue]\n"))
    if reviewer_strs:
        body.append_text(Text.from_markup("\n[bold]Reviewers:[/bold]\n" + "\n".join(reviewer_strs) + "\n"))
    if description:
        body.append_text(Text.from_markup(f"\n[bold]Description:[/bold]\n{escape(description)}\n"))

    console.print(Panel(body, title="Pull Request", border_style="cyan"))


def _build_diff_snippet(anchor, diff):
    """Extract a code snippet from the diff hunks around the commented line.

    Returns a list of (line_number, code_text, is_highlighted) tuples.
    """
    if not anchor or not diff:
        return []

    target_line = anchor.get("line")
    line_type = anchor.get("lineType", "ADDED")
    if target_line is None:
        return []

    # Collect all lines from all hunks into a flat list with metadata
    all_lines = []
    for hunk in diff.get("hunks", []):
        for segment in hunk.get("segments", []):
            seg_type = segment.get("type", "CONTEXT")  # ADDED, REMOVED, CONTEXT
            for ln in segment.get("lines", []):
                line_no = ln.get("destination") if line_type != "REMOVED" else ln.get("source")
                all_lines.append({
                    "line_no": line_no,
                    "code": ln.get("line", ""),
                    "seg_type": seg_type,
                    "is_target": line_no == target_line,
                })

    # Find the target line index
    target_idx = None
    for i, ln in enumerate(all_lines):
        if ln["is_target"]:
            target_idx = i
            break

    if target_idx is None:
        return []

    # Show a window of context around the target line
    context_before = 3
    context_after = 3
    start = max(0, target_idx - context_before)
    end = min(len(all_lines), target_idx + context_after + 1)

    snippet = []
    for ln in all_lines[start:end]:
        prefix = " "
        if ln["seg_type"] == "ADDED":
            prefix = "+"
        elif ln["seg_type"] == "REMOVED":
            prefix = "-"

        snippet.append((ln["line_no"], prefix, ln["code"], ln["is_target"]))

    return snippet


def _render_code_snippet(snippet):
    """Render a code snippet as a rich Text block with line numbers and highlighting."""
    text = Text()
    for line_no, prefix, code, is_target in snippet:
        num_str = f"{line_no:>5}" if line_no else "     "

        if is_target:
            text.append(f" >> {num_str} {prefix} {code}\n", style="bold yellow")
        elif prefix == "+":
            text.append(f"    {num_str} {prefix} {code}\n", style="green")
        elif prefix == "-":
            text.append(f"    {num_str} {prefix} {code}\n", style="red")
        else:
            text.append(f"    {num_str} {prefix} {code}\n", style="dim")

    return text


def _render_comment_with_replies(comment, tree_node, indent=0):
    """Recursively render a comment and its replies into a rich Tree node."""
    author = comment.get("author", {}).get("displayName", "Unknown")
    text = comment.get("text", "")
    severity = comment.get("severity", "NORMAL")
    state = comment.get("state", "")
    created_date = comment.get("createdDate")

    timestamp = _format_timestamp(created_date)

    severity_badge = ""
    if severity == "BLOCKER":
        severity_badge = " [bold red]BLOCKER[/bold red]"

    state_badge = ""
    if state == "RESOLVED":
        state_badge = " [green](resolved)[/green]"

    header = f"[bold]{escape(author)}[/bold]"
    if timestamp:
        header += f" [dim]{escape(timestamp)}[/dim]"
    header += f"{severity_badge}{state_badge}"
    body = f"{header}\n{escape(text)}"
    child_node = tree_node.add(body)

    for reply in comment.get("comments", []):
        _render_comment_with_replies(reply, child_node, indent + 1)


def _format_timestamp(timestamp_ms):
    if not timestamp_ms:
        return ""

    try:
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).astimezone()
    except (OSError, OverflowError, ValueError, TypeError):
        return ""

    return dt.strftime("%Y-%m-%d %H:%M %Z")


def _fetch_and_render_comments(base_url, token, project_key, repo_slug, pr_id):
    """Fetch PR activities and render comments grouped by file with code context."""
    url = (
        f"{base_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}"
        f"/pull-requests/{pr_id}/activities"
    )
    activities = api_get(url, token)

    comment_activities = [
        a for a in activities
        if a.get("action") == "COMMENTED" and a.get("comment")
    ]

    if not comment_activities:
        console.print("[dim]No comments on this PR.[/dim]\n")
        return

    # Separate inline (file-anchored) comments from general comments
    inline = []
    general = []
    for activity in comment_activities:
        if activity.get("commentAnchor") and activity["commentAnchor"].get("path"):
            inline.append(activity)
        else:
            general.append(activity)

    # --- General (non-inline) comments ---
    if general:
        tree = Tree(f"[bold]General Comments ({len(general)})[/bold]")
        for activity in general:
            _render_comment_with_replies(activity["comment"], tree)
        console.print(tree)
        console.print()

    # --- Inline comments grouped by file ---
    if inline:
        # Group by file path
        by_file = {}
        for activity in inline:
            path = activity["commentAnchor"]["path"]
            by_file.setdefault(path, []).append(activity)

        # Sort each file's comments by line number
        for path in by_file:
            by_file[path].sort(key=lambda a: a["commentAnchor"].get("line", 0))

        console.print(f"[bold]Inline Comments ({len(inline)} across {len(by_file)} files)[/bold]\n")

        for path in sorted(by_file.keys()):
            file_activities = by_file[path]
            diff_link = (
                f"{base_url}/projects/{project_key}/repos/{repo_slug}"
                f"/pull-requests/{pr_id}/diff#{path}"
            )
            console.print(Panel(
                f"[blue]{escape(diff_link)}[/blue]",
                title=f"[bold magenta]{escape(path)}[/bold magenta]",
                border_style="magenta",
                expand=False,
            ))

            for activity in file_activities:
                anchor = activity["commentAnchor"]
                diff = activity.get("diff")
                comment = activity["comment"]
                line_num = anchor.get("line", "?")
                line_type = anchor.get("lineType", "")

                # Code snippet from diff
                snippet = _build_diff_snippet(anchor, diff)
                if snippet:
                    console.print(_render_code_snippet(snippet))

                # Comment as a tree (supports threaded replies)
                location = f"[dim]Line {line_num}[/dim]"
                if line_type:
                    location += f" [dim]({line_type})[/dim]"
                tree = Tree(location)
                _render_comment_with_replies(comment, tree)
                console.print(tree)
                console.print()


@app.command()
def pr(
    branch: str = typer.Option(
        None, "--branch", "-b",
        help="Branch name to look up (defaults to current branch)"
    ),
    url: str = typer.Option(
        None, "--url", "-u",
        help="Stash PR URL to use instead of auto-detecting from git status"
    ),
    no_comments: bool = typer.Option(
        False, "--no-comments",
        help="Skip fetching comments"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Print API call details without executing"
    ),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="Output format: table, json, csv"
    ),
):
    """Show the active Pull Request for the current branch with comments and tasks."""
    if url:
        base_url, project_key, repo_slug, pr_id = _parse_pr_url(url)
        token = get_access_token()

        console.print(
            f"Looking up PR [cyan]#{pr_id}[/cyan] in "
            f"[cyan]{project_key}/{repo_slug}[/cyan]...\n"
        )

        pr_api_url = (
            f"{base_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}"
            f"/pull-requests/{pr_id}"
        )

        if dry_run:
            safe_headers = {"Authorization": f"Bearer {token}"}
            print_api_call("GET", pr_api_url, headers=safe_headers)
            if not no_comments:
                print_api_call(
                    "GET",
                    f"{base_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{pr_id}/activities",
                    headers=safe_headers,
                )
            return

        try:
            headers = {"Authorization": f"Bearer {token.get()}"}
            verify = get_ssl_verify()
            response = requests.get(pr_api_url, headers=headers, timeout=10, verify=verify)
            response.raise_for_status()
            pr_data = response.json()
        except requests.exceptions.RequestException as e:
            console.print(f"[bold red]Error fetching PR:[/bold red] {e}")
            raise typer.Exit(code=1)
    else:
        base_url, token = get_env_vars()
        project_key, repo_slug = get_git_context()

        # Resolve branch
        if not branch:
            try:
                repo = Repo(os.getcwd(), search_parent_directories=True)
                branch = repo.active_branch.name
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] Could not determine current branch: {e}")
                raise typer.Exit(code=1)

        console.print(f"Looking up active PR for branch [cyan]{branch}[/cyan] "
                      f"in [cyan]{project_key}/{repo_slug}[/cyan]...\n")

        pr_url = f"{base_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests"
        pr_params = {"state": "OPEN", "direction": "OUTGOING", "at": f"refs/heads/{branch}"}

        if dry_run:
            safe_headers = {"Authorization": f"Bearer {token}"}
            print_api_call("GET", pr_url, headers=safe_headers, params=pr_params)
            if not no_comments:
                print_api_call("GET",
                               f"{base_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{{prId}}/activities",
                               headers=safe_headers)
            return

        try:
            pr_data = _find_pr_for_branch(base_url, token, project_key, repo_slug, branch)
        except requests.exceptions.RequestException as e:
            console.print(f"[bold red]Error fetching PRs:[/bold red] {e}")
            raise typer.Exit(code=1)

        if not pr_data:
            console.print(f"[yellow]No open pull request found for branch '{branch}'.[/yellow]")
            raise typer.Exit(code=0)

        pr_id = pr_data.get("id")

    # --- Header ---
    _render_pr_header(pr_data, base_url, project_key, repo_slug)

    # --- Comments ---
    if not no_comments:
        try:
            _fetch_and_render_comments(base_url, token, project_key, repo_slug, pr_id)
        except requests.exceptions.RequestException as e:
            console.print(f"[bold red]Error fetching comments:[/bold red] {e}")


def _resolve_pr_context(url: str | None):
    """Resolve PR context from a URL or auto-detect from the current branch.

    Returns (base_url, token, project_key, repo_slug, pr_id, pr_data).
    pr_data may be None when the caller does not need the full PR object (e.g. dry-run).
    """
    if url:
        base_url, project_key, repo_slug, pr_id = _parse_pr_url(url)
        token = get_access_token()
        return base_url, token, project_key, repo_slug, pr_id
    else:
        base_url, token = get_env_vars()
        project_key, repo_slug = get_git_context()

        try:
            repo = Repo(os.getcwd(), search_parent_directories=True)
            branch = repo.active_branch.name
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] Could not determine current branch: {e}")
            raise typer.Exit(code=1)

        console.print(
            f"Looking up active PR for branch [cyan]{branch}[/cyan] "
            f"in [cyan]{project_key}/{repo_slug}[/cyan]..."
        )

        try:
            pr_data = _find_pr_for_branch(base_url, token, project_key, repo_slug, branch)
        except requests.exceptions.RequestException as e:
            console.print(f"[bold red]Error fetching PRs:[/bold red] {e}")
            raise typer.Exit(code=1)

        if not pr_data:
            console.print(f"[yellow]No open pull request found for branch '{branch}'.[/yellow]")
            raise typer.Exit(code=0)

        pr_id = str(pr_data.get("id"))
        return base_url, token, project_key, repo_slug, pr_id


# ---------------------------------------------------------------------------
# pr comment – post a general comment on a pull request
# ---------------------------------------------------------------------------

@app.command()
def pr_comment(
    text: str = typer.Argument(..., help="Comment text to post on the pull request"),
    url: str = typer.Option(
        None, "--url", "-u",
        help="Stash PR URL (auto-detected from current branch when omitted)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print API call details without executing"),
):
    """Post a general comment on a Pull Request."""
    base_url, token, project_key, repo_slug, pr_id = _resolve_pr_context(url)

    api_url = (
        f"{base_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}"
        f"/pull-requests/{pr_id}/comments"
    )
    headers = {
        "Authorization": f"Bearer {token.get()}",
        "Content-Type": "application/json",
    }
    payload = {"text": text}

    if dry_run:
        safe_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        print_api_call("POST", api_url, headers=safe_headers, payload=payload)
        return

    try:
        verify = get_ssl_verify()
        response = requests.post(api_url, headers=headers, json=payload, timeout=10, verify=verify)
        response.raise_for_status()
        comment_data = response.json()
        comment_id = comment_data.get("id")

        console.print(f"[bold green]✓[/bold green] Comment posted successfully!")
        console.print(f"  PR: [cyan]{project_key}/{repo_slug}#{pr_id}[/cyan]")
        console.print(f"  Comment ID: [cyan]{comment_id}[/cyan]")
        console.print(f"  Text: {escape(text)}")
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Error posting comment:[/bold red] {e}")
        if hasattr(e, "response") and e.response is not None:
            console.print(f"Status: {e.response.status_code}")
            try:
                err_data = e.response.json()
                for err in err_data.get("errors", []):
                    console.print(f"[red]{err.get('message')}[/red]")
            except Exception:
                pass
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# pr add-reviewer / pr remove-reviewer – reviewer management
# ---------------------------------------------------------------------------

@app.command()
def pr_add_reviewer(
    usernames: list[str] = typer.Argument(..., help="Reviewer username(s) to add"),
    url: str = typer.Option(
        None, "--url", "-u",
        help="Stash PR URL (auto-detected from current branch when omitted)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print API call details without executing"),
):
    """Add one or more reviewers to a Pull Request."""
    base_url, token, project_key, repo_slug, pr_id = _resolve_pr_context(url)

    participants_url = (
        f"{base_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}"
        f"/pull-requests/{pr_id}/participants"
    )
    headers = {
        "Authorization": f"Bearer {token.get()}",
        "Content-Type": "application/json",
    }

    if dry_run:
        safe_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        for username in usernames:
            payload = {"user": {"name": username}, "role": "REVIEWER"}
            print_api_call("POST", participants_url, headers=safe_headers, payload=payload)
        return

    verify = get_ssl_verify()
    added = []
    failed = []

    for username in usernames:
        payload = {"user": {"name": username}, "role": "REVIEWER"}
        try:
            response = requests.post(
                participants_url, headers=headers, json=payload, timeout=10, verify=verify
            )
            response.raise_for_status()
            added.append(username)
        except requests.exceptions.RequestException as e:
            status = ""
            msg = ""
            if hasattr(e, "response") and e.response is not None:
                status = f" (HTTP {e.response.status_code})"
                try:
                    err_data = e.response.json()
                    msgs = [err.get("message", "") for err in err_data.get("errors", [])]
                    msg = ": " + "; ".join(msgs) if msgs else ""
                except Exception:
                    pass
            failed.append((username, f"{e}{status}{msg}"))

    if added:
        console.print(f"[bold green]✓[/bold green] Added reviewer(s) to PR [cyan]{project_key}/{repo_slug}#{pr_id}[/cyan]:")
        for u in added:
            console.print(f"  [green]+[/green] {u}")
    if failed:
        for username, reason in failed:
            console.print(f"[bold red]✗[/bold red] Failed to add [yellow]{username}[/yellow]: {reason}")
        raise typer.Exit(code=1)


@app.command()
def pr_remove_reviewer(
    username: str = typer.Argument(..., help="Reviewer username to remove"),
    url: str = typer.Option(
        None, "--url", "-u",
        help="Stash PR URL (auto-detected from current branch when omitted)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print API call details without executing"),
):
    """Remove a reviewer from a Pull Request."""
    base_url, token, project_key, repo_slug, pr_id = _resolve_pr_context(url)

    participant_url = (
        f"{base_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}"
        f"/pull-requests/{pr_id}/participants/{username}"
    )
    headers = {"Authorization": f"Bearer {token.get()}"}

    if dry_run:
        safe_headers = {"Authorization": f"Bearer {token}"}
        print_api_call("DELETE", participant_url, headers=safe_headers)
        return

    try:
        verify = get_ssl_verify()
        response = requests.delete(participant_url, headers=headers, timeout=10, verify=verify)
        response.raise_for_status()

        console.print(f"[bold green]✓[/bold green] Removed reviewer [yellow]{username}[/yellow] from PR [cyan]{project_key}/{repo_slug}#{pr_id}[/cyan]")
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Error removing reviewer:[/bold red] {e}")
        if hasattr(e, "response") and e.response is not None:
            console.print(f"Status: {e.response.status_code}")
            try:
                err_data = e.response.json()
                for err in err_data.get("errors", []):
                    console.print(f"[red]{err.get('message')}[/red]")
            except Exception:
                pass
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
