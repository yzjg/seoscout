"""Per-keyword search variants for "one keyword, one page" articles.

classify-keywords keeps one keyword per search intent and drops the other ways players write it.
This module gets them back from the raw long-tail files next to 关键词.json
(long-tail-keyword-{google-suggest,dataforseo,3ue,trends}.json) so the article can use them:

1. Deterministic: normalize every raw query (lowercase, drop punctuation / "roblox" / the game
   name and its acronym / years / filler words, singularize, ignore word order) and match it to the
   keyword with the same normalized form — spelling, plural and word-order variants.
2. claude -p (claude-dispatch/claude-p.sh, 3 tries + account switching): picks same-intent queries
   from the rest of the pool (true synonyms) and adds up to 4 common synonym phrasings.
   If it still fails, raise — never fill in made-up output.

Result is cached in <meta dir>/关键词变体.json, rebuilt when the raw files or the keyword list change.
"""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

CLAUDE_P_SH = os.getenv("CLAUDE_P_SH", "/Users/yuzhijian/.openclaw/skills/claude-dispatch/claude-p.sh")
CACHE_NAME = "关键词变体.json"
SOURCES = ["google-suggest", "dataforseo", "3ue", "trends"]
MAX_VARIANTS = 8
MAX_SYNONYMS = 4
STOP = set("a an the for in of on to all and roblox game list working active valid new latest current".split())
MONTHS = set("january february march april may june july august september october november december".split())
SCHEMA = json.dumps({
    "type": "object", "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "required": ["keyword", "from_pool", "synonyms"],
        "properties": {"keyword": {"type": "string"},
                       "from_pool": {"type": "array", "items": {"type": "string"}},
                       "synonyms": {"type": "array", "items": {"type": "string"}}}}}}})


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", s.lower())).strip()


