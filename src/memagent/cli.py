from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from memagent.agents import (
    build_agents_doctor_report,
    build_agents_install_plan,
    build_agents_snippet,
    render_agents_install_report,
    write_agents_install_plan,
)
from memagent.context import detect_context
from memagent.memory import MemoryStore
from memagent.wrapper import build_augmented_prompt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memagent",
        description="Local workflow memory for Codex and other coding agents.",
    )
    parser.add_argument(
        "--home",
        help="Override memory home directory. Defaults to MEMAGENT_HOME or ~/.memagent.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    remember = subparsers.add_parser("remember", help="Write a memory card from text.")
    remember.add_argument("text", help="Lesson, workflow note, or pitfall to remember.")
    remember.add_argument("--topic", help="Short memory topic.")
    remember.add_argument(
        "--domain",
        help="Memory domain. Defaults to coding. Examples: coding, learning, life.",
    )
    remember.add_argument(
        "--kind",
        help="Memory kind. Defaults to note. Examples: tool_recipe, skill_route, pitfall.",
    )
    remember.add_argument("--repo", help="Repository scope.")
    remember.add_argument("--module", help="Module or subsystem scope.")
    remember.add_argument(
        "--trigger",
        action="append",
        default=[],
        help="Keyword that should recall this memory. Can be repeated.",
    )
    remember.add_argument(
        "--exportable",
        action="store_true",
        help="Mark this memory as exportable. Default is local/internal only.",
    )

    recall = subparsers.add_parser("recall", help="Recall relevant memory cards.")
    recall.add_argument("query", help="Natural-language task or question.")
    recall.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of memory cards to inspect. Default: 5.",
    )
    recall.add_argument(
        "--max-lines",
        type=int,
        default=12,
        help="Maximum lines in the composed recall context. Default: 12.",
    )
    recall.add_argument(
        "--show-sources",
        action="store_true",
        help="Include matching memory card file names.",
    )
    recall.add_argument(
        "--show-reasons",
        action="store_true",
        help="Include simple recall score and matched query terms.",
    )

    codex = subparsers.add_parser(
        "codex",
        help="Start Codex with recalled MemAgent context prepended to the prompt.",
    )
    codex.add_argument("prompt", help="Prompt to pass to Codex.")
    codex.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of memory cards to inspect. Default: 5.",
    )
    codex.add_argument(
        "--max-lines",
        type=int,
        default=12,
        help="Maximum lines in the composed recall context. Default: 12.",
    )
    codex.add_argument(
        "--show-sources",
        action="store_true",
        help="Include matching memory card file names in the Codex prompt.",
    )
    codex.add_argument(
        "--show-reasons",
        action="store_true",
        help="Include simple recall score and matched query terms in the Codex prompt.",
    )
    codex.add_argument(
        "--no-memory",
        action="store_true",
        help="Pass the prompt to Codex without recalling memories.",
    )
    codex.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the final prompt instead of starting Codex.",
    )
    codex.add_argument(
        "--codex-bin",
        default="codex",
        help="Codex executable to run. Default: codex.",
    )
    codex.add_argument(
        "codex_args",
        nargs=argparse.REMAINDER,
        help="Extra Codex CLI arguments after --, for example: -- --model gpt-5.4",
    )

    snippet = subparsers.add_parser(
        "agents-snippet",
        help="Print AGENTS.md instructions for natural-language MemAgent triggers.",
    )
    snippet.add_argument(
        "--memagent-root",
        help="MemAgent project root. Defaults to the installed package root.",
    )

    doctor = subparsers.add_parser(
        "agents-doctor",
        help="Check whether the current project AGENTS.md is wired to MemAgent.",
    )
    doctor.add_argument(
        "--cwd",
        help="Project directory to inspect. Defaults to the current working directory.",
    )
    doctor.add_argument(
        "--memagent-root",
        help="MemAgent project root. Defaults to the installed package root.",
    )

    install = subparsers.add_parser(
        "agents-install",
        help="Preview or write MemAgent instructions into an AGENTS.md file.",
    )
    install.add_argument(
        "--cwd",
        help="Project directory to inspect. Defaults to the current working directory.",
    )
    install.add_argument(
        "--target",
        help="AGENTS.md path to update. Defaults to <cwd>/AGENTS.md.",
    )
    install.add_argument(
        "--memagent-root",
        help="MemAgent project root. Defaults to the installed package root.",
    )
    install.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace an existing unmarked MemAgent section.",
    )
    install.add_argument(
        "--write",
        action="store_true",
        help="Write the planned AGENTS.md change. Default is dry-run preview.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "agents-snippet":
        print(build_agents_snippet(Path(args.memagent_root) if args.memagent_root else None))
        return 0

    store = MemoryStore.from_home_arg(args.home)

    if args.command == "agents-doctor":
        context = detect_context(Path(args.cwd) if args.cwd else None)
        print(
            build_agents_doctor_report(
                context=context,
                memory_home=store.home,
                memory_count=store.count_memory_cards(),
                memagent_root=Path(args.memagent_root) if args.memagent_root else None,
            )
        )
        return 0

    if args.command == "agents-install":
        context = detect_context(Path(args.cwd) if args.cwd else None)
        plan = build_agents_install_plan(
            context=context,
            target=Path(args.target) if args.target else None,
            memagent_root=Path(args.memagent_root) if args.memagent_root else None,
            replace_existing=args.replace_existing,
        )
        if args.write:
            write_agents_install_plan(plan)
        print(render_agents_install_report(plan, write=args.write))
        return 1 if plan.blocked and args.write else 0

    if args.command == "remember":
        context = detect_context()
        try:
            card = store.remember(
                text=args.text,
                topic=args.topic,
                domain=args.domain,
                kind=args.kind,
                repo=args.repo or context.repo_name,
                module=args.module,
                triggers=args.trigger,
                exportable=args.exportable,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(f"Saved memory: {card.path}")
        return 0

    if args.command == "recall":
        context = detect_context()
        matches = store.recall(args.query, context=context, limit=args.limit)
        rendered = store.compose_context(
            query=args.query,
            context=context,
            matches=matches,
            max_lines=args.max_lines,
            show_sources=args.show_sources,
            show_reasons=args.show_reasons,
        )
        print(rendered)
        return 0

    if args.command == "codex":
        context = detect_context()
        matches = [] if args.no_memory else store.recall(args.prompt, context=context, limit=args.limit)
        recalled_context = ""
        if not args.no_memory and matches:
            recalled_context = store.compose_context(
                query=args.prompt,
                context=context,
                matches=matches,
                max_lines=args.max_lines,
                show_sources=args.show_sources,
                show_reasons=args.show_reasons,
            )
        final_prompt = build_augmented_prompt(args.prompt, recalled_context)
        if args.dry_run:
            print(final_prompt)
            return 0
        cmd = [args.codex_bin, *normalize_remainder(args.codex_args), final_prompt]
        return subprocess.run(cmd, check=False).returncode

    parser.error(f"unknown command: {args.command}")
    return 2


def normalize_remainder(items: list[str]) -> list[str]:
    if items and items[0] == "--":
        return items[1:]
    return items


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
