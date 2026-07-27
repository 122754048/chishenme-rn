# USFR Current-State Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove proven generated residue, obsolete documentation, and legacy Skill-name aliases while preserving the current universal USFR runtime and its validated contracts.

**Architecture:** Treat `references/bundle_manifest.json` plus live code/document references as the runtime authority. Delete only items that are generated, unreferenced, or explicitly routing-only historical aliases; protect files declared in the bundle manifest and compatibility modes still selected by current deployment contracts.

**Tech Stack:** PowerShell filesystem verification, Python 3.12, pytest, existing bundle verification scripts.

## Global Constraints

- Do not remove any file declared in `references/bundle_manifest.json`.
- Do not alter fixed slots, `background_music`, direct language-only lip-sync, user-script approvals, Provider behavior, queueing, or deployment APIs.
- Do not remove profile modes, runtime adapters, or compatibility flags that remain referenced by current executable code or deployment contracts.
- Delete only verified generated caches, the stale unreferenced dependency map, and the two routing-only old Skill aliases.
- Before every recursive deletion, resolve and verify each absolute target remains inside either the canonical Skill root or the two explicitly named old-alias directories.

---

### Task 1: Lock the Clean-State Contract

**Files:**
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_cleanup_contract.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_cleanup_contract.py`

**Interfaces:**
- `SkillCleanupContractTest` rejects historical alias directories, stale `references/dependency-map.md`, and generated cache directories.

- [ ] **Step 1: Write the failing clean-state test**

```python
def test_historical_aliases_and_stale_dependency_map_are_absent(self):
    self.assertFalse(LEGACY_FACTORY.exists())
    self.assertFalse(LEGACY_SEEDANCE.exists())
    self.assertFalse((ROOT / "references" / "dependency-map.md").exists())
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -B -m pytest tests/test_cleanup_contract.py::SkillCleanupContractTest::test_historical_aliases_and_stale_dependency_map_are_absent -q`

Expected: FAIL because the old aliases and stale dependency map still exist.

- [ ] **Step 3: Remove the obsolete legacy-alias assertion**

```python
# Remove test_legacy_aliases_are_routing_only; the aliases themselves are now forbidden.
```

- [ ] **Step 4: Do not change runtime source while establishing the test**

Run: `python -B -m pytest tests/test_cleanup_contract.py -q`

Expected: FAIL only on currently present generated/cache and obsolete-path residue.

### Task 2: Remove Verified Historical Files and Generated Residue

**Files:**
- Delete: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\references\dependency-map.md`
- Delete: `C:\Users\zhaocx04\.codex\skills\tiktok-ai-video-replication-factory\`
- Delete: `C:\Users\zhaocx04\.codex\skills\seedance-storyboard-replication\`
- Delete generated directories named `.pytest_cache` or `__pycache__` under `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\SKILL.md`

**Interfaces:**
- The canonical Skill is referenced only as `$universal-source-fidelity-replication`.
- `verify_lightweight_bundle()` returns an empty failure list on a clean tree.

- [ ] **Step 1: Verify the exact recursive-delete targets before deletion**

Run a PowerShell resolved-path check for every cache directory and both alias roots.

Expected: Every target resolves under the canonical Skill root or one explicitly named alias root.

- [ ] **Step 2: Delete the stale dependency map and the two old alias roots**

Use `apply_patch` for the text-file deletion. Use one verified PowerShell cleanup operation for the empty/routing-only alias roots.

- [ ] **Step 3: Delete only verified generated cache directories**

Use one verified PowerShell cleanup operation for the resolved `.pytest_cache` and `__pycache__` directories.

- [ ] **Step 4: Remove the obsolete alias statement from the canonical Skill header**

```markdown
This is the canonical Skill. Use `$universal-source-fidelity-replication` for new work.
```

- [ ] **Step 5: Run clean-state and bundle checks**

Run: `python -B -m pytest tests/test_cleanup_contract.py -p no:cacheprovider -q`

Expected: PASS.

Run: `python -B scripts/verify_lightweight_bundle.py`

Expected: `lightweight bundle is valid`.

### Task 3: Prove Runtime Closure Was Preserved

**Files:**
- No additional files.

**Interfaces:**
- Every bundle-manifest runtime file remains present.
- No remaining non-test reference resolves to deleted `dependency-map.md` or either historical alias name.

- [ ] **Step 1: Run dependency-reference scans**

Run: `rg -n "dependency-map\\.md|tiktok-ai-video-replication-factory|\\$seedance-storyboard-replication" --glob '!tests/**' --glob '!**/__pycache__/**' --glob '!**/.pytest_cache/**'`

Expected: no matches.

- [ ] **Step 2: Run bundle closure and feature regressions**

Run: `python -B -m pytest tests/test_bundle_runtime_closure.py tests/test_lightweight_bundle_contract.py tests/test_cleanup_contract.py tests/test_user_editable_script.py tests/test_review_workflow.py tests/test_review_service.py tests/test_ephemeral_runtime.py tests/test_server_fastapi_router.py tests/test_job_api.py tests/test_inprocess_video_e2e.py tests/test_production_ports.py -p no:cacheprovider -q`

Expected: PASS.

- [ ] **Step 3: Run the full suite**

Run: `python -B -m pytest -p no:cacheprovider -q`

Expected: PASS with no generated-cache cleanliness failures.

## Plan Self-Review

The plan preserves every file declared as current runtime, removes only proven historical/generated residue, updates the canonical header and cleanup tests, and verifies both runtime closure and behavior. It deliberately leaves currently referenced `legacy` compatibility modes unchanged because deleting them would be a runtime behavior migration rather than safe cleanup.
