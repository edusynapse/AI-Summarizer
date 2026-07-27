# Plan 001 — Summary usefulness v1: line resolve, adjacency, multi-repo workspace

**Status:** P0 implemented (workspace + adjacency.sqlite per repo + line postprocess + CLI)  
**Repo:** AI-Summarizer (open source skill `agent_token_usage_optimization`)  
**Authoring context:** Know To Win (Flutter `know_to_win` + backend `ktw_do_react_api`) as a *reference multi-repo setup*, not a hard-coded product dependency  
**Date:** 2026-07-27  
**HARD REQUIREMENT (user):** multi-repo = **separate** symbol index + summary corpus + adjacency DB **per adjacent repo**. No clever merging into one blob. No “one graph to rule them all.”

---

## 0. Architecture lock — one store stack per repo (MANDATORY)

**100% clear rule:**

| Repo | What it owns (always local to that checkout) |
|------|-----------------------------------------------|
| Repo A (e.g. Flutter) | Its own `summaries/`, its own `index.sqlite` (symbols), its own **adjacency DB** |
| Repo B (e.g. API) | Its own `summaries/`, its own `index.sqlite`, its own **adjacency DB** |
| Repo C (if any) | Same — fully separate |

```text
know_to_win/
  skills/agent_token_usage_optimization/
    summaries/repo/**          # Flutter summaries ONLY
    repo/index.sqlite          # Flutter symbols ONLY
    repo/adjacency.sqlite      # Flutter adjacency ONLY  (or edges in index.sqlite — still THIS repo only)

ktw_do_react_api/
  skills/agent_token_usage_optimization/
    summaries/repo/**          # API summaries ONLY
    repo/index.sqlite          # API symbols ONLY
    repo/adjacency.sqlite      # API adjacency ONLY
```

**What `workspace.env` does (and does not do):**

- **Does:** list sibling checkout paths + ids so tools know *where* the other skill trees live.  
- **Does not:** merge DBs, copy foreign symbols into this repo’s sqlite as if they were local, or invent a unified cross-repo database.

**How you use an adjacent repo’s data:**

1. Build/index/summarize **in that repo** (normal install + `broker.py index` + summarizer).  
2. From the current repo, tools **open the sibling path** from `WORKSPACE_SIBLINGS` and read:
   - `{sibling}/skills/.../repo/index.sqlite`
   - `{sibling}/skills/.../repo/adjacency.sqlite` (if separate)
   - `{sibling}/skills/.../summaries/`
3. Queries are **explicitly scoped**: `adjacent --repo api` or `summary_broker --workspace api search …` meaning “run against that repo’s stores,” not “magically fold api into local.”

**In-repo adjacency** = edges among files **inside that same repo only**, stored only in **that** repo’s adjacency DB.

**Cross-repo (later / optional)** = not a third merged DB. At most:

- a small **link table** of keys (e.g. HTTP path string → local file in *this* repo), plus  
- lookup of the **other** repo’s separate index/summaries by opening their files on disk  

…or the agent simply switches tool root to the sibling skill. **No single combined adjacency DB.**

**Banned in this plan:**

- One sqlite that holds both Flutter and API symbols/summaries/adjacency  
- “Shadow copy” of the whole sibling summary tree into the current repo  
- Graph DB spanning all siblings  

---

## 1. Problem

LLM file summaries already cut **primary** research (which file to open). Remaining cost is **secondary** research:

1. **False line ranges** on large files → wrong jump → full-file open.  
2. **No structured “what’s next door”** → agents re-grep the tree to find callers/callees.  
3. **Cross-repo products** (client + API) → summary layer stops at the repo boundary; agents lose the contract hop (route ↔ handler) unless hand-documented.

The skill must stay **repo-agnostic and open-source**: any user installs into one or more repos and optionally declares sibling checkouts via **local config**, never via hard-coded KTW paths.

---

## 2. Goals

| Goal | Success signal |
|------|----------------|
| G1 — Trustworthy NAVIGATION lines | Post-processed ranges match `outline.extract` for resolved symbols on large sample files |
| G2 — In-repo adjacency (v1) | `summary_broker adjacent <path>` lists imports + reverse importers without LLM |
| G3 — Optional multi-repo workspace | User fills a **local** env/config once; tools resolve sibling skill roots and read **that sibling’s separate** symbol/summary/adjacency stores |
| G4 — Zero/low LLM regen | P0 features improve **existing** `.md` summaries without full re-summarize |
| G5 — Open-source ergonomics | Template + install script; secrets/paths gitignored; docs for single-repo and multi-repo users |

