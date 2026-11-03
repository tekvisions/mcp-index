MCP legacy refresh publication hold
===================================

The 60-page collector and destructive detail generator may replace an incomplete catalog and remove routes. The scheduled workflow remains enabled at 09:32 UTC daily, but now fails with exit 2 before collection, commits, uploads or IndexNow. Manual Python entrypoints have the same hold. There is no environment override or automatic expiry. Existing data and production stay in place.

The source git.deploymentEnabled=false prevents a guard-only Git push from launching an unreviewed Vercel build, matching the other fleet repositories. CSP and access settings are unchanged.

Resume only after integrating and validating the cursor-complete collector, preserving the union of observed historic/current routes, proving snapshot/client binding, validating the bounded daily package path and checking the provider release. Replace this temporary hold through a reviewed source change; do not merely remove it to rerun the legacy pipeline.
