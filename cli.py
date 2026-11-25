#!/usr/bin/env python3
"""
seoscout CLI — unified entry point.

Usage:
    seoscout search --keywords FILE
    seoscout collect --keywords FILE
    seoscout generate --keywords FILE [--prompt FILE] [--overwrite] [--test]
    seoscout translate --keywords FILE --lang es,pt,de [--prompt FILE] [--overwrite] [--test]
    seoscout run --keywords FILE [--languages-file languages.json]
    seoscout check --keywords FILE [--lang es,pt | --languages-file languages.json]

Translation languages: --lang > --languages-file > 'languages' in the keywords JSON.
'en' is the source language and is always ignored as a translation target.

Every command accepts --output-dir DIR: use DIR as the project directory
(DIR/articles/en/..., DIR/out/..., DIR/logs/...) instead of OUTPUT_DIR/<project>.
run / generate / translate end with the one-keyword-one-page check (skipped with --test)
and exit 1 when it fails.
"""

import asyncio
import argparse
import json
import os
import sys

from . import __version__


def _derive_project(keywords_file: str) -> str:
    """Derive project name from topic_name in JSON, or fall back to filename."""
    try:
        with open(keywords_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        topic = data.get('topic_name', '').strip()
        if topic:
            return topic.replace(' ', '_').lower()
    except Exception:
        pass
    base = os.path.splitext(os.path.basename(keywords_file))[0]
    return base.replace(' ', '_').lower()


def main():
    parser = argparse.ArgumentParser(
        prog="seoscout",
        description="Keyword research, content collection, article generation & translation CLI for SEO"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── search ──
    search_parser = subparsers.add_parser(
        "search",
        help="Search keywords on YouTube and Google → search_results.json"
    )
    search_parser.add_argument(
        "--keywords", "-k", required=True,
        help="Path to keywords JSON file"
    )

    # ── collect ──
    collect_parser = subparsers.add_parser(
        "collect",
        help="Collect YouTube transcripts and web content from search results"
    )
    collect_parser.add_argument(
        "--project", "-p",
        help="Project name (auto-derived from keywords file if not set)"
    )
    collect_parser.add_argument(
        "--keywords", "-k",
        help="Keywords JSON file (used to derive project name if --project not set)"
    )

    # ── generate ──
    gen_parser = subparsers.add_parser(
        "generate",
        help="Generate Markdown articles from collected material using LLM"
    )
    gen_parser.add_argument(
        "--keywords", "-k", required=True,
        help="Path to keywords JSON file"
    )
    gen_parser.add_argument(
        "--prompt",
        help="Path to custom prompt template (default: built-in)"
    )
    gen_parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing articles"
    )
    gen_parser.add_argument(
        "--test", action="store_true",
        help="Test mode: only generate 2 articles"
    )

    # ── translate ──
    trans_parser = subparsers.add_parser(
        "translate",
        help="Translate English articles to other languages using LLM"
    )
    trans_parser.add_argument(
        "--keywords", "-k", required=True,
        help="Path to keywords JSON file (used to derive project name)"
    )
    trans_langs = trans_parser.add_mutually_exclusive_group()
    trans_langs.add_argument(
        "--lang", "-l",
        help="Target languages, comma-separated (e.g. es,pt,de,fr,ja). If neither --lang nor --languages-file is set, reads 'languages' from keywords JSON. 'en' is always ignored."
    )
    trans_langs.add_argument(
        "--languages-file",
        help='languages.json with {"languages": ["en", "de", ...]}; "en" is ignored'
    )
    trans_parser.add_argument(
        "--prompt",
        help="Path to custom translation prompt template (default: built-in)"
    )
    trans_parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing translations"
    )
    trans_parser.add_argument(
        "--test", action="store_true",
        help="Test mode: only translate 1 article"
    )

    # ── run (search + collect + generate) ──
    run_parser = subparsers.add_parser(
        "run",
        help="Search, collect, generate (and translate if languages set) in one step"
    )
    run_parser.add_argument(
        "--keywords", "-k", required=True,
        help="Path to keywords JSON file"
    )
    run_parser.add_argument(
        "--prompt",
        help="Path to custom prompt template for generation"
    )
    run_parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing articles"
    )
    run_parser.add_argument(
        "--languages-file",
        help='languages.json with {"languages": ["en", "de", ...]}: translate into every language '
             'except "en" (default: \'languages\' field in keywords JSON)'
    )

    # ── check (one keyword = one page) ──
    check_parser = subparsers.add_parser(
        "check",
        help="Verify every keyword has exactly one English page and translations mirror English"
    )
    check_parser.add_argument(
        "--keywords", "-k", required=True,
        help="Path to keywords JSON file"
    )
    check_langs = check_parser.add_mutually_exclusive_group()
    check_langs.add_argument(
        "--lang", "-l",
        help="Languages to verify, comma-separated (default: 'languages' field in keywords JSON); 'en' is ignored"
    )
    check_langs.add_argument(
        "--languages-file",
        help='languages.json with {"languages": ["en", "de", ...]}; "en" is ignored'
    )

    for sub in (search_parser, collect_parser, gen_parser, trans_parser, run_parser, check_parser):
        sub.add_argument(
            "--output-dir", "-o",
            help="Project directory for all output (default: OUTPUT_DIR/<project> from .env)"
        )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.output_dir:
        from .core.config import Config
        Config.PROJECT_DIR_OVERRIDE = os.path.abspath(os.path.expanduser(args.output_dir))
        print(f"📂 Output dir: {Config.PROJECT_DIR_OVERRIDE}")

    # Derive project name
    if args.command in ("search", "generate", "run", "check"):
        args.project = _derive_project(args.keywords)
        print(f"📁 Project: {args.project}\n")
    elif args.command == "collect":
        if args.project:
            pass
        elif args.keywords:
            args.project = _derive_project(args.keywords)
        else:
            print("❌ Need --project or --keywords to identify project")
            sys.exit(1)
    elif args.command == "translate":
        args.project = _derive_project(args.keywords)
        print(f"📁 Project: {args.project}\n")

    # Resolve translation languages up front so a bad languages file fails before any search / LLM call
    if args.command in ("translate", "run", "check"):
        try:
            args.target_langs, args.langs_given = _resolve_langs(args)
        except ValueError as e:
            print(f"❌ {e}")
            sys.exit(2)

    ok = True
    if args.command == "search":
        asyncio.run(_run_search(args))
    elif args.command == "collect":
        asyncio.run(_run_collect(args))
    elif args.command == "generate":
        ok = asyncio.run(_run_generate(args))
    elif args.command == "translate":
        ok = asyncio.run(_run_translate(args))
    elif args.command == "run":
        ok = asyncio.run(_run_all(args))
    elif args.command == "check":
        ok = _run_check(args)
    sys.exit(0 if ok else 1)


