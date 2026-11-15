# Release procedure

Status: no selected submission, full-data prediction, second-laptop reproduction
or upload is established by this E5 work. Execute restricted-data steps locally;
do not expose their contents or detailed diagnostics to hosted AI tools.

1. Confirm the merged E2/E5 integration at the frozen revision, obtain owner
   sign-off on the actual configuration and the documented unknown-team
   live-play policy, and run the synthetic checks. Do not select thresholds or
   a candidate on public-window scores.
2. A repository admin configures required PR review and the synthetic CI checks
   on main. E5 inspected main on 2026-11-10: unprotected; the connected account
   has push/triage rights but no admin rights. Configuration was not changed.
3. Freeze a clean committed code revision and JSON config. Record purpose,
   evidence source and parameter-selection method using the
   [experiment template](experiments/TEMPLATE.md). Every owner confirms their
   [technical-document](TECHNICAL_DOCUMENT.md) section and training-data provenance.
4. E1 runs the full pipeline locally using [TEAM_README.md](../../TEAM_README.md),
   exporting the registered `<team_name>.csv` plus a private manifest in `runs/`.
   E4 runs `scripts/check_solution.py` against that exact CSV. Preserve the file,
   manifest, input/config identities and output hash locally.
5. E5/E1 independently regenerate from the same commit/config/inputs on a second
   authorised laptop, using a fresh checkout and pinned environment. Compare
   CSV SHA-256 hashes exactly. Runtime and platform may differ; CSV bytes must
   match. Record only completion status and code/config references in handoffs;
   keep detailed manifests local. A same-laptop test does not satisfy this gate.
6. Audit tracked files and history before public release. The CI filename guard
   catches common artifact paths, not every possible disclosure and not history.
   Inspect the audit locally without sending restricted content to AI tools.
   A maintainer makes the repository public only after review. The inspected
   team repository is currently private; do not advertise a public submission yet.
7. Name the final Markdown/PDF after the registered team and remove draft
   status once claims have been verified. Include final reproduction commands,
   code/config identity, possession rules, assets, training provenance and limits.
   The registered team name is not established in shared context; do not invent it.
8. The designated human submitter uploads the exact validated CSV, public
   repository URL and team-named document via the emailed registration form.
   Record confirmation and the frozen version. Do not overwrite this release
   with later experiments. Check organiser deadline updates through registration.

Open dependencies: frozen integrated revision/config, admin protection/public visibility,
local full-data execution, independent second-laptop hash agreement, owner sign-off,
registered team name and human upload confirmation. Format checks establish no
competition accuracy improvement.