def _singular(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("sses", "xes", "ches", "shes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def _name_forms(names):
    """Cleaned game-name phrases (longest first) and their acronyms (e.g. wcue)."""
    forms, acr = set(), set()
    for n in names:
        c = _clean(n.replace("roblox", ""))
        if c:
            forms.add(c)
            if len(c.split()) > 1:
                acr.add("".join(w[0] for w in c.split()))
    return sorted(forms, key=len, reverse=True), acr


def _key(s: str, forms, acr) -> tuple:
    t = " " + _clean(s).replace("roblox", " ") + " "
    t = re.sub(r"\s+", " ", t)
    for f in forms:
        t = t.replace(" " + f + " ", " ")
    words = [w for w in t.split() if w not in acr and w not in STOP and w not in MONTHS
             and not re.fullmatch(r"20\d\d", w)]
    return tuple(sorted({_singular(w) for w in words}))


def _load_pool(meta_dir: str):
    """{query: volume} from the raw long-tail files that exist; plus the seed names they were mined for."""
    pool, seeds = {}, []

    def add(q, v=0):
        q = re.sub(r"\s+", " ", str(q or "")).strip()
        if q:
            pool[q.lower()] = max(pool.get(q.lower(), 0), int(v or 0))

    for src in SOURCES:
        p = Path(meta_dir) / f"long-tail-keyword-{src}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("keyword"):
            seeds.append(d["keyword"])
        if src == "trends":
            for k in ("relatedQueries", "risingQueries"):
                for it in d.get(k) or []:
                    add(it.get("query"))
            continue
        for it in d.get("keywords") or []:
            if isinstance(it, str):
                add(it)
            else:
                add(it.get("keyword"), it.get("search_volume") or it.get("volume_28d") or 0)
    return pool, seeds


def _fingerprint(meta_dir: str) -> str:
    """Hash of the raw long-tail files: when they change (new mining run) the whole cache is rebuilt."""
    h = hashlib.sha1()
    for src in SOURCES:
        p = Path(meta_dir) / f"long-tail-keyword-{src}.json"
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()


def _ask_claude(topic, entries, pool, raw_dir, template_path):
    kw_lines = "\n".join(f"- {e['category'] or 'general'}: {e['keyword']}" for e in entries)
    pool_lines = "\n".join(f"- {q}" + (f" (volume {v})" if v else "") for q, v in
                           sorted(pool.items(), key=lambda x: (-x[1], x[0])))
    prompt = (Path(template_path).read_text(encoding="utf-8")
              .replace("{topic}", topic).replace("{keywords}", kw_lines).replace("{pool}", pool_lines))
    os.makedirs(raw_dir, exist_ok=True)
    why = ""
    for attempt in range(1, 4):
        r = subprocess.run(["bash", CLAUDE_P_SH, "--model", "claude-sonnet-5-5", "--effort", "medium",
                            "--raw-dir", raw_dir, "--json-schema", SCHEMA],
                           input=prompt, capture_output=True, text=True, timeout=3600)
        if r.returncode != 0:
            raise RuntimeError(f"claude -p 同义词判断失败（exit={r.returncode}，已内部重试）：{r.stderr[-500:]}")
        try:
            items = json.loads(r.stdout)["items"]
        except (ValueError, KeyError, TypeError) as e:
            why = f"输出不是合法 JSON：{e}"
        else:
            got = [it["keyword"] for it in items]
            missing = [e["keyword"] for e in entries if e["keyword"] not in got]
            if not missing:
                return items
            why = f"缺少 {len(missing)} 个关键词：{missing[:5]}"
        print(f"  ⚠️  同义词结果校验不通过（{attempt}/3）：{why}")
    raise RuntimeError(f"claude -p 同义词结果 3 次都过不了校验：{why}")


def build_variants(meta_dir: str, entries, topic: str, raw_dir: str, template_path: str) -> dict:
    """entries: [{'keyword', 'category'}]. Returns {keyword: {'variants': [...], 'synonyms': [...]}}
    ({} when no raw long-tail files exist). Only keywords missing from the cache file in meta_dir are
    computed (a --test / subset run never drops cached ones); the cache is reset when the raw files change."""
    pool, seeds = _load_pool(meta_dir)
    if not pool:
        print(f"  ℹ️  {meta_dir} 下没有 long-tail-keyword-*.json，不加同义写法")
        return {}
    cache_path = Path(meta_dir) / CACHE_NAME
    fp = _fingerprint(meta_dir)
    cached = {}
    if cache_path.exists():
        c = json.loads(cache_path.read_text(encoding="utf-8"))
        if c.get("fingerprint") == fp:
            cached = c.get("keywords") or {}
    entries = [e for e in entries if e["keyword"] not in cached]
    if not entries:
        print(f"  🔤 同义写法：用缓存 {cache_path}")
        return cached
    keywords = [e["keyword"] for e in entries]
    if cached:
        print(f"  🔤 同义写法：缓存里有 {len(cached)} 个，新算 {len(keywords)} 个")

    forms, acr = _name_forms([topic] + seeds)
    # 1. deterministic: same normalized form (collisions checked against cached keywords too)
    by_key = {}
    for kw in list(cached) + keywords:
        by_key.setdefault(_key(kw, forms, acr), []).append(kw)
    exact = {kw: [] for kw in keywords}
    ambiguous = 0
    for q in pool:
        k = _key(q, forms, acr)
        owners = by_key.get(k, []) if k else []
        if len(owners) == 1 and owners[0] in exact and _clean(q) != _clean(owners[0]):
            exact[owners[0]].append(q)
        elif len(owners) > 1:
            ambiguous += 1
    taken = {q for qs in exact.values() for q in qs}
    print(f"  🔤 同义写法 1/2 规则匹配：{len(taken)} 条原始词归到 {sum(1 for v in exact.values() if v)} 个关键词"
          f"（{ambiguous} 条同时像多个关键词，跳过）")

    # 2. claude -p: true synonyms from the rest of the pool
    kw_clean = {_clean(kw) for kws in by_key.values() for kw in kws}
    taken |= {q for v in cached.values() for q in v.get("variants", [])}  # already given to cached keywords
    rest = {q: v for q, v in pool.items() if q not in taken and _clean(q) not in kw_clean}
    print(f"  🔤 同义写法 2/2 claude -p 判断同义词：{len(keywords)} 个关键词，候选 {len(rest)} 条 ...")
    items = _ask_claude(topic, entries, rest, raw_dir, template_path)
    picked, dropped = set(), []
    ai = {}
    for it in items:
        kw = it["keyword"]
        if kw not in exact or kw in ai:
            continue
        fp_list = []
        for q in it.get("from_pool") or []:
            ql = q.strip().lower()
            if ql not in rest or ql in picked:
                dropped.append(q)  # not in the pool, or already given to another keyword
                continue
            picked.add(ql)
            fp_list.append(ql)
        syn = []
        for s in it.get("synonyms") or []:
            s = re.sub(r"\s+", " ", s).strip()
            if s and _clean(s) != _clean(kw) and _clean(s) not in {_clean(x) for x in syn} \
                    and s.lower() not in pool:
                syn.append(s)
        ai[kw] = (fp_list, syn[:MAX_SYNONYMS])
    if dropped:
        print(f"  ⚠️  删掉不在候选池或重复分配的词 {len(dropped)} 个：{dropped[:10]}")

    result = {}
    for kw in keywords:
        fp_list, syn = ai.get(kw, ([], []))
        vs, seen = [], set()
        for q in sorted(set(exact[kw]) | set(fp_list), key=lambda q: (-pool.get(q, 0), len(q), q)):
            d = " ".join(w for w in _clean(q).split() if w not in MONTHS and not re.fullmatch(r"20\d\d", w))
            if d not in seen:  # "npc" / "npc:" / "codes 2026 july" / "codes 2026 august" count once
                seen.add(d)
                vs.append(q)
        vs = vs[:MAX_VARIANTS]
        result[kw] = {"variants": vs, "synonyms": syn}
    n = sum(1 for v in result.values() if v["variants"] or v["synonyms"])
    result = {**cached, **result}
    cache_path.write_text(json.dumps({"fingerprint": fp, "topic": topic, "keywords": result},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  🔤 同义写法完成：{n}/{len(keywords)} 个关键词有变体，已存 {cache_path}（共 {len(result)} 个）")
    return result


def variants_block(v: dict) -> str:
    """Requirement line for the generate prompt; '' when there is nothing to add."""
    phrases = (v or {}).get("variants", []) + (v or {}).get("synonyms", [])
    if not phrases:
        return ""
    quoted = ", ".join(f'"{p}"' for p in phrases)
    return ("- **Search variants**: players also search this exact topic as " + quoted +
            ". Work at least half of them into H2/H3 headings, body text or the FAQ, each once, inside "
            "grammatical sentences (adjust word order, capitalization and grammar; write the game name properly; "
            "skip any that cannot fit naturally). Do not bold them, do not list them, and do not add separate "
            "sections for them — they are the same topic as the keyword.\n")