## 3. Non-goals (this plan)

- Graph database (Neo4j etc.) — use SQLite / JSON.  
- Full precise callgraphs / type-aware Dart analysis.  
- Merging two repos into one summary tree.  
- Second LLM enrichment pass.  
- Shipping Know To Win–specific paths in shared skill code.  
- New cloud settings service or KTW `settings.js` tax.

---

## 4. Research: author needs (KTW) vs generic OSS

### 4.1 Author’s multi-repo product

```
know_to_win (Flutter)
  lib/, libadmin/  →  HTTP / SessionURI  →  ktw_do_react_api
                                                 routes, models, Redis
```

Already true in production use of the skill:

- Skill installed under each repo’s `skills/agent_token_usage_optimization/`.  
- Flutter side: ~786 dart summaries, rollups (`lib`, `libadmin`, …), `repo_context` describing the API sibling.  
- Backend side: separate tree, same skill pattern (when installed).  
- Cross-repo edges are **contracts** (paths like `/admin/settings`), not filesystem imports.

### 4.2 Generic open-source user

| User type | Need |
|-----------|------|
| Single repo | Install → summarize → brokers; adjacency optional; **no** multi-repo config |
| Monorepo packages | Same skill once; import adjacency within tree |
| Client + API (like KTW) | **Two full skill installs**; each has its own summaries + symbol DB + adjacency DB; workspace.env only points at sibling roots |
| CI / teammates | Workspace file is **local** (or per-machine); templates committed without absolute paths |

### 4.3 Design constraint: configuration

**Do not** bake `/home/…/know_to_win` into shared scripts.

**Do** ship:

1. A **template** (committed): `repo/workspace.env.example` (or `workspace.json.example`).  
2. A **local file** (gitignored): `repo/workspace.env` (or `workspace.local.json`) populated by the user or by an install helper.  
3. Load order (first hit wins for each key):

```text
process env  >  repo/workspace.env  >  defaults (single-repo only)
```

Prefer **dotenv-style `KEY=value`** for zero deps (stdlib parse) and familiarity; optional JSON later if lists get awkward.

---

## 5. Configuration design (multi-repo without product lock-in)

### 5.1 File locations (per installed skill)

```text
<target_repo>/skills/agent_token_usage_optimization/
  repo/
    config.json              # existing — include/exclude for index
    workspace.env.example    # NEW — committed template
    workspace.env            # NEW — local, gitignored
    index.sqlite             # existing symbols (+ new edge tables)
    context_session.json     # existing Layer 2 session (gitignored)
```

Root `.gitignore` of **consumer** repos should ignore `workspace.env` (skill `repo/.gitignore` will list it so install copies the ignore rule).

### 5.2 Template keys (`workspace.env.example`)

All optional. Empty = single-repo mode.

```bash
# AI-Summarizer workspace (local — copy to workspace.env and edit)
# Used only for multi-repo adjacency / cross-repo navigation. Safe to omit.

# Stable id for THIS checkout (shown in ADJACENT / cross tools)
WORKSPACE_REPO_ID=my-app

# Role hint for agents/docs: app | api | lib | other
WORKSPACE_ROLE=app

# Sibling checkouts: id → absolute or ~ path to repo root (not to skills/)
# Comma-separated pairs: id=/abs/path
# Example multi-repo product:
# WORKSPACE_SIBLINGS=api=/home/me/work/my-api,web=/home/me/work/my-web
WORKSPACE_SIBLINGS=

# Optional: package/module prefix used when resolving language imports
# (e.g. Dart package name → lib/). Comma-separated id:prefix
# WORKSPACE_PACKAGE_PREFIXES=my_app:package:my_app/
WORKSPACE_PACKAGE_PREFIXES=

# Optional: enable cross-repo contract scan (routes) when siblings set
# WORKSPACE_CROSS_CONTRACTS=1
WORKSPACE_CROSS_CONTRACTS=0
```

**KTW example (user-local only, never committed as shared default):**

```bash
WORKSPACE_REPO_ID=know_to_win
WORKSPACE_ROLE=app
WORKSPACE_SIBLINGS=api=/home/surajitray/Development/VSCodeProjects/ktw_do_react_api
WORKSPACE_PACKAGE_PREFIXES=know_to_win:package:know_to_win/
WORKSPACE_CROSS_CONTRACTS=1
```

Backend checkout:

