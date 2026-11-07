# Build and verification

Repository-owned commands and evidence from governance Initialize, issue #96,
against `e95f50a42769f1895636b6c4380f1dd5e300a2dc`. Commands ran in disposable
worktrees of a separate clone, not the original checkout or live Rime data.
Failing commands below are recorded facts, not waivers or changes to the product
gate. This delivery changes no product code, dependency/build configuration or
release CI.

## Runtime and isolation

Read `docs/model-free-gates.md` before treating a run as the inherited model-free
gate: it owns the exact runtime, native-helper pairing, fingerprint, permissions,
deployment-path, evidence and optional-skip requirements.

The default `python3` observed during Initialize was Python 3.9.6 / SQLite 3.54.0.
The available `python3.11` was Python 3.11.15 / SQLite 3.53.3, matching that runbook.
Its isolated eval environment was prepared successfully with:

```sh
python3.11 -m venv eval/.venv
eval/.venv/bin/pip install -r eval/requirements.txt 'numpy==2.2.6' 'PyYAML==6.0.2'
```

Both commands **worked**; requirements supplied `pypinyin==0.55.0`. Nothing was
installed machine-wide. Python dependencies alone do not supply the paired
native `fact_store_tool`, the host's dictionary/console or real model weights.

## Commands that worked

Run from the plugin root unless a host directory is explicitly named.

| Command | Initialize result |
| --- | --- |
| `python3 -m unittest discover -s eval -p 'test_*.py'` | **Working:** 721 tests, four optional MLX batch-scorer skips; ResourceWarnings, no failures. |
| `eval/.venv/bin/python -m unittest discover -s eval -p 'test_*.py'` | **Working:** same 721 tests and four optional skips on the pinned runtime. |
| `eval/.venv/bin/python -m unittest daemon.test_retention` | **Working.** |
| `eval/.venv/bin/python -m unittest daemon.test_rebuild` | **Working.** |
| `eval/.venv/bin/python -m unittest eval.test_semantic_benchmark` | **Working.** |
| `eval/.venv/bin/python -m unittest eval.test_public_layer` | **Working.** |
| `eval/.venv/bin/python -m unittest eval.test_public_layer_a` | **Working.** |
| `eval/.venv/bin/python -m unittest eval.test_public_layer_b` | **Working.** |
| `eval/.venv/bin/python -m unittest eval.test_personal_layer_2x2` | **Working.** |
| `eval/.venv/bin/python -m unittest eval.test_recalibrate` | **Working.** |
| `eval/.venv/bin/python -m unittest eval.test_suffix_walkforward` | **Working.** |
| `eval/.venv/bin/python -m unittest eval.test_prefix_hn_census` | **Working.** |
| `eval/.venv/bin/python -m unittest eval.test_actionable_milestone_census` | **Working.** |
| `eval/.venv/bin/python -m unittest eval.test_suffix_walkforward_ac164` | **Working.** |
| `eval/.venv/bin/python -m unittest eval.test_usearch_ann daemon.test_ann` | **Working.** |
| `eval/.venv/bin/python -m unittest eval.test_hnswlib_ann daemon.test_hnswlib_ann` | **Working.** |
| `eval/.venv/bin/python -m unittest eval.test_production_config_lock` | **Working.** |
| `eval/.venv/bin/python -m unittest discover -s eval -p 'test_personal_lora_data*.py'` | **Working.** |
| `eval/.venv/bin/python -m unittest discover -s eval -p 'test_personal_lora_pilot*.py'` | **Working.** |
| `eval/.venv/bin/python -m unittest discover -s eval -p 'test_personal_lora_train*.py'` | **Working.** |
| `eval/.venv/bin/python eval/semantic_benchmark.py --fixture` | **Working:** synthetic fixture only. |
| `eval/.venv/bin/python eval/semantic_benchmark_v2.py --fixture --artifact-dir .local-work/governance-inspection/semantic-v2` | **Working:** synthetic artifacts in the disposable tree. |
| `eval/.venv/bin/python eval/run_usearch_ann_qualification.py --fixture` | **Working:** synthetic fixture; writes artifact files. |
| `eval/.venv/bin/python eval/run_hnswlib_ann_qualification.py --fixture` | **Working in a separate pristine worktree:** exit zero, synthetic terminal `hnswlib_disqualified`. |
| `eval/.venv/bin/python eval/personal_lora_pilot.py --self-test` | **Working:** 14 checks. |
| `eval/.venv/bin/python eval/personal_lora_train.py --self-test` | **Working:** 21 checks. |

The two ANN fixture runners write their committed artifact locations in their
own worktrees. Run each in a separate disposable tree: running hnswlib after the
usearch fixture changed its pinned AC-78 input and caused a non-baseline
SHA-256 refusal. The clean hnswlib rerun above succeeded. Do not carry generated
fixture changes into an unrelated delivery.

## Commands that failed or could not start

