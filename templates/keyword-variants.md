You are an SEO keyword analyst for the game "{topic}". Each keyword below gets exactly one article ("one keyword, one page"). Below the keywords is a pool of raw search queries that real players typed (Google Suggest, DataForSEO, 3ue, Google Trends).

For EVERY keyword, return:

1. `from_pool`: queries from the pool that have the SAME search intent as that keyword — a reader typing that query wants exactly this article. Typical cases: synonyms (e.g. "skins" vs "morphs"), singular/plural, different word order, abbreviations of the game name, extra filler words, a year, a question form of the same need. Copy each query exactly as written in the pool. Do NOT pick queries about a different or broader/narrower topic that deserves its own page, and do NOT pick a query for more than one keyword. An empty list is fine.
2. `synonyms`: up to 4 extra phrasings players commonly use for the same intent that are NOT in the pool and differ from the keyword itself (true synonyms or common alternative wording, e.g. "how to hunt" for "how to catch prey"). Write them as search phrases including the game name or its usual abbreviation. Only real, natural phrasings; an empty list is fine. Never invent names, subreddit/Discord handles, URLs, codes or item names — the article will repeat these phrases as facts.

Return one item per keyword, with `keyword` copied exactly as given.

## Keywords (category: keyword)

{keywords}

## Pool of raw player queries

{pool}