```bash
WORKSPACE_REPO_ID=ktw_do_react_api
WORKSPACE_ROLE=api
WORKSPACE_SIBLINGS=app=/home/surajitray/IdeaProjects/know_to_win
WORKSPACE_CROSS_CONTRACTS=1
```

### 5.3 Loader API

`lib/workspace_config.py`:

- `load_workspace(skill_repo_dir) -> dict`  
- Resolve `~`, expand paths, validate sibling dirs exist (warn, don’t crash).  
- Resolve sibling skill root: `{sibling}/skills/agent_token_usage_optimization`.  
- Expose `list_siblings()`, `sibling_summaries_root(id)`, `this_repo_id()`.

No network. No secrets expected (paths only). Document: do not put API keys here (summarizer providers stay in agy/grok env as today).

### 5.4 Why not only `repo_context` markdown?

`repo_context` stays the **prose orientation** layer (already used on Flutter).  
`workspace.env` is **machine-readable** for tools (adjacent, cross, install helpers). Both coexist: prose for agents reading orientation; env for scripts.

---

## 6. Feature plan (80/20)

### 6.1 P0-A — Post-resolve NAVIGATION line numbers (highest accuracy kill)

| Item | Detail |
|------|--------|
| **What** | After LLM summary write (and a batch tool over existing `.md`), parse NAVIGATION / KEY EXPORTS for symbols; run `outline.extract` on source; rewrite `approx lines X–Y` → `lines N` / `lines N–M` when resolved; drop or mark `?` when unresolved |
| **Where** | `lib/summary_postprocess.py`; hook from `summarizer.py` success path + parent of parallel runners; CLI `summaries/postprocess_summaries.py` for offline batch |
| **LLM?** | No |
| **Regen?** | Not required — batch postprocess existing corpus |
| **State** | In-place edit of `summaries/repo/**/*.md` only (content, not manifest hash of source — optional sidecar `nav_resolved: true` in a tiny meta comment is unnecessary if deterministic) |

**Symbol match rules:** exact name; else last segment after `.`; case-sensitive first.

**Lifecycle**

| Verb | Behavior |
|------|----------|
| CREATE | On new summary write → postprocess before finalizing file |
| READ | Agents/brokers read improved md |
| UPDATE | Re-run postprocess when source changes and summary regenerates |
| REINDEX | `postprocess_summaries.py` over all md |
| DELETE | Deleting summary removes resolved lines with it |

### 6.2 P0-B — Prompt: NEXT HOP + private spine (cheap LLM quality)

| Item | Detail |
|------|--------|
| **What** | Update `summaries/prompt_template.txt`: NAVIGATION may include private control-plane methods; add `## NEXT HOP` one-liner (`broker.py read {path} --symbol …` or outline) |
| **Where** | Shared prompt template (install overwrites shared file) |
| **LLM?** | Affects **future** summarizations only |
| **Optional without LLM** | Postprocess can synthesize NEXT HOP from first resolved NAVIGATION symbol if section missing |

### 6.3 P0-C — In-repo adjacency v1 (import graph) — **per repo only**

| Item | Detail |
|------|--------|
| **What** | Extract imports (dart/js/ts/py light parsers); store edges; reverse index; CLI + optional md inject |
| **Where** | `lib/adjacency.py`; **prefer dedicated `repo/adjacency.sqlite`** (symbols stay in `index.sqlite`). Both belong to **this repo only**. |
| **Schema** | `file_edges(src TEXT, dst TEXT, kind TEXT, PRIMARY KEY (src,dst,kind))` with `kind IN ('import')`; indexes on `src`, `dst` |
| **CLI** | `summary_broker.py adjacent <path> [--max N] [--json]` — defaults to **current** repo DBs |
| **CLI multi** | `summary_broker.py adjacent <path> --repo <sibling_id>` — opens **sibling’s** `adjacency.sqlite` / skill root from `WORKSPACE_SIBLINGS`; does **not** write into current repo |
| **Inject** | Deterministic `## ADJACENT` block in **this** repo’s summary md only (markers `<!-- ADJACENT BEGIN/END -->`) |
| **LLM?** | No |
| **Resolution** | Relative imports → paths **inside this repo**; `package:foo/` via `WORKSPACE_PACKAGE_PREFIXES` if set |

**Lifecycle**

| Verb | Behavior |
|------|----------|
| CREATE | `broker.py index` (or adjacency build step) writes edges for **this** repo only |
| READ | `adjacent` (local or `--repo sibling` read-only against sibling files) |
| UPDATE | Re-index **that** repo when its source changes |
| REINDEX | Full rebuild **per repo**, independently |
| DELETE | File gone from **that** repo’s scan → drop its edges there |