def _split_langs(lang: str) -> list:
    return [l.strip() for l in (lang or "").split(",") if l.strip()]


def _resolve_langs(args) -> tuple:
    """Translation targets: --lang > --languages-file > 'languages' in keywords JSON.
    English (the source) is always dropped. Returns (targets, whether any languages were given)."""
    from .core.utils import load_languages_file, load_languages_from_json, target_languages
    lang = getattr(args, "lang", None)
    lang_file = getattr(args, "languages_file", None)
    if lang:
        source, langs = "--lang", _split_langs(lang)
    elif lang_file:
        source, langs = f"--languages-file {lang_file}", load_languages_file(lang_file)
    else:
        source, langs = "keywords JSON", load_languages_from_json(args.keywords)
    targets = target_languages(langs)
    if langs:
        print(f"🌐 Languages ({source}): {', '.join(langs)} → translate: {', '.join(targets) or 'none (English only)'}\n")
    return targets, bool(langs)


def _run_check(args) -> bool:
    from .verify import run_check
    return run_check(args.project, args.keywords, args.target_langs)


async def _run_search(args):
    from .search import run_search
    await run_search(args.project, args.keywords)


async def _run_collect(args):
    from .collect import run_collect
    await run_collect(args.project)


async def _run_generate(args) -> bool:
    from .generate import run_generate
    from .verify import run_check
    if not await run_generate(
        args.project,
        args.keywords,
        prompt_path=args.prompt,
        overwrite=args.overwrite,
        test=args.test,
    ):
        return False
    if args.test:
        print("  🧪 TEST MODE: one-keyword-one-page check skipped")
        return True
    return run_check(args.project, args.keywords)


async def _run_translate(args) -> bool:
    from .translate import run_translate
    from .verify import run_check

    if not args.langs_given:
        print("❌ No languages: pass --lang or --languages-file, or add 'languages' to the keywords JSON")
        sys.exit(1)
    if args.target_langs:
        await run_translate(
            args.project,
            ",".join(args.target_langs),
            prompt_path=args.prompt,
            overwrite=args.overwrite,
            test=args.test,
            keywords_file=args.keywords,
        )
    else:
        print("  ℹ️  Only English configured — nothing to translate")
    if args.test:
        print("  🧪 TEST MODE: one-keyword-one-page check skipped")
        return True
    return run_check(args.project, args.keywords, args.target_langs)


async def _run_all(args) -> bool:
    from .search import run_search
    from .collect import run_collect
    from .generate import run_generate
    from .translate import run_translate
    from .verify import run_check

    await run_search(args.project, args.keywords)
    await run_collect(args.project)
    if not await run_generate(
        args.project,
        args.keywords,
        prompt_path=args.prompt,
        overwrite=args.overwrite,
    ):
        return False

    # Translate when --languages-file or the keywords JSON lists languages other than English
    langs = args.target_langs
    if langs:
        lang_str = ",".join(langs)
        print(f"\n{'='*70}")
        print(f"  Step 4: Translate [{args.project}] → {lang_str}")
        print(f"{'='*70}")
        await run_translate(
            args.project,
            lang_str,
            prompt_path=None,
            overwrite=args.overwrite,
            keywords_file=args.keywords,
        )

    return run_check(args.project, args.keywords, langs)


if __name__ == "__main__":
    main()
