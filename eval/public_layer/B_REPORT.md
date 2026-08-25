# Public-layer B gate (AC-156-v1)

- contract: `AC-156-v1`
- slice digest: `8818cc8033834db953c69c470453b98ecc418d45469d730d078d7c004d63d667`
- code SHA: `461cab18425bb76f62e2d6ac67d883efb6892de4`
- freeze digest: `fb72da82ddb5a4691446b137d754f6cd344f3de8c1c818c5ebdb87adb1a8cb81`
- A winner (frozen by #154): `dedicated_bge_m3`
- A freeze digest: `091af6f9b84925b920dced2dfb218a8079052351b8c1a2735eb9f37081250ed1`
- pair-set rule: `target_len>=2;stride=8;index_mod=0;split=B`
- query rule: `ctx-as-query:last64`
- B source slices (len>=2): 17982
- B source pairs (len>=2): 118081
- B source table digest: `e93f25f11826b3cbaf93d372f65b8bea5060d240235ffe99a9b71b83d720f7cc`
- B stride slices: 2248
- B stride pairs: 14725
- compact table digest: `16de4da09538c318961b8102d89fe71fbdc6d6aa627070dad75a1c5e048a7795`
- gate: `accuracy >= 0.7`
- hits: 11953 / 14725
- accuracy: 0.8117487267
- gate: `PASSED`
- winner: `dedicated_bge_m3`

B only scores the frozen A winner
`dedicated_bge_m3` on the stride-8 subset of #153 B slices whose
target length is >= 2, with the same `ctx-as-query:last64` rule
as A. A verdict of `dedicated_bge_m3` is a public-layer
representation result only: it does not enable `γ` or #113, the
retired 95% τ keeps no official status, and #155 is not started.