### 6.4 P1 — Cross-repo use (siblings) — still **separate DBs**

| Item | Detail |
|------|--------|
| **What** | User lists siblings in `workspace.env`. Each sibling is a full skill install with its **own** summaries + symbol DB + adjacency DB. |
| **How tools work** | Resolve `WORKSPACE_SIBLINGS[id]` → read that tree’s skill stores. Never merge into local sqlite. |
| **Optional link hints (local only)** | If we extract HTTP path literals in **this** repo, store **only** `local_path → path_string` (or path_string list) in **this** adjacency/contract table. Matching to a server **file** means: open sibling skill and search **sibling** index/summaries for that path string — result still lives in sibling’s world. |
| **CLI** | `summary_broker.py --repo api search "…"`, `broker.py --repo api outline …`, `adjacent --repo api` |
| **Not** | A combined adjacency DB; copying sibling summaries into current repo; writing into sibling DBs from current repo’s index job |

**Discovery honesty (non-LLM):** in-repo edges = import parse in **that** repo. Cross-repo “which API file” = search **API repo’s own** stores (or path-literal join when both sides share the same string). No magic unified graph.

### 6.5 Explicit deferrals

| Idea | Why later |
|------|-----------|
| Graph DB | SQLite hop-1 is enough |
| Embeddings of edges | Orthogonal |
| Auto-clone siblings | Dangerous / out of scope |
| Writing into sibling repo from this tool | Read-only cross |

---

## 7. Install artifacts and scripts

### 7.1 Changes to `install.sh` (shared vs template)

| Path | Policy |
|------|--------|
| `lib/workspace_config.py`, `lib/adjacency.py`, `lib/summary_postprocess.py` | **shared** overwrite |
| `summaries/postprocess_summaries.py` | **shared** overwrite |
| `summaries/prompt_template.txt` | **shared** overwrite (NEXT HOP / spine) |
| `repo/workspace.env.example` | **shared** overwrite (template always fresh) |
| `repo/workspace.env` | **never create from secrets**; on first install copy example → `workspace.env` only if missing **or** leave missing and print “copy example” (prefer **copy example once** like other templates) |
| `repo/.gitignore` | ensure `workspace.env`, `context_session.json`, … |

### 7.2 New helper: `configure_workspace.sh` (or `workspace_init.sh`)

Repo root of AI-Summarizer:

```bash
./configure_workspace.sh /path/to/target_repo \
  --id my-app --role app \
  --sibling api=/path/to/api
```

Behavior:

1. Ensure skill installed (or call install first).  
2. Write/merge `skills/.../repo/workspace.env`.  
3. Print next steps: `broker.py index`, `postprocess_summaries.py`, optional summarize.  
4. **Never** commit `workspace.env`.

Idempotent merge: update keys by name, preserve unknown user keys.

### 7.3 Docs to add/update

| Doc | Content |
|-----|---------|
| `docs/workspace_multi_repo.md` | Env keys, single vs multi, KTW-shaped *example* clearly marked example |
| `docs/adjacency_and_nav_resolve.md` | P0-A/C usage |
| Root `README.md` | Link + short “Multi-repo (optional)” section |
| `repo_context/README.md` | Point to workspace.env for machine links; keep prose for humans |

### 7.4 Consumer git hygiene

Skill `repo/.gitignore`:

```gitignore
workspace.env
context_session.json
```

Document: commit `workspace.env.example` only (via skill tree when users vendor the skill). If consumers commit the whole `skills/` folder, example is fine; env is ignored.

---

## 8. Implementation phases

### Phase 0 — Install/config plumbing (do first if tooling)

1. `workspace.env.example` + `repo/.gitignore` update.  
2. `lib/workspace_config.py` loader + unit smoke.  
3. `configure_workspace.sh` + `install.sh` hooks.  
4. Docs skeleton.

### Phase 1 — P0-A postprocess lines

1. `summary_postprocess.resolve_navigation(md, source_path, lang)`.  
2. Wire summarizer + parallel runners.  
3. Batch CLI; run on know_to_win sample; verify `_fetchSettings` lines.  

### Phase 2 — P0-B prompt

1. Edit `prompt_template.txt`.  
2. Optional: synthesize NEXT HOP if missing in postprocess.  

### Phase 3 — P0-C adjacency

