# Git action count reconciliation

This record was created before applying the approved Git index changes. The source of truth is the frozen `GIT_ACTION_INVENTORY.json`, cross-checked against `GIT_TRACKING_POLICY.md`, `PROPOSED_GIT_ACTIONS.md`, and `git ls-files`.

| Item | Count |
| --- | ---: |
| Explicit `TRACK` paths | 282 |
| Proposed `git add` commands | 281 |
| `TRACK` paths already tracked and requiring no add | 1 |

The exact no-action path is **`.gitignore`**. It is already tracked by Git and unchanged in the working tree. It is present in `TRACK` to retain the repository ignore policy but correctly has no proposed `git add` command. Every other `TRACK` path has exactly one explicit proposed add command; there are no unexplained paths or duplicate commands.

**Verification result: `GIT_ACTION_COUNTS_RECONCILED`.** The 12 `UNTRACK_KEEP_LOCAL` paths and 304 `REVIEW_BEFORE_UNTRACK` paths are disjoint from the approved add list. Index actions must remain limited to the explicit 12 cached bytecode removals, the 281 approved add commands, and staging this newly requested reconciliation record. No scientific raw file is to be physically deleted.
