# Active-only publication filter (2026-11-25)

Problem: `normalized()` stopped every release with "Record budget or empty
catalog" because non-deleted registry records (74k) exceed `MAX_RECORDS=60000`.

Owner decision: publish only active servers; do not raise the cap.

Readings considered:
1. Status filter only (`active`): 72,884 records, still over the cap. Rejected.
2. Active + recency window. Counts on the 2026-11-25 capture: 30 d 34,277;
   60 d 47,310; 90 d 55,939. Weekly publishing is accelerating (11.9k in the
   last week), so 60-90 d would hit the cap within weeks. Chosen: 30 d, which is
   the pipeline's existing "active" freshness threshold.

Assumptions (recorded instead of asking):
- "Inactive" means not updated within the window; the registry has no separate
  inactive status.
- Excluded, previously published routes stay as noindex dated references rather
  than being removed (no live URL breaks; the existing lifecycle already does this
  for deleted records).
- The cap and the empty-catalog guard stay fail-closed; a headroom warning at 85%
  gives notice before a hard failure.

Success criteria: tests in `tests/test_publication_filter.py`; offline build of
the 2026-11-25 capture passes `verify_package` with no missing historical routes;
production `workflow_dispatch` passes.
