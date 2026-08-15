# Vendored OpenCC t2s dictionary data

`TSCharacters.txt` and `TSPhrases.txt` are the canonical OpenCC
Traditional-to-Simplified dictionary files, copied **verbatim** (byte-identical)
from the OpenCC checkout that the librime revision pinned by
`Habit130/squirrel`'s `action-install.sh` vendors:

- librime `deps/opencc` submodule at commit `556ed224` (ver.1.1.2-148-g556ed224)
- files: `data/dictionary/TSCharacters.txt`, `data/dictionary/TSPhrases.txt`

The same data powers librime's `zh_hans` simplifier (`data/config/t2s.json`:
TSPhrases segmentation + TSPhrases/TSCharacters conversion chain), so the
oracle's simplified matching agrees with the candidate text librime shows.

License: Apache-2.0 (OpenCC project, byvoid). The consuming project is
BSD-3-Clause; the vendored data keeps its Apache-2.0 terms.

Format: `key<TAB>value1 value2 ...` per line; the first value is the default
conversion (OpenCC first-alternative policy). `TSCharacters` keys are single
characters; `TSPhrases` keys are multi-character phrases. The oracle applies
longest phrase match first, character fallback second.

Do not edit these files by hand; update them only by copying from a newer
pinned OpenCC revision, and record that revision here.
