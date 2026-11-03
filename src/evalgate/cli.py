"""The ``evalgate`` command-line interface.

Exit codes: 0 pass (or NO_BASELINE), 1 gate failed, 2 config/usage error,
3 provider/cassette error.
"""

from __future__ import annotations

import os
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn
from rich.table import Table

from evalgate import __version__
from evalgate.config import DEFAULT_CONFIG_NAME, EvalGateConfig, Mode, load_config
from evalgate.errors import EvalGateError, ExitCode, UsageError
from evalgate.gate import GateResult, evaluate_gate
from evalgate.reports import ReportFormat, render, render_terminal
from evalgate.results import RunResult
from evalgate.runner import run_sync
from evalgate.scaffold import write_scaffold
from evalgate.store import (
    latest_run_path,
    load_baseline,
    load_run,
    save_run,
    update_baseline,
)
from evalgate.validate import validate_project

out = Console(soft_wrap=True)
err = Console(stderr=True, soft_wrap=True)

app = typer.Typer(
    name="evalgate",
    help="EvalGate: a regression gate for LLM features. Unit tests, but for LLM behaviour.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
baseline_app = typer.Typer(help="Manage the stored baseline.", no_args_is_help=True)
app.add_typer(baseline_app, name="baseline")

T = TypeVar("T")
MODES: tuple[Mode, ...] = ("replay", "record", "live")


@dataclass
class State:
    config: Path | None = None
    mode: Mode | None = None
    verbose: bool = False


ConfigOpt = Annotated[
    Path | None,
    typer.Option(
        "--config", "-c", help=f"Path to the config file [default: {DEFAULT_CONFIG_NAME}]."
    ),
]
ModeOpt = Annotated[
    str | None,
    typer.Option(
        "--mode",
        "-m",
        help="replay (default: serve cassettes), record (call + save), live (call provider).",
        show_default=False,
    ),
]
VerboseOpt = Annotated[
    bool, typer.Option("--verbose", "-v", help="More detail, tracebacks on bugs.")
]
SuiteOpt = Annotated[
    list[str] | None,
    typer.Option("--suite", "-s", help="Only this suite (repeatable)."),
]


def _version_callback(value: bool) -> None:
    if value:
        out.print(f"evalgate {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    config: ConfigOpt = None,
    mode: ModeOpt = None,
    verbose: VerboseOpt = False,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """Global options apply to every command (they can also be given after the command)."""
    ctx.obj = State(config=config, mode=_parse_mode(mode), verbose=verbose)


def _parse_mode(value: str | None) -> Mode | None:
    if value is None:
        return None
    lowered = value.lower()
    for mode in MODES:
        if lowered == mode:
            return mode
    raise typer.BadParameter(
        f"must be one of: {', '.join(MODES)} (got {value!r})", param_hint="--mode"
    )


@dataclass
class Opts:
    config_path: Path
    mode: Mode
    verbose: bool


def _opts(ctx: typer.Context, config: Path | None, mode: str | None, verbose: bool) -> Opts:
    state = ctx.obj if isinstance(ctx.obj, State) else State()
    env_mode = os.environ.get("EVALGATE_MODE")
    resolved = _parse_mode(mode) or state.mode or _parse_mode(env_mode) or "replay"
    return Opts(
        config_path=config or state.config or Path(DEFAULT_CONFIG_NAME),
        mode=resolved,
        verbose=verbose or state.verbose,
    )


@contextmanager
def friendly_errors(verbose: bool) -> Iterator[None]:
    """Turn user mistakes into short, actionable messages and the right exit code."""
    try:
        yield
    except EvalGateError as exc:
        err.print(f"[bold red]{exc.title}:[/bold red] {escape(exc.message)}", highlight=False)
        if exc.hint:
            err.print(f"[yellow]Hint:[/yellow] {escape(exc.hint)}", highlight=False)
        raise typer.Exit(int(exc.exit_code)) from None
    except (typer.Exit, typer.Abort):
        raise
    except KeyboardInterrupt:
        err.print("[red]Interrupted.[/red]")
        raise typer.Exit(130) from None
    except Exception as exc:
        if verbose:
            err.print(traceback.format_exc(), highlight=False, markup=False)
        err.print(
            f"[bold red]Unexpected error:[/bold red] {escape(f'{exc.__class__.__name__}: {exc}')}",
            highlight=False,
        )
        err.print(
            "[yellow]Hint:[/yellow] re-run with --verbose for a traceback, and please open an "
            "issue at https://github.com/mourya-dasgupta/evalgate/issues"
        )
        raise typer.Exit(int(ExitCode.USAGE_ERROR)) from None


def _guarded(opts: Opts, fn: Callable[[], T]) -> T:
    with friendly_errors(opts.verbose):
        return fn()
    raise AssertionError("unreachable")  # pragma: no cover


def _execute_run(cfg: EvalGateConfig, suites: list[str] | None, opts: Opts) -> RunResult:
    selected = cfg.select_suites(suites)
    if opts.mode != "replay":
        err.print(
            f"[yellow]Mode {opts.mode}:[/yellow] real provider calls will be made"
            + (" and cassettes updated." if opts.mode == "record" else ".")
        )
    with Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=err,
        transient=True,
        disable=not err.is_terminal,
    ) as progress:
        tasks: dict[str, Any] = {}

        def on_progress(suite: str, done: int, total: int) -> None:
            if suite not in tasks:
                tasks[suite] = progress.add_task(suite, total=total)
            progress.update(tasks[suite], completed=done)

        run = run_sync(cfg, selected, opts.mode, progress=on_progress)
    path = save_run(run, cfg.runs_dir)
    if opts.verbose:
        for suite in run.suites:
            err.print(
                f"[dim]{suite.name}: {suite.metrics.total} cases, "
                f"{suite.cache_hits} cassette hits, mode {opts.mode}[/dim]"
            )
    err.print(f"[dim]Saved run to {_rel(path)}[/dim]")
    return run


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _report_provider_errors(run: RunResult) -> None:
    errored = run.errored_cases
    if not errored:
        return
    err.print(
        f"[bold red]Provider error:[/bold red] {len(errored)} case(s) could not get a model "
        "response, so the gate was not evaluated:"
    )
    for suite, case in errored[:5]:
        err.print(f"  - {suite}/{case.id}: {escape(case.error or '')}", highlight=False)
    if len(errored) > 5:
        err.print(f"  ... and {len(errored) - 5} more")
    if any("no recording" in (c.error or "") for _, c in errored):
        suites = sorted({s for s, _ in errored})
        flags = " ".join(f"--suite {s}" for s in suites)
        err.print(
            "[yellow]Hint:[/yellow] the prompt, model or params changed since the cassettes "
            f"were recorded. Re-record with: evalgate --mode record run {flags} "
            "(needs the provider API key), then commit the cassettes. See docs/runbook.md"
        )
    else:
        err.print(
            "[yellow]Hint:[/yellow] check API keys, base_url and rate limits; see docs/runbook.md"
        )
    raise typer.Exit(int(ExitCode.PROVIDER_ERROR))


def _write_reports(
    run: RunResult, gate: GateResult, targets: dict[ReportFormat, Path | None]
) -> None:
    for fmt, path in targets.items():
        if path is None:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(fmt, run, gate), encoding="utf-8")
        err.print(f"[dim]Wrote {fmt} report to {_rel(path)}[/dim]")


