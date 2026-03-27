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
@click.argument("repo_path", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Force full re-index")
@click.option("--skip-wiki", is_flag=True, help="Skip wiki generation")
@click.option("--skip-embed", is_flag=True, help="Skip embedding generation")
def analyze(repo_path, force, skip_wiki, skip_embed):
    """Index a repository (parse symbols, build graph, generate docs)."""
    from reposage.indexer.pipeline import IndexPipeline
    repo = Path(repo_path).resolve()
    console.print(f"[bold green]Analyzing[/bold green] {repo}")
    pipeline = IndexPipeline(repo)
    pipeline.run(force=force, skip_wiki=skip_wiki, skip_embed=skip_embed)


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
def watch(repo_path):
    """Watch a repository for changes and incrementally update the index."""
    from reposage.watcher.monitor import start_watcher
    repo = Path(repo_path).resolve()
    console.print(f"[bold blue]Watching[/bold blue] {repo}")
    start_watcher(repo)


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Force regeneration of all wiki pages")
def wiki(repo_path, force):
    """Generate or update the Markdown wiki for a repository."""
    from reposage.generator.wiki import WikiGenerator
    repo = Path(repo_path).resolve()
    console.print(f"[bold yellow]Generating wiki[/bold yellow] for {repo}")
    gen = WikiGenerator(repo)
    gen.generate(force=force)


@cli.command()
@click.option("--repo", required=True, type=click.Path(exists=True), help="Repository path")
def mcp(repo):
    """Start the MCP server (stdio) for a repository."""
    import asyncio
    from reposage.mcp.server import start_mcp_server
    repo_path = Path(repo).resolve()
    asyncio.run(start_mcp_server(repo_path))


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
    repo = Path(repo_path).resolve()
    db_path = repo / ".reposage" / "index.db"
    if not db_path.exists():
        console.print("[red]Not indexed yet.[/red] Run: reposage analyze <repo>")
        return
    db = RepoSageDB(db_path)
    stats = db.get_stats()
    console.print(f"[bold]Repository:[/bold] {repo.name}")
    console.print(f"  Symbols:   {stats['symbols']}")
    console.print(f"  Relations: {stats['relations']}")
    console.print(f"  Modules:   {stats['modules']}")
    console.print(f"  Files:     {stats['files']}")
    console.print(f"  Indexed:   {stats.get('last_indexed', 'unknown')}")


if __name__ == "__main__":
    cli()
