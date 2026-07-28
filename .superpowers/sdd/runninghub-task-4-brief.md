### Task 4: Update the runtime contract and synchronize the local Skill

**Files:**

- Modify: `usfr-server/SKILL.md`
- Modify: `usfr-server/bundled-skills/seedance-storyboard-replication/SKILL.md`
- Modify: `usfr-server/references/server-deployment-step-by-step.md`
- Modify: `.env.example`
- Sync to: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/`

- [ ] **Step 1: Update provider wording and command references**

Replace the active Youdao-only Seedance submission instructions with the RunningHub standard-model endpoint, dedicated key, permitted upload list, fixed `videoUrls=[]`, query/download lifecycle and no-retry policy. Do not alter source analysis, route selection, approvals, storyboard settings, ASR/TTS or lip-sync workflow IDs.

- [ ] **Step 2: Add a contract test that rejects any active provider document or env default pointing to Youdao**

Run: `python -B -m pytest usfr-server/tests/test_skill_contract.py -q`

Expected: FAIL until the runtime contract and package manifest use the new adapter.

- [ ] **Step 3: Sync the verified packaged files to the locally invoked Skill**

Copy only the changed provider/config/script/document files after their workspace tests pass. Do not copy credentials, run artifacts, `.pytest_cache`, source videos, storyboards or temporary files.

- [ ] **Step 4: Run the final focused verification**

Run: `python -B -m pytest usfr-server/tests/test_runninghub_standard_seedance.py usfr-server/tests/test_production_ports.py usfr-server/tests/test_seedance_dependency_resolution.py usfr-server/tests/test_skill_contract.py -q; python -B -m pytest backend/tests/test_background_music_execution.py backend/tests/test_background_music_local_mvp.py -q`

Expected: PASS; no test permits a source-video reference or logs a credential.

## Self-Review

- The plan changes only the final Seedance video-provider boundary; it preserves all mandatory script/storyboard approvals and upstream analysis.
- A dedicated standard-model key avoids silently sending a non-enterprise workflow key to the enterprise-only API.
- The standard payload is audited before paid submission, uploads only references that are legal for the active route, and never carries source/opaque videos.
- Music/singing still uses `@Audio1` in the compiled prompt, while the external request uses RunningHub’s documented `audioUrls` field.
