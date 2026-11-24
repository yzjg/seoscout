#!/usr/bin/env python3
"""
Step 5: One-keyword-one-page check.

Every keyword must map to exactly one non-empty English MDX at the path generate
writes it to (articles/en/<category>/<slug>.mdx), with no extra pages; every target
language must have exactly the same set of pages as English.
Bare MDX braces / `<` left in any page (e.g. articles written before generate
escaped them) are escaped in place first; anything still unsafe fails the check.
Writes logs/page_check.json and returns True only when every check passes.
"""

import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List

from .core.config import Config
from .core.mdx import escape_mdx_body, find_mdx_issues
from .core.utils import load_keywords_from_json
from .generate import keyword_to_filename, keyword_to_slug


def _expected_relpath(keyword: str, category: str) -> str:
    """Same path rule as generate.run_generate."""
    slug = keyword_to_slug(keyword)
    if category:
        return f"{category.lower().replace(' ', '-')}/{slug}.mdx"
    return f"{slug}.mdx"


def _mdx_set(lang_dir: Path) -> set:
    if not lang_dir.exists():
        return set()
    return {str(p.relative_to(lang_dir)) for p in lang_dir.glob("**/*.mdx")}


def _is_empty(path: Path) -> bool:
    try:
        return not path.read_text(encoding='utf-8').strip()
    except OSError:
        return True


def run_check(project: str, keywords_file: str, languages: List[str] = None) -> bool:
    Config.init(project)
    languages = [l for l in (languages or []) if l and l != 'en']
    articles_root = Path(Config.DATA_DIR) / "articles"
    en_dir = articles_root / "en"
    collected_dir = Path(Config.OUT_DIR) / "collected"

    print("=" * 70)
    print(f"  Step 5: One-keyword-one-page check [{project}]")
    print("=" * 70)

    entries = load_keywords_from_json(keywords_file)
    errors = []
    report = {
        "checked_at": datetime.now().isoformat(timespec='seconds'),
        "keywords_file": os.path.abspath(keywords_file),
        "articles_dir": str(articles_root),
        "keyword_count": len(entries),
        "languages": languages,
    }

    if not entries:
        errors.append("no keywords found in keywords file")

    # 1. duplicate keywords (case / surrounding spaces ignored) and path collisions
    by_norm, by_path = defaultdict(list), defaultdict(list)
    for e in entries:
        by_norm[e['keyword'].strip().lower()].append(e['keyword'])
        by_path[_expected_relpath(e['keyword'], e['category'])].append(e['keyword'])
    duplicates = [v for v in by_norm.values() if len(v) > 1]
    collisions = {p: v for p, v in by_path.items() if len(set(k.lower() for k in v)) > 1}
    if duplicates:
        errors.append(f"duplicate keywords: {duplicates}")
    if collisions:
        errors.append(f"different keywords map to the same page: {collisions}")

    # 2. every keyword has one non-empty English page
    expected = set(by_path)
    actual_en = _mdx_set(en_dir)
    missing = []
    for e in entries:
        rel = _expected_relpath(e['keyword'], e['category'])
        path = en_dir / rel
        if rel in actual_en and not _is_empty(path):
            continue
        cat = e['category'].lower().replace(' ', '-') if e['category'] else ''
        fname = keyword_to_filename(e['keyword']) + ".json"
        has_data = (collected_dir / cat / fname).exists() or (collected_dir / fname).exists()
        reason = "empty file" if rel in actual_en else (
            "not generated" if has_data else "no collected material (search/collect found nothing)")
        missing.append({"keyword": e['keyword'], "expected": str(path), "reason": reason})
    if missing:
        errors.append(f"{len(missing)} keywords have no valid English page")

    # 3. no English page without a keyword
    extra_en = sorted(actual_en - expected)
    if extra_en:
        errors.append(f"{len(extra_en)} English pages do not match any keyword")

    # 4. translations mirror English exactly
    lang_report = {}
    for lang in languages:
        actual = _mdx_set(articles_root / lang)
        lang_missing = sorted(actual_en - actual)
        lang_extra = sorted(actual - actual_en)
        lang_report[lang] = {"count": len(actual), "missing": lang_missing, "extra": lang_extra}
        if lang_missing or lang_extra or len(actual) != len(actual_en):
            errors.append(f"[{lang}] {len(actual)} pages vs {len(actual_en)} English "
                          f"(missing {len(lang_missing)}, extra {len(lang_extra)})")

    # 5. MDX body safety: escape legacy pages in place, then re-check every page
    mdx_escaped, mdx_issues = [], []
    for lang in ['en'] + languages:
        for f in sorted((articles_root / lang).glob("**/*.mdx")):
            text = f.read_text(encoding='utf-8')
            fixed = escape_mdx_body(text)
            if fixed != text:
                f.write_text(fixed, encoding='utf-8')
                mdx_escaped.append(f"{lang}/{f.relative_to(articles_root / lang)}")
            mdx_issues += [f"{lang}/{f.relative_to(articles_root / lang)}:{n}" for n in find_mdx_issues(fixed)]
    if mdx_issues:
        errors.append(f"{len(mdx_issues)} lines still have bare MDX braces or '<'")

    report.update({
        "en_count": len(actual_en),
        "duplicates": duplicates,
        "collisions": collisions,
        "missing_en": missing,
        "extra_en": extra_en,
        "translations": lang_report,
        "mdx_escaped": mdx_escaped,
        "mdx_issues": mdx_issues,
        "passed": not errors,
        "errors": errors,
    })
    report_path = Path(Config.LOG_DIR) / "page_check.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f"  Keywords:        {len(entries)}")
    print(f"  English pages:   {len(actual_en)}")
    for lang, r in lang_report.items():
        print(f"  [{lang}] pages:      {r['count']}")
    for m in missing[:20]:
        print(f"  ❌ missing  {m['keyword']} — {m['reason']}")
    for x in extra_en[:20]:
        print(f"  ❌ extra    en/{x}")
    if mdx_escaped:
        print(f"  🔧 escaped bare MDX braces / '<' in {len(mdx_escaped)} pages")
    for x in mdx_issues[:20]:
        print(f"  ❌ mdx      {x}")
    for err in errors:
        print(f"  ❌ {err}")
    print(f"  {'✅ PASSED' if not errors else '❌ FAILED'} — report: {report_path}")
    print("=" * 70)
    return not errors
