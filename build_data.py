#!/usr/bin/env python3
"""The MCP Index — data builder.

Pulls the OFFICIAL Model Context Protocol registry (registry.modelcontextprotocol.io),
dedupes to the latest version per server, derives category + freshness + transport,
and writes data.json. Authoritative source, no fabricated signals — every field
comes from the registry response.
"""
import json, os, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
MAX_PAGES = 60  # safety cap (100/page)

CATEGORY_RULES = [
    ("Data & DB",       ["database", "postgres", "mysql", "mongo", "redis", "sql", "duckdb", "snowflake", "bigquery", "supabase", "sqlite"]),
    ("Web & Search",    ["search", "web", "scrape", "scraping", "crawl", "browser", "fetch", "google", "bing", "tavily", "serp"]),
    ("Dev Tools",       ["github", "gitlab", "git ", "jira", "linear", "code", "developer", "ci/cd", "devtool", "ide", "lsp", "terminal", "shell"]),
    ("Productivity",    ["slack", "discord", "email", "gmail", "notion", "calendar", "teams", "telegram", "todo", "task", "obsidian", "confluence"]),
    ("Files & Storage", ["file", "filesystem", "storage", "s3", "drive", "dropbox", "bucket", "document"]),
    ("Finance",         ["payment", "stripe", "finance", "trading", "crypto", "stock", "bank", "invoice", "accounting"]),
    ("AI & Models",     ["llm", "image", "video", "model", "agent", "embedding", "rag", "vector", "openai", "anthropic", "huggingface", "inference"]),
    ("Cloud & DevOps",  ["cloud", "aws", "gcp", "azure", "kubernetes", "docker", "devops", "terraform", "vercel", "cloudflare", "deploy"]),
    ("Maps & Travel",   ["map", "location", "weather", "travel", "flight", "geo", "places"]),
]


def fetch(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "mcp-index"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(1 + attempt)
    return None


def days_since(iso):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    except Exception:
        return None


def safe_url(u):
    """Only allow http(s) URLs from the (untrusted) registry — block javascript:,
    data:, etc. Returns the URL or None."""
    if not u or not isinstance(u, str):
        return None
    u = u.strip()
    if u.lower().startswith(("http://", "https://")):
        return u
    return None


def categorize(text):
    t = (text or "").lower()
    for name, kws in CATEGORY_RULES:
        if any(k in t for k in kws):
            return name
    return "Other"


def transport_of(server):
    if server.get("remotes"):
        return "Remote"
    pkgs = server.get("packages") or []
    if pkgs:
        return "Local"
    return "Unknown"


def registries(server):
    out = []
    for p in (server.get("packages") or []):
        rt = p.get("registryType") or p.get("registry_type")
        if rt:
            out.append(rt)
    if server.get("remotes"):
        out.append("hosted")
    return sorted(set(out))


def main():
    seen = {}   # name -> entry (keep isLatest / newest publishedAt)
    cursor = None
    pages = 0
    while pages < MAX_PAGES:
        url = REGISTRY + "?limit=100" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
        data = fetch(url)
        if not data or "servers" not in data:
            break
        for item in data["servers"]:
            s = item.get("server", {})
            meta = (item.get("_meta") or {}).get("io.modelcontextprotocol.registry/official", {}) or {}
            name = s.get("name")
            if not name:
                continue
            if meta.get("status") and meta.get("status") != "active":
                continue
            cur = {
                "name": name,
                "title": s.get("title") or name.split("/")[-1],
                "description": s.get("description", ""),
                "version": s.get("version"),
                "transport": transport_of(s),
                "registries": registries(s),
                "repository": safe_url((s.get("repository") or {}).get("url") if isinstance(s.get("repository"), dict) else None),
                "website": safe_url(s.get("websiteUrl")),
                "published_at": meta.get("publishedAt"),
                "updated_at": meta.get("updatedAt") or meta.get("publishedAt"),
                "is_latest": bool(meta.get("isLatest")),
            }
            prev = seen.get(name)
            # keep the latest: prefer isLatest, else the most recently updated
            if prev is None:
                seen[name] = cur
            elif cur["is_latest"] and not prev["is_latest"]:
                seen[name] = cur
            elif (cur["updated_at"] or "") > (prev["updated_at"] or "") and not prev["is_latest"]:
                seen[name] = cur
        pages += 1
        cursor = (data.get("metadata") or {}).get("nextCursor")
        if not cursor:
            break

    items = list(seen.values())
    for it in items:
        it["category"] = categorize(it["title"] + " " + it["description"] + " " + it["name"])
        d = days_since(it["updated_at"])
        it["updated_days"] = round(d, 1) if d is not None else None
        if d is None:
            it["health"] = "unknown"
        elif d <= 30:
            it["health"] = "active"
        elif d <= 120:
            it["health"] = "maintained"
        else:
            it["health"] = "stale"
        pd = days_since(it["published_at"])
        it["is_new"] = pd is not None and pd <= 7

    # sort: freshest first (most recently updated)
    items.sort(key=lambda x: x["updated_at"] or "", reverse=True)

    cats = {}
    for it in items:
        cats[it["category"]] = cats.get(it["category"], 0) + 1
    new_this_week = [x["name"] for x in items if x["is_new"]][:12]

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "registry.modelcontextprotocol.io (official MCP registry)",
        "server_count": len(items),
        "new_this_week": len([x for x in items if x["is_new"]]),
        "active_count": len([x for x in items if x["health"] == "active"]),
        "categories": sorted(cats.keys()),
        "category_counts": cats,
        "new_names": new_this_week,
        "servers": items,
    }
    json.dump(data, open(os.path.join(HERE, "data.json"), "w"), indent=2)
    print(f"wrote data.json: {len(items)} servers, {data['new_this_week']} new this week, {data['active_count']} active", file=sys.stderr)
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(main())
