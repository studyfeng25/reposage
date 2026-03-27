"""CLI entry point for RepoSage."""
import click
from pathlib import Path
from rich.console import Console

console = Console()


@click.group()
@click.version_option()
def cli():
    """RepoSage — Code intelligence for ObjC/Swift/Java repos."""
    pass


@cli.command()
@click.argument("repo_paths", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Force full re-index")
@click.option("--skip-wiki", is_flag=True, help="Skip wiki generation")
@click.option("--skip-embed", is_flag=True, help="Skip embedding generation")
def analyze(repo_paths, force, skip_wiki, skip_embed):
    """Index one or more repositories."""
    from reposage.indexer.pipeline import IndexPipeline
    repos = [Path(p).resolve() for p in repo_paths]
    for repo in repos:
        if len(repos) > 1:
            console.print(f"\n[bold green]Analyzing[/bold green] {repo.name} ({repo})")
        else:
            console.print(f"[bold green]Analyzing[/bold green] {repo}")
        pipeline = IndexPipeline(repo)
        pipeline.run(force=force, skip_wiki=skip_wiki, skip_embed=skip_embed)


@cli.command()
@click.argument("repo_paths", nargs=-1, required=True, type=click.Path(exists=True))
def watch(repo_paths):
    """Watch one or more repositories for changes and incrementally update the index."""
    import threading
    from reposage.watcher.monitor import start_watcher
    repos = [Path(p).resolve() for p in repo_paths]
    if len(repos) == 1:
        console.print(f"[bold blue]Watching[/bold blue] {repos[0]}")
        start_watcher(repos[0])
    else:
        threads = []
        for repo in repos:
            console.print(f"[bold blue]Watching[/bold blue] {repo.name}")
            t = threading.Thread(target=start_watcher, args=(repo,), daemon=True)
            t.start()
            threads.append(t)
        console.print(f"[bold blue]Watching {len(repos)} repos[/bold blue] — Ctrl+C to stop")
        try:
            for t in threads:
                t.join()
        except KeyboardInterrupt:
            pass


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Force regeneration of all wiki pages")
def wiki(repo_path, force):
    """Generate fallback wiki stubs (symbol listings) for a repository.

    Full LLM-generated docs are produced by your AI agent via the MCP tools
    get_pending_wiki / write_wiki — no API key required.
    """
    from reposage.generator.wiki import WikiGenerator
    repo = Path(repo_path).resolve()
    console.print(f"[bold yellow]Generating wiki stubs[/bold yellow] for {repo}")
    gen = WikiGenerator(repo)
    gen.generate(force=force)


@cli.command()
@click.option("--repo", multiple=True, type=click.Path(exists=True),
              help="Repository path (can be specified multiple times)")
@click.option("--repos-dir", type=click.Path(exists=True),
              help="Directory to scan for indexed repos (subdirs with .reposage/index.db)")
def mcp(repo, repos_dir):
    """Start the MCP server (stdio) for one or more repositories."""
    import asyncio
    from reposage.mcp.server import start_mcp_server

    repos: dict = {}

    # Collect from --repos-dir: find RepoSage-* sibling dirs
    if repos_dir:
        base = Path(repos_dir).resolve()
        for subdir in sorted(base.iterdir()):
            if (subdir.is_dir()
                    and subdir.name.startswith("RepoSage-")
                    and (subdir / "index.db").exists()):
                repo_name = subdir.name[len("RepoSage-"):]
                repo_path = base / repo_name
                if repo_path.exists():
                    repos[repo_name] = repo_path

    # Collect from --repo
    for r in repo:
        p = Path(r).resolve()
        repos[p.name] = p

    if not repos:
        console.print("[red]No indexed repositories found.[/red] "
                      "Run: reposage analyze <repo_path>")
        return

    console.print(f"[bold]RepoSage MCP[/bold] — serving {len(repos)} repo(s): "
                  + ", ".join(repos.keys()))
    asyncio.run(start_mcp_server(repos))


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
@click.option("--port", default=8080, help="Port for the web server")
def serve(repo_path, port):
    """Start the web UI server."""
    import uvicorn
    from reposage.web.app import create_app
    repo = Path(repo_path).resolve()
    app = create_app(repo)
    uvicorn.run(app, host="0.0.0.0", port=port)


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
def status(repo_path):
    """Show index status for a repository."""
    from reposage.storage.db import RepoSageDB
    from reposage.indexer.pipeline import get_reposage_dir
    repo = Path(repo_path).resolve()
    reposage_dir = get_reposage_dir(repo)
    db_path = reposage_dir / "index.db"
    if not db_path.exists():
        console.print("[red]Not indexed yet.[/red] Run: reposage analyze <repo>")
        console.print(f"  (looking for index at: {db_path})")
        return
    db = RepoSageDB(db_path)
    stats = db.get_stats()
    console.print(f"[bold]Repository:[/bold] {repo.name}")
    console.print(f"  Index dir: {reposage_dir}")
    console.print(f"  Symbols:   {stats['symbols']}")
    console.print(f"  Relations: {stats['relations']}")
    console.print(f"  Modules:   {stats['modules']}")
    console.print(f"  Files:     {stats['files']}")
    console.print(f"  Indexed:   {stats.get('last_indexed', 'unknown')}")


if __name__ == "__main__":
    cli()