1. Import extractors.  
2. Indexer edge write.  
3. `summary_broker adjacent`.  
4. ADJACENT marker inject in postprocess.  

### Phase 4 — P1 cross-repo (optional flag)

1. Route extractors (generic).  
2. `cross_edges` table + CLI.  
3. Document multi-root agent workflow.  
4. Validate on KTW Flutter↔API with user-local `workspace.env` only.

---

## 9. Agent workflow after v1 (token path)

**Single repo:**

```text
summary_broker search/read
  → ADJACENT / NEXT HOP
  → broker read --symbol   (lines trusted if postprocessed)
```

**Multi-repo (workspace.env set):**

```text
summary_broker read client_file
  → ADJACENT includes cross: api::path
  → open sibling root (IDE multi-root)
  → sibling summary_broker read | search route
  → sibling broker read --symbol
```

---

## 10. Verification matrix

| Check | Single-repo OSS user | KTW dual-repo |
|-------|----------------------|---------------|
| Install without workspace.env | Works | Works |
| Postprocess without tree-sitter | Regex outline fallback | Same |
| Postprocess with tree-sitter | Better symbols/lines | Same |
| `adjacent` on leaf file | imports only | same |
| `adjacent` on hub file | importers listed | same |
| Cross CLI with CROSS=0 | No-op / empty | Same |
| Cross with siblings + CROSS=1 | N/A or empty if no routes | Flutter path links to API file when resolvable |
| No absolute KTW paths in git | Pass | Pass |

---

## 11. State lifecycle summary (new persisted elements)

| Element | CREATE | READ | UPDATE | REINDEX | DELETE |
|---------|--------|------|--------|---------|--------|
| `workspace.env` | configure script / manual copy | `workspace_config.load` | edit keys | n/a | user deletes; tools degrade to single-repo |
| `file_edges` | indexer | adjacent / inject | re-index file | full index | src removed from scan |
| `cross_edges` | index if flag | cross CLI / inject | re-index | full rebuild | flag off or sibling gone → clear |
| Postprocessed md lines | postprocess | agents | re-summarize + postprocess | batch postprocess | md deleted with prune |

Derived only from source + local config; **no** edge is authoritative without re-extract.

---

## 12. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Package import resolution wrong | Prefix map in workspace.env; leave unresolved as external labels |
| Postprocess breaks markdown structure | Only rewrite NAVIGATION bullets; marker blocks for ADJACENT |
| Users commit machine paths | gitignore + example-only in template; docs scream LOCAL |
| Parallel summarizer skips postprocess | Parent process postprocesses after each OK write (same as manifest merge ownership) |
| Cross false positives on string paths | Require minimum path shape; confidence flag; show as hint not fact |

---

## 13. Recommended ship order (this implementation wave)

1. **Install artifacts + `workspace_config` + configure script** (unblocks multi-repo without lying about KTW).  
2. **P0-A postprocess** (immediate quality on existing know_to_win summaries).  
3. **P0-C adjacency** (import ± reverse).  
4. **P0-B prompt** (cheap; re-summarize selectively later).  
5. **P1 cross contracts** when 1–3 are green.

---

## 14. Open decisions (resolve at implement time)

| Decision | Default proposal |
|----------|------------------|
| `workspace.env` vs `workspace.local.json` | **env** (stdlib, familiar) |
| Edges in `index.sqlite` vs separate file | **`adjacency.sqlite` separate** from symbols; still **one pair of DBs per repo** |
| Multi-repo data layout | **Separate summary + symbol + adjacency stores per adjacent repo** (mandatory) |
| Auto-copy example → `workspace.env` on install | **Yes if missing** |
| Inject ADJACENT into md vs CLI-only | **Both**: CLI always; inject markers for agent-read md |
| Cross-repo in first PR | **No** — Phase 4 after adjacency |

---

## 15. References (in-repo)

- Summaries prompt: `agent_token_usage_optimization/summaries/prompt_template.txt` (NAVIGATION approx lines)  
- Outline: `lib/outline.py` (tree-sitter + regex)  
- Install: `install.sh` (shared vs template)  
- Provider docs: `docs/using_agy_gemini_flash.md`, `docs/using_grok.md`  
- Prior discussion themes: secondary research, adjacency not graph DB, Flutter+API contract edges  

---

## 16. Next action

Implement **Phase 0 + Phase 1** first (workspace install artifacts + line postprocess), then adjacency. Do not re-LLM the full know_to_win corpus unless validating prompt changes (Phase 2).
