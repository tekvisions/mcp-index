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
