# Reviewed registry pipeline: 2026-11-06

The existing MCP Index public site was corrected using the bounded replacement
pipeline. This is acceptance of the described changes, not certification of the
entire site, every third-party server, indexing or citation outcomes.

- Source: `1951a30799d35736bf22e432d735b473f1a9f540`.
- Full cursor capture: 593 pages, 59,294 latest-version records, terminal cursor
  empty, including 1,542 registry-deleted records. Capture ended
  `2026-11-06T19:40:01.441438+00:00`; moving-registry traversal is not an atomic census.
- Searchable snapshot: 57,752 records and 482 static catalog pages. All 2,285
  previously public detail paths were retained and checked over HTTP. Deleted
  historical entries remain explicitly labelled and noindex, without stale
  installation commands.
- Exact accepted deployment: `dpl_3ppJeGrUCDibpZi4WUwvtndmCmuL`,
  `mcp-index-ewnx4a3oq-techtalevisions-projects.vercel.app`, promoted to
  <https://mcp.kymatalabs.com/>.
- Package SHA-256:
  `95eeead4477cbd84c06e5f708325daf0312adaf0ab091578374228c5bcaa9c82`.
- Candidate: 2,316 HTTP checks passed. Public verification checked exact static
  bytes, stratified current/deleted detail responses, headers, and a real 404.
  The original five audit pages were separately recollected from the canonical host.
- Source tests: 53 Python and 9 Node tests. Native CI completed full capture,
  bounded packaging and candidate deployment/verification at
  <https://github.com/tekvisions/mcp-index/actions/runs/42287747740>.
- Actual local publisher then verified the same candidate again, durably pushed
  route state before promotion (`7cc2e3404aa450633bceb13f17c640c79e760c90`), checked
  canonical public output and committed confirmation
  (`b3194b58812512af8d00a9aa50b8be68aced35fa`).
- Chromium browser checks: 390x844 pagination, empty search/reset, dark theme;
  1280x800 search-to-detail; raw catalog with JavaScript disabled; Enter-key
  pagination; final canonical page and settled statistics. Physical iOS/Android
  and field performance were not tested by this release.

## Operations

The existing 09:32 UTC daily schedule now uses the reviewed workflow. Its future
scheduled runs are not claimed as already observed. Manual runs default to
candidate-only; explicit promotion is main-only. Git-triggered Vercel deployments
remain disabled, and legacy collection/deploy/IndexNow entrypoints remain held.
The reviewed publisher does not submit IndexNow or install third-party packages.

The collector, artifact and deployment limits deliberately fail closed rather
than truncate. Current limits include 60,000 records, 1,600 deployed files and
220 MB output. Capacity increases require a new measured package review.

Route history and compact prior catalog state are content-bound, semantically
checked and committed before promotion. A failed/non-fast-forward state push
prevents promotion. A pending deployment that is already public stops the next
release until the retained exact package is reverified and its confirmation is
committed. Reconcile before retrying ambiguous mutations; do not erase pending
state, weaken verification, or rerun the legacy collector. Before rollback the
publisher checks production still points to its own candidate. Vercel provides
no compare-and-swap transaction here, so a narrow inspect-to-mutate race remains.

All access settings, canonical ownership and CSP were preserved. Candidate
provider noindex is crawler exclusion, not authentication. The public correction
does not waive separate privacy, commercial or launch gates for other projects.

## Publication filter: 2026-11-25

The official registry outgrew the 60,000-record budget (76,061 latest-version
records captured on 2026-11-25: 72,884 active, 1,114 deprecated, 2,063 deleted),
so every scheduled release failed closed from 2026-11-09. Owner decision: publish
only active servers and keep the cap.

- Listed: records the registry marks `active` whose latest version was
  updated within the last 30 days of the completed capture (`updatedAt`, else
  `publishedAt`). Constants: `RECENCY_DAYS = 30`, `MAX_RECORDS = 60000` in
  `release_pipeline.py`. Active records alone (72,884) exceed the cap, so the
  recency window is required; 30 days matches the existing "active" freshness
  label and gave 33,698 listed records (56% of the cap) on 2026-11-25.
- Not listed: `deleted`, `deprecated`, and active records last updated more than
  30 days before the capture. Collection is unchanged (the full traversal is still
  captured and hash-bound), so counts per exclusion reason are published in
  `data.json` and `snapshot.json` (`publication_filter`, `deleted_records`,
  `deprecated_records`, `outside_window_records`).
- Lifecycle: no published URL is removed. A previously published identity the
  filter excludes is served at the same `/s/<slug>/` URL as a labelled,
  `noindex,follow` historical reference (`deleted_reference`,
  `deprecated_reference` with the publisher's status message, or
  `dormant_reference` with its last registry update date), outside the sitemap and
  without install commands. If it is updated again it returns to the listing at
  the same slug.
- Guards kept: an empty listing raises (`Empty catalog ...`) and the previous
  release stays; more than `MAX_RECORDS` raises (`Record budget exceeded ...`);
  above 85% of the cap the build logs a GitHub warning so the window or capacity
  can be reviewed before it fails. Raising the cap still needs a measured package
  review. Offline build of the 2026-11-25 capture: 74,321 routes (all 59,615
  historical routes kept), detail function 65 MB of the 160 MB budget.
