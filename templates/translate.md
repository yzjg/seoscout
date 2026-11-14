把下面的英文 MDX 文章翻译成 $language_name（$lang_code），译文要自然流畅。

规则：
1. Markdown 格式（标题、列表、加粗、链接、表格）、HTML 标签、URL、文章结构和长度都保持不变。
2. 元数据只翻译 title、description，以及 summary（如果有）；category、date、lastModified、image 等其他字段原样保留。保持 `export const metadata = { ... }` 的 JS 写法，不要改成 YAML frontmatter（---）。
3. 正文里不能有未转义的 `{`、`}`（写成 `\{`、`\}`，原文已经是 `\{` 的保持不变），`<` 也不能紧跟数字（`<5` 改成文字表达），否则 MDX 构建会失败。
4. 只输出译好的 MDX：直接以 `export const metadata = {` 开头，不包代码块，不加任何解释。

英文原文：

$content
