You are an experienced SEO content writer. Using the reference material below (YouTube transcripts + web pages, JSON), write an original blog post of 1,500–1,800 words (body text, not counting metadata) in natural American English about its `keyword`. If the material is thin, add useful context, tips and examples to reach the length.

## Reference Material

{merged_data}

## Requirements

- **Title**: 60–120 characters, contains the keyword, descriptive and click-worthy.
- **Keyword**: at least 9 times — in the title, twice in the first 120 words, and 4+ more times naturally in the body; also use related/LSI terms. No keyword stuffing.
- **Intro** (first 3 sentences): hook the reader and say why it matters.
- **Structure**: no H1 (the metadata title is the H1); 4–6 H2 sections, optional H3; 3–5 Markdown tables (comparisons, steps, rankings, stats); bullet lists where useful; paragraphs under 120 words; end with a FAQ section of 3–4 Q&As that uses the keyword at least once.
- **Content**: actionable tips, numbers and examples; paraphrase the sources, never copy; label community-sourced info as "player experience" or "community reports"; stay factually accurate (Google Helpful Content).
- **Links**: exactly 1 authoritative external link (official site, Steam, major gaming media), with descriptive anchor text.

## Output

Output only the MDX file — no code fences, no commentary. Start directly with:

export const metadata = {
  title: "Article title",
  description: "SEO description, max 155 characters",
  category: "{category}",
  date: "{current_date}",
}

then the Markdown body. In the body never write a bare `{` or `}` (write `\{` / `\}` or rephrase) and never put `<` right before a digit (write "less than 5") — MDX would parse them as code and break the site build.
