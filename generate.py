#!/usr/bin/env python3
"""
Step 3: Generate articles from collected material.

Reads collected/*.json (output from collect step), sends to LLM,
outputs MDX articles (JS export metadata) to articles/en/.
"""

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path

from .core.config import Config
from .core.llm_client import LLMClient, mdx_shape_error, body_word_count
from .core.mdx import escape_mdx_body, strip_preamble
from .core.utils import load_json, save_json, ensure_dir, source_problem
from .core.variants import build_variants, variants_block

# Extra tries for a draft that fails the checks (too short, no structure): 3 attempts in total
REPAIR_ROUNDS = 2


# ── helpers ─────────────────────────────────────────────────────

def keyword_to_slug(keyword: str) -> str:
    """'My Game beginner guide' → 'my-game-beginner-guide'"""
    return re.sub(r'[^a-z0-9-]', '', keyword.lower().replace(' ', '-'))


def keyword_to_filename(keyword: str) -> str:
    """'My Game beginner guide' → 'my_game_beginner_guide'"""
    return re.sub(r'[^a-z0-9_]', '', keyword.lower().replace(' ', '_'))


def load_prompt_template(prompt_path: str = None) -> str:
    """Load prompt template from file or use built-in default."""
    if prompt_path:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()

    # Built-in default
    default = Path(__file__).parent / "templates" / "generate.md"
    with open(default, 'r', encoding='utf-8') as f:
        return f.read()


def fill_template(template: str, **values) -> str:
    """Replace only {merged_data} / {current_date} / {category} / {keyword_variants}; other braces in the
    template (e.g. the `export const metadata = { ... }` example) stay as written.
    str.format() would treat those braces as fields and raise KeyError."""
    pattern = re.compile(r"\{(" + "|".join(map(re.escape, values)) + r")\}")
    # single pass: inserted material is never scanned for placeholders again
    return pattern.sub(lambda m: str(values[m.group(1)]), template)


def clean_llm_output(content: str) -> str:
    """Drop any preamble before the metadata, strip code fences, trim, and escape bare MDX braces / `<` in the body."""
    content = strip_preamble(content.strip())
    if content.startswith('```markdown'):
        content = content[len('```markdown'):].lstrip('\n')
    elif content.startswith('```md'):
        content = content[len('```md'):].lstrip('\n')
    elif content.startswith('```'):
        content = content[3:].lstrip('\n')
    if content.rstrip().endswith('```'):
        content = content.rstrip()[:-3].rstrip()
    return escape_mdx_body(content)


def validate_markdown(content: str, min_words: int = 0) -> tuple:
    """Gate before saving, for every channel (web answers and the LLM_PROVIDER fallback alike): the same
    strict shape rules as code_before's format check, plus the body word floor when min_words > 0.
    Returns (is_valid, error_msg); a failure goes to the repair round instead of being saved."""
    if not content or not content.strip():
        return False, "Empty content"
    err = mdx_shape_error(content, min_words=min_words)
    return (not err), err


# ── main logic ──────────────────────────────────────────────────

