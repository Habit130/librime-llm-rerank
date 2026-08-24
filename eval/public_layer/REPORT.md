# Public-layer source slices (AC-153-v1)

- rule: `public-layer-slice-v1`
- digest: `8818cc8033834db953c69c470453b98ecc418d45469d730d078d7c004d63d667`
- A: 455884
- B: 124321

| Repo | Split | Count |
| --- | --- | ---: |
| `rust-lang-cn/book-cn` | A | 196476 |
| `SwiftGGTeam/the-swift-programming-language-in-chinese` | A | 209385 |
| `Go-zh/go` | A | 50023 |
| `vuejs-translations/docs-zh-cn` | B | 124268 |
| `typst-doc-cn/tutorial` | B | 53 |

`slices.tsv` stores source index, path, offsets, target, and complete
pinyin. Competitors are reconstructed from the pinned system lexicon;
上文 is reconstructed from the pinned source files and offsets. Neither
private 上文 nor machine paths are stored.

This corpus is public-layer raw material only. It does not load a
model, emit pairwise scores, or choose a winner. The retired v1/v2
95% representation gates from #69/#150 are demoted and are not
applied here.
