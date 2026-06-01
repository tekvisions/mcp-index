# The MCP Index

**Every Model Context Protocol server, in one living index.** A searchable,
freshness-tracked catalog sourced from the [official MCP registry](https://registry.modelcontextprotocol.io/),
categorized and health-checked, refreshed daily by an AI agent.

A [Kymata Labs](https://kymatalabs-techtalevisions-projects.vercel.app/) product.

## How it works
- `build_data.py` — pulls the official registry (paginated), dedupes to the latest
  version per server, infers category + freshness + transport, writes `data.json`.
  Authoritative source; no fabricated signals.
- `deploy.py` — ships the static site to Vercel via the REST API.
- `.github/workflows/update.yml` — recompute + redeploy daily, no human in the loop.

Static site: `index.html` + `app.js`. No build step.