| Command | Initialize result and cause |
| --- | --- |
| `scripts/run-model-free-gates.sh` | **Failing:** daemon discovery ran 1062 tests with six failures, 182 errors and 13 optional MLX skips. The standalone tree lacks the paired native `fact_store_tool`; fact-maintenance fixtures cannot complete. The script exits before eval. |
| `scripts/run-model-free-gates.sh eval/.venv/bin/python` | **Failing:** the same counts on Python 3.11.15 / SQLite 3.53.3. Matching Python/SQLite does not replace the missing native helper. Eval was run separately and passed; that is not a full-gate pass. |
| `eval/.venv/bin/python eval/run_walkforward.py --fixture --work-dir .local-work/governance-inspection/walkforward` | **Failing:** `SnapshotError`; the synthetic recorder gap state was `present` before and after the snapshot. |
| `eval/.venv/bin/python tools/check_model_free_gate_prerequisite.py --self-test --root .local-work/governance-inspection/evidence-self-test --report .local-work/governance-inspection/evidence-self-test-report.json` | **Failing:** `checker_exception`; the report names `OSError` but does not expose the underlying OS cause. No cause beyond that was established. |
| `eval/.venv/bin/python eval/verify_fixture.py --dict librime/build/bin/luna_pinyin.dict.yaml` | **Failing:** the host-generated dictionary is absent. |
| `eval/.venv/bin/python eval/verify_artifacts.py --dict librime/build/bin/luna_pinyin.dict.yaml` | **Failing:** the same dictionary is absent. |
| `daemon/.venv/bin/python daemon/integration_hidden_state.py --rounds 32:32` | **Could not start:** the model-runtime interpreter is absent. |
| `daemon/.venv/bin/python daemon/integration_generation.py --events 24` | **Could not start:** the model-runtime interpreter is absent. |
| `daemon/.venv/bin/python daemon/integration_delta.py --events 24` | **Could not start:** the model-runtime interpreter is absent. |
| `daemon/.venv/bin/python daemon/integration_staging.py --events 24` | **Could not start:** the model-runtime interpreter is absent. |
| `daemon/.venv/bin/python daemon/integration_publish.py --events 24` | **Could not start:** the model-runtime interpreter is absent. |
| `ctest --output-on-failure -R '^llm_rerank_test$'` from `librime/build` | **Could not start:** there is no host librime build directory in this standalone plugin checkout. |

Absolute temporary output directories were used for the fixture/evidence rows;
the table gives their equivalent checkout-relative names. No fake native helper,
test filtering, code repair or CI change was used to turn a failure green.

## Native host build prerequisites — not verified in this run

The plugin is built by a host librime tree, not as a standalone CMake project.
From the Squirrel root the inherited command is:

```sh
export BOOST_ROOT=/opt/homebrew/opt/boost
export MACOSX_DEPLOYMENT_TARGET=13.0
make librime
```

Plain `make` may skip plugin changes because Squirrel only checks whether its
librime dylib exists. After first adding the plugin, `make -C librime release`
reconfigures the plugin glob without wiping vendored dependency build
directories. Confirm the plugin dylib in `lib/rime-plugins/` and
`librime/build/lib/rime-plugins/`. Run the plugin-owned `llm_rerank_test` with
`BUILD_TEST=ON`, not librime's unlinked `rime_test`. Prediction e2e additionally
needs the pinned sibling predict plugin and `build_predict`.

These host build/reconfigure commands were **not run**: the isolated plugin
checkout has no Squirrel/librime host. They were not incorrectly launched from
the plugin root. Real-model scoring/training, private snapshots and live
deployment/install commands were also **not run**. Initialize neither opens
habit's live data/models nor enables capture or launchd registration.

## CI

| Workflow / job | Trigger and filters | Required status |
| --- | --- | --- |
| Release / `build` | Push of a `v*` tag, or manual `workflow_dispatch`; no PR trigger. | Not eligible: it does not run/report on every PR. |
| governance-gate / `governance-gate` | Every PR into `master` on opened, edited, synchronize and reopened; `pull_request_target`, no path filter; reads the default-branch workflow/tree, not PR code. | The model's fixed required check after habit runs the owner script. |
| merge-watch / `merge-watch` | Push to `master`, plus completion of other workflows on `master`; excludes its own completion. | Audit only, never a required check. |

Release CI installs checksummed/pinned host dependencies and the predict sibling,
runs model-free Python suites, builds the plugin/native tests/helper, runs the
C++ suite and verifies a universal dylib before publishing. Its trigger/config
is unchanged by governance Initialize. There is no product build/test smoke
check on default-branch pushes; a green merge-watch audit is not such a smoke
check. The approved additional required-check list is empty.

## Actions secrets

No workflow uses a custom Actions secret. GitHub provides the automatic
`GITHUB_TOKEN` / `github.token`; no credential provisioning or secret write is
needed for this delivery. Only habit writes Actions secrets, as `AGENTS.md`
specifies.
