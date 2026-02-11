import os
import sys
import re
import json
import typer
import requests
import urllib3
from git import Repo, InvalidGitRepositoryError
from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax

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
    # token = os.environ.get("STASH_ACCESS_TOKEN")
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

if __name__ == "__main__":
    app()