# -- commands ---------------------------------------------------------------------------------


@app.command()
def init(
    directory: Annotated[Path, typer.Option("--dir", help="Where to create the project.")] = Path(),
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
) -> None:
    """Scaffold evalgate.yaml, an example golden set + prompt, and a GitHub workflow."""
    written, skipped = write_scaffold(directory, force=force)
    for path in written:
        out.print(f"[green]created[/green] {_rel(path)}")
    for path in skipped:
        out.print(f"[yellow]skipped[/yellow] {_rel(path)} (exists; use --force to overwrite)")
    if written:
        out.print(
            "\nNext steps:\n"
            "  evalgate validate          # check config + golden set\n"
            "  evalgate gate              # first run: NO_BASELINE (passes with a warning)\n"
            "  evalgate baseline update   # promote that run to the baseline\n"
            "  evalgate gate              # now gated against the baseline"
        )


@app.command()
def validate(
    ctx: typer.Context,
    suite: SuiteOpt = None,
    config: ConfigOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Check the config, golden sets, templates and scorers for errors."""
    opts = _opts(ctx, config, None, verbose)

    def _do() -> bool:
        cfg = load_config(opts.config_path)
        report = validate_project(cfg, suite)
        for check in report.suites:
            status = "[green]ok[/green]" if not check.errors else "[red]invalid[/red]"
            tags = ", ".join(f"{t}={n}" for t, n in sorted(check.tags.items())) or "none"
            name = escape(check.suite)
            out.print(
                f"{status} suite [bold]{name}[/bold]: {check.cases} cases; tags: {escape(tags)}"
            )
            for e in check.errors:
                out.print(f"  [red]✗[/red] {escape(e)}", highlight=False)
            for w in check.warnings:
                out.print(f"  [yellow]![/yellow] {escape(w)}", highlight=False)
        return report.ok

    if not _guarded(opts, _do):
        raise typer.Exit(int(ExitCode.USAGE_ERROR))
    out.print("[green]Configuration is valid.[/green]")


@app.command()
def run(
    ctx: typer.Context,
    suite: SuiteOpt = None,
    config: ConfigOpt = None,
    mode: ModeOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Run all suites (or --suite NAME) and save results to .evalgate/runs/<timestamp>.json."""
    opts = _opts(ctx, config, mode, verbose)

    def _do() -> RunResult:
        cfg = load_config(opts.config_path)
        result = _execute_run(cfg, suite, opts)
        baseline = load_baseline(cfg.baseline_path)
        render_terminal(out, result, evaluate_gate(cfg, result, baseline), verbose=opts.verbose)
        return result

    result = _guarded(opts, _do)
    _report_provider_errors(result)


@app.command()
def gate(
    ctx: typer.Context,
    suite: SuiteOpt = None,
    config: ConfigOpt = None,
    mode: ModeOpt = None,
    verbose: VerboseOpt = False,
    report_md: Annotated[
        Path | None, typer.Option(help="Also write the Markdown report here.")
    ] = None,
    report_html: Annotated[
        Path | None, typer.Option(help="Also write the HTML report here.")
    ] = None,
    report_json: Annotated[
        Path | None, typer.Option(help="Also write the JSON report here.")
    ] = None,
) -> None:
    """Run, compare to the baseline, print a verdict; exit 1 if the gate fails."""
    opts = _opts(ctx, config, mode, verbose)

    def _do() -> tuple[RunResult, GateResult | None]:
        cfg = load_config(opts.config_path)
        baseline = load_baseline(cfg.baseline_path)  # fail fast on a corrupted baseline
        result = _execute_run(cfg, suite, opts)
        if result.errored_cases:
            return result, None
        verdict = evaluate_gate(cfg, result, baseline)
        render_terminal(out, result, verdict, verbose=opts.verbose)
        _write_reports(result, verdict, {"md": report_md, "html": report_html, "json": report_json})
        return result, verdict

    result, verdict = _guarded(opts, _do)
    _report_provider_errors(result)
    assert verdict is not None
    raise typer.Exit(int(verdict.exit_code))


@baseline_app.command("update")
def baseline_update(
    ctx: typer.Context,
    run_file: Annotated[
        Path | None, typer.Option("--run", help="Promote this run file instead of the latest.")
    ] = None,
    suite: SuiteOpt = None,
    config: ConfigOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Promote the latest run (or --run FILE) to the baseline (.evalgate/baseline.json)."""
    opts = _opts(ctx, config, None, verbose)

    def _do() -> None:
        cfg = load_config(opts.config_path)
        path = run_file or latest_run_path(cfg.runs_dir)
        chosen = load_run(path)
        if chosen.errored_cases:
            raise UsageError(
                f"run {chosen.run_id} has {len(chosen.errored_cases)} errored case(s) and "
                "cannot become the baseline",
                hint="fix the provider/cassette errors and run again",
            )
        promoted = update_baseline(chosen, cfg.baseline_path, suite)
        out.print(
            f"[green]Baseline updated[/green] from run {chosen.run_id} → {_rel(cfg.baseline_path)}"
        )
        for s in promoted.suites:
            m = s.metrics
            out.print(f"  {s.name}: {m.passed}/{m.total} passed ({m.pass_rate * 100:.1f}%)")
        out.print("[dim]Commit the baseline file so CI gates against it.[/dim]")

    _guarded(opts, _do)


@baseline_app.command("show")
def baseline_show(
    ctx: typer.Context,
    config: ConfigOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Show what the current baseline contains."""
    opts = _opts(ctx, config, None, verbose)

    def _do() -> None:
        cfg = load_config(opts.config_path)
        baseline = load_baseline(cfg.baseline_path)
        if baseline is None:
            raise UsageError(
                f"no baseline at {cfg.baseline_path}",
                hint="run 'evalgate run' then 'evalgate baseline update'",
            )
        table = Table(
            title=f"Baseline {baseline.run_id} ({baseline.created_at})", title_justify="left"
        )
        for col in ("Suite", "Model", "Prompt", "Cases", "Pass rate", "Score"):
            table.add_column(col)
        for s in baseline.suites:
            table.add_row(
                s.name,
                s.target.model,
                s.target.prompt,
                str(s.metrics.total),
                f"{s.metrics.pass_rate * 100:.1f}%",
                f"{s.metrics.score:.3f}",
            )
        out.print(table)

    _guarded(opts, _do)


@app.command()
def report(
    ctx: typer.Context,
    fmt: Annotated[str, typer.Option("--format", "-f", help="md | html | json")] = "md",
    run_file: Annotated[
        Path | None, typer.Option("--run", help="Render this run instead of the latest.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write to a file instead of stdout.")
    ] = None,
    config: ConfigOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Render the last run (compared to the baseline, if any) as Markdown, HTML or JSON."""
    opts = _opts(ctx, config, None, verbose)
    if fmt not in ("md", "html", "json"):
        raise typer.BadParameter(f"must be md, html or json (got {fmt!r})", param_hint="--format")
    report_format: Literal["md", "html", "json"] = fmt  # type: ignore[assignment]

    def _do() -> None:
        cfg = load_config(opts.config_path)
        current = load_run(run_file or latest_run_path(cfg.runs_dir))
        baseline = load_baseline(cfg.baseline_path)
        if baseline is not None and baseline.run_id == current.run_id:
            err.print("[dim]Note: this run is the baseline itself, so deltas are zero.[/dim]")
        verdict = evaluate_gate(cfg, current, baseline)
        text = render(report_format, current, verdict)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding="utf-8")
            err.print(f"[dim]Wrote {report_format} report to {_rel(output)}[/dim]")
        else:
            typer.echo(text, nl=False)

    _guarded(opts, _do)


def main() -> None:
    app()
