MCP legacy refresh publication hold — reviewed replacement released
==================================================================

On 2026-11-06 the separate bounded pipeline was released from source
1951a30799d35736bf22e432d735b473f1a9f540. The legacy Python entrypoints remain
held, with no environment bypass. The daily workflow now uses registry_collect.py,
release_pipeline.py and publish_release.py. See RELEASE_ACCEPTANCE.md for the
verified production identity, route preservation and remaining limits.

The following describes the superseded workflow hold and remains as historical
context for why the legacy collector must not be used:

The 60-page collector and destructive detail generator may replace an incomplete catalog and remove routes. The scheduled workflow remains enabled at 09:32 UTC daily, but now fails with exit 2 before collection, commits, uploads or IndexNow. Manual Python entrypoints have the same hold. There is no environment override or automatic expiry. Existing data and production stay in place.

The source git.deploymentEnabled=false prevents a guard-only Git push from launching an unreviewed Vercel build, matching the other fleet repositories. CSP and access settings are unchanged.

Resume only after integrating and validating the cursor-complete collector, preserving the union of observed historic/current routes, proving snapshot/client binding, validating the bounded daily package path and checking the provider release. Replace this temporary hold through a reviewed source change; do not merely remove it to rerun the legacy pipeline.