async def run_generate(
    project: str,
    keywords_file: str,
    prompt_path: str = None,
    overwrite: bool = False,
    test: bool = False,
):
    """Generate articles from collected material."""
    Config.init(project)

    print("=" * 70)
    print(f"  Step 3: Generate [{project}]")
    print("=" * 70)

    # Load prompt template
    prompt_template = load_prompt_template(prompt_path)
    print(f"  📝 Prompt template loaded ({len(prompt_template)} chars)\n")

    # Load keywords with categories from search_results.json
    search_results_path = f"{Config.OUT_DIR}/search_results.json"
    try:
        with open(search_results_path, 'r', encoding='utf-8') as f:
            sr_data = json.load(f)
        keyword_entries = []
        for kw in sr_data.get('keywords', []):
            keyword_entries.append({
                'keyword': kw['keyword'],
                'category': kw.get('category', ''),
            })
    except FileNotFoundError:
        # Fallback: load from keywords file directly
        try:
            with open(keywords_file, 'r', encoding='utf-8') as f:
                kw_data = json.load(f)
        except FileNotFoundError:
            print(f"  ❌ Keywords file not found: {keywords_file}")
            return False

        keyword_entries = []
        if 'categories' in kw_data:
            for cat in kw_data['categories']:
                for kw in cat.get('keywords', []):
                    keyword_entries.append({'keyword': kw.strip(), 'category': cat.get('category', '')})
        else:
            for kw in kw_data.get('keywords', []):
                keyword_entries.append({'keyword': kw.strip(), 'category': ''})

    if not keyword_entries:
        print("  ❌ No keywords found")
        return False

    # Search variants (spelling / plural / word order / synonyms) per keyword, from the raw
    # long-tail files next to the keywords JSON; raises if claude -p fails (no made-up variants)
    meta_dir = os.path.dirname(os.path.abspath(keywords_file))
    try:
        topic = load_json(keywords_file).get('topic_name', '')
    except (OSError, ValueError, AttributeError):
        topic = ''
    variants = build_variants(
        meta_dir, keyword_entries, topic or os.path.basename(meta_dir),
        raw_dir=f"{Config.OUT_DIR}/cache/variants-claude-p",
        template_path=str(Path(__file__).parent / "templates" / "keyword-variants.md"))

    if test:
        keyword_entries = keyword_entries[:2]
        print(f"  🧪 TEST MODE: {len(keyword_entries)} keywords\n")

    # Load collected material for each keyword
    collected_dir = f"{Config.OUT_DIR}/collected"
    articles_dir = f"{Config.DATA_DIR}/articles/en"
    ensure_dir(articles_dir)

    prompts = []
    no_material = []   # (keyword, 原因)：没有可用资料的关键词，一个都不生成，整步报错
    skipped_exists = 0

    for entry in keyword_entries:
        keyword = entry['keyword']
        category = entry.get('category', '')
        slug = keyword_to_slug(keyword)
        fname = keyword_to_filename(keyword)

        # Look for collected file in category subdir or flat
        if category:
            cat_slug = category.lower().replace(' ', '-')
            collected_path = f"{collected_dir}/{cat_slug}/{fname}.json"
            if not os.path.exists(collected_path):
                collected_path = f"{collected_dir}/{fname}.json"
            output_path = f"{articles_dir}/{cat_slug}/{slug}.mdx"
        else:
            collected_path = f"{collected_dir}/{fname}.json"
            output_path = f"{articles_dir}/{slug}.mdx"

        if os.path.exists(output_path) and not overwrite:
            skipped_exists += 1
            continue

        if not os.path.exists(collected_path):
            no_material.append((keyword, "没有资料包（collect 没抓到任何来源）"))
            continue

        # Load collected content; 旧资料包里可能存着拦截页，这里再筛一遍，只把真资料交给模型
        merged = load_json(collected_path) or {}
        srcs = merged.get('sources', {})
        dropped = []
        for kind, key in (('youtube', 'videos'), ('web', 'pages')):
            block = srcs.get(kind, {})
            kept = []
            for src in block.get(key, []):
                problem = source_problem(src.get('content', ''))
                (dropped if problem else kept).append(f"{src.get('url', '?')[:80]} {problem}" if problem else src)
            block[key] = kept
            block['count'] = len(kept)
        merged['total_sources'] = sum(srcs.get(k, {}).get('count', 0) for k in ('youtube', 'web'))
        if merged['total_sources'] == 0:
            no_material.append((keyword, "资料全部不可用：" + "；".join(dropped) if dropped else "资料包为空"))
            continue

        merged_json = json.dumps(merged, indent=2, ensure_ascii=False)
        current_date = datetime.now().strftime('%Y-%m-%d')
        cat_slug_final = cat_slug if category else "general"

        prompt = fill_template(
            prompt_template,
            merged_data=merged_json,
            current_date=current_date,
            category=cat_slug_final,
            keyword_variants=variants_block(variants.get(keyword)),
        )

        prompts.append((prompt, {'keyword': keyword, 'slug': slug, 'output_path': output_path}))

    if skipped_exists > 0:
        print(f"  ⏭️  Skipped {skipped_exists} keywords (article exists)")

    # 抓不到资料就停：不让模型凭空写"请自行核实"式的空文章
    if no_material:
        print(f"\n  ❌ {len(no_material)} 个关键词没有可用资料，本步不生成任何文章：")
        for kw, why in no_material:
            print(f"     - {kw}: {why}")
        print("     处理：重跑 collect 补抓（被拦截的来源不会进缓存），或从关键词清单删掉这些词")
        return False

    if not prompts:
        print("\n  ℹ️  Nothing to generate")
        return True

    print(f"\n  📝 Generating {len(prompts)} articles...")
    print(f"     Batch size: {Config.GENERATE_BATCH_SIZE}")
    print(f"     Model: {Config.llm_label()}")
    web = Config.web_channels('generate')
    print(f"     Order: {' → '.join([ch['title'] for ch in web] + [Config.LLM_PROVIDER])}\n")

    # Generate: Yuanbao web → Doubao web → Gemini web → Kimi web → DeepSeek web → Grok web → LLM_PROVIDER
    client = LLMClient(web=web)
    min_words = Config.GENERATE_MIN_WORDS
    # Web answers (Yuanbao / Doubao / Gemini / Kimi / DeepSeek / Grok) must pass this (shape + word floor), else the next one in the order
    web_check = lambda c: mdx_shape_error(clean_llm_output(c), min_words=min_words)
    prompt_of = {meta['output_path']: prompt for prompt, meta in prompts}
    results = await client.generate_batch(prompts, validator=web_check)

    # Save results; a draft that fails the checks is rewritten, up to REPAIR_ROUNDS times
    saved = 0
    failed = 0

    for attempt in range(REPAIR_ROUNDS + 1):
        repair_prompts = []
        for meta, content in results:
            if not content:
                failed += 1
                continue

            cleaned = clean_llm_output(content)
            is_valid, err = validate_markdown(cleaned, min_words)

            if is_valid:
                output_path = meta['output_path']
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(cleaned)
                saved += 1
                # [via 模型]：最终存下的这一版是谁写的（wiki-insights 汇总按它统计每个模型通过篇数）
                print(f"  ✅ {'(repaired) ' if attempt else ''}{meta['slug']}.mdx ({body_word_count(cleaned)} words) [via {meta.get('source', '?')}]")
            elif attempt < REPAIR_ROUNDS:
                print(f"  ⚠️  {meta['slug']}.mdx rejected: {err}")
                repair_prompts.append((_build_repair_prompt(prompt_of[meta['output_path']], err), meta))
            else:
                failed += 1
                print(f"  ❌ {meta['slug']}.mdx — still invalid after {REPAIR_ROUNDS} repairs, not saved: {err}")

        if not repair_prompts:
            break
        print(f"\n  🔧 Repairing {len(repair_prompts)} articles (round {attempt + 1}/{REPAIR_ROUNDS})...")
        results = await client.generate_batch(
            repair_prompts,
            batch_size=min(10, len(repair_prompts)),
            validator=web_check,
        )

    # Summary
    print("\n" + "=" * 70)
    print(f"  {'✅' if failed == 0 else '⚠️ '} Generate complete")
    print("=" * 70)
    print(f"  Saved:   {saved}")
    print(f"  Failed:  {failed}")
    print(f"  Output:  {articles_dir}/")
    client.print_stats()
    print("=" * 70)
    return True


def _build_repair_prompt(prompt: str, error: str) -> str:
    """The original prompt (it carries the reference material, so the rewrite stays sourced) plus what
    was wrong with the previous draft."""
    return (
        prompt
        + "\n\n---\n\n"
        f"Your previous draft was rejected: {error}.\n"
        "Write the COMPLETE article again from the reference material above and fix that problem. "
        "If it was too short, cover each section in more depth with facts from the reference material "
        "(no padding, no repetition) and aim well above the minimum.\n"
        "Output ONLY valid MDX starting with `export const metadata = {`. Do NOT wrap in code blocks."
    )
