#!/usr/bin/env python3
"""The MCP Index — data builder.

Pulls the OFFICIAL Model Context Protocol registry (registry.modelcontextprotocol.io),
dedupes to the latest version per server, derives category + freshness + transport,
and writes data.json. Authoritative source, no fabricated signals — every field
comes from the registry response.
"""
import json, os, re, html, shutil, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = "https://mcp.kymatalabs.com"
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


def slugify(name):
    """URL-safe slug from a server name. MUST match app.js slugify()."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "server"


def assign_slugs(servers):
    """Stable unique slug per server (collisions get a -2, -3, … suffix)."""
    used = {}
    for s in servers:
        base = slugify(s.get("name"))
        slug = base
        n = 1
        while slug in used:
            n += 1
            slug = f"{base}-{n}"
        used[slug] = True
        s["slug"] = slug
    return servers


def _fmt_days(d):
    if d is None:
        return "—"
    if d < 1:
        return "today"
    if d < 2:
        return "1d ago"
    if d < 30:
        return f"{round(d)}d ago"
    if d < 365:
        return f"{round(d/30)}mo ago"
    return f"{round(d/365)}y ago"


def _fmt_date(iso):
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %-d, %Y")
    except Exception:
        return "—"


def generate_details(data, out_dir=None):
    """Static-generate /s/<slug>/index.html for every server — the SEO surface.
    Reuses the hub's exact header/nav/footer/theme (style.css). Shared head/footer
    built once for speed; only the per-server body is templated in the loop.
    """
    out_dir = out_dir or HERE
    servers = assign_slugs(data.get("servers", []))
    s_root = os.path.join(out_dir, "s")
    if os.path.isdir(s_root):
        shutil.rmtree(s_root)  # avoid orphaned pages from renamed/removed servers
    os.makedirs(s_root, exist_ok=True)

    # built once — shared chrome
    head_top = (
        '<!DOCTYPE html><html lang="en"><head>\n'
        '<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
    )
    head_static = (
        '<meta name="theme-color" content="#e7edf3">\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700;800&family=Hanken+Grotesk:wght@300;400;500&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">\n'
        '<link rel="icon" href="/favicon.svg">\n'
        '<link rel="stylesheet" href="/style.css">\n'
        '<script>(function(){try{var t=localStorage.getItem("theme");'
        'if(!t){t=(window.matchMedia&&window.matchMedia("(prefers-color-scheme:dark)").matches)?"dark":"light";}'
        'document.documentElement.dataset.theme=t;}catch(e){}})();</script>\n'
    )
    nav = (
        '</head><body><canvas id="mesh" aria-hidden="true"></canvas>\n'
        '<nav id="nav"><div class="wrap nav-in">\n'
        '<a class="brand" href="/"><span class="mark"><svg width="24" height="24" viewBox="0 0 24 24" fill="none">'
        '<circle cx="5" cy="6" r="2.2" fill="#1d6fe0"/><circle cx="19" cy="9" r="2.2" fill="#1d6fe0"/>'
        '<circle cx="12" cy="18" r="2.2" fill="#0891b2"/><path d="M5 6 L19 9 M19 9 L12 18 M12 18 L5 6" stroke="#1d6fe0" stroke-width="1" opacity=".5"/></svg></span>'
        'The MCP Index <span class="by">// Kymata Labs</span></a>\n'
        '<div class="nav-links"><a href="/#index">Browse</a><a href="https://kymatalabs.com/" class="hidem">Kymata Labs ↗</a>'
        '<button class="themebtn" id="themebtn" type="button" aria-label="Toggle dark mode" title="Toggle theme">'
        '<svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
        '<svg class="moon" viewBox="0 0 24 24" fill="currentColor"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg></button>'
        '</div></div></nav>\n'
    )
    footer = (
        '<footer><div class="wrap"><span class="mono" style="color:var(--node-soft)">How it\'s made</span>'
        '<h2>The registry of record, made <em>browsable.</em></h2>'
        '<p>The MCP Index pulls the <a class="inl" href="https://registry.modelcontextprotocol.io/" target="_blank" rel="noopener">official Model Context Protocol registry</a> '
        'every day, dedupes to the latest version of each server, infers a category, and checks freshness. '
        'It\'s the registry\'s own data, made fast to search and pleasant to read, by the agent stack that runs '
        '<a class="inl" href="https://kymatalabs.com/" target="_blank" rel="noopener">Kymata Labs</a>.</p>'
        '<div class="foot-row"><span>Updated daily from the official registry</span>'
        '<span>© 2026 Kymata Labs · The MCP Index</span><a href="https://kymatalabs.com/">kymatalabs ↗</a></div></div></footer>\n'
    )
    theme_js = (
        '<script>'
        '(function(){var cv=document.getElementById("mesh");if(!cv)return;'
        'if(window.matchMedia&&window.matchMedia("(prefers-reduced-motion:reduce)").matches)return;'
        'var ctx=cv.getContext("2d"),W=0,H=0,dpr=Math.min(window.devicePixelRatio||1,2),nodes=[],raf,COL;'
        'function rt(){var d=document.documentElement.dataset.theme==="dark";'
        'COL=d?{line:"61,139,242",node:"118,174,246",hub:"34,184,214"}:{line:"29,111,224",node:"29,111,224",hub:"8,145,178"};}'
        'function size(){W=cv.clientWidth;H=cv.clientHeight;cv.width=W*dpr;cv.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);build();}'
        'function build(){var c=Math.max(20,Math.min(48,Math.round(W*H/30000)));nodes=[];for(var i=0;i<c;i++)nodes.push({x:Math.random()*W,y:Math.random()*H,vx:(Math.random()-.5)*.22,vy:(Math.random()-.5)*.22,r:Math.random()<.18?2.6:1.6,hub:Math.random()<.18});}'
        'var LINK=132;function frame(){ctx.clearRect(0,0,W,H);for(var i=0;i<nodes.length;i++){var a=nodes[i];a.x+=a.vx;a.y+=a.vy;if(a.x<0||a.x>W)a.vx*=-1;if(a.y<0||a.y>H)a.vy*=-1;}'
        'for(var i=0;i<nodes.length;i++)for(var j=i+1;j<nodes.length;j++){var a=nodes[i],b=nodes[j],dx=a.x-b.x,dy=a.y-b.y,d=Math.sqrt(dx*dx+dy*dy);if(d<LINK){var o=(1-d/LINK)*.3;ctx.strokeStyle="rgba("+COL.line+","+o.toFixed(3)+")";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();}}'
        'for(var i=0;i<nodes.length;i++){var a=nodes[i];ctx.beginPath();ctx.arc(a.x,a.y,a.r,0,6.2832);ctx.fillStyle=a.hub?"rgba("+COL.hub+",.9)":"rgba("+COL.node+",.65)";ctx.fill();}raf=requestAnimationFrame(frame);}'
        'rt();size();window.addEventListener("resize",size);window.addEventListener("themechange",rt);'
        'document.addEventListener("visibilitychange",function(){if(document.hidden)cancelAnimationFrame(raf);else raf=requestAnimationFrame(frame);});raf=requestAnimationFrame(frame);})();'
        '(function(){var b=document.getElementById("themebtn");if(!b)return;function set(t){document.documentElement.dataset.theme=t;try{localStorage.setItem("theme",t);}catch(e){}'
        'var m=document.querySelector(\'meta[name="theme-color"]\');if(m)m.setAttribute("content",t==="dark"?"#0a1320":"#e7edf3");window.dispatchEvent(new Event("themechange"));}'
        'b.addEventListener("click",function(){set(document.documentElement.dataset.theme==="dark"?"light":"dark");});})();'
        '</script></body></html>'
    )

    e = html.escape

    def attr(v):
        return html.escape(str(v if v is not None else ""), quote=True)

    count = 0
    for s in servers:
        slug = s["slug"]
        title = s.get("title") or s.get("name")
        name = s.get("name") or ""
        desc = (s.get("description") or "").strip()
        cat = s.get("category") or "Other"
        transport = s.get("transport") or "Unknown"
        health = s.get("health") or "unknown"
        version = s.get("version") or "—"
        ud = s.get("updated_days")
        regs = s.get("registries") or []
        repo = safe_url(s.get("repository"))
        web = safe_url(s.get("website"))
        canon = f"{SITE}/s/{slug}"

        page_title = f"{title} — MCP server · The MCP Index"
        meta_desc = (desc or f"{title} is a {transport.lower()} Model Context Protocol (MCP) server in the {cat} category.")
        if len(meta_desc) > 158:
            meta_desc = meta_desc[:155].rstrip() + "…"

        # JSON-LD: BreadcrumbList + SoftwareApplication
        sw = {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": title,
            "identifier": name,
            "applicationCategory": "DeveloperApplication",
            "applicationSubCategory": cat,
            "operatingSystem": "Cross-platform",
            "softwareVersion": version,
            "description": desc or meta_desc,
            "url": canon,
            "isAccessibleForFree": True,
            "publisher": {"@type": "Organization", "name": "Kymata Labs", "url": "https://kymatalabs.com/"},
        }
        if repo:
            sw["codeRepository"] = repo
        if web:
            sw["sameAs"] = [web]
        if s.get("published_at"):
            sw["datePublished"] = s["published_at"]
        if s.get("updated_at"):
            sw["dateModified"] = s["updated_at"]
        crumbs = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"},
                {"@type": "ListItem", "position": 2, "name": "The MCP Index", "item": SITE + "/#index"},
                {"@type": "ListItem", "position": 3, "name": title, "item": canon},
            ],
        }
        ld = json.dumps([crumbs, sw], separators=(",", ":"))

        head_dyn = (
            f"<title>{e(page_title)}</title>\n"
            f'<meta name="description" content="{attr(meta_desc)}">\n'
            f'<link rel="canonical" href="{attr(canon)}">\n'
            f'<meta property="og:title" content="{attr(title + " — MCP server")}">\n'
            f'<meta property="og:description" content="{attr(meta_desc)}">\n'
            f'<meta property="og:type" content="website">\n'
            f'<meta property="og:url" content="{attr(canon)}">\n'
            f'<meta property="og:image" content="{SITE}/og.png">\n'
            f'<meta name="twitter:card" content="summary_large_image">\n'
            f'<meta name="twitter:title" content="{attr(title + " — MCP server")}">\n'
            f'<meta name="twitter:description" content="{attr(meta_desc)}">\n'
            f'<meta name="twitter:image" content="{SITE}/og.png">\n'
            f'<script type="application/ld+json">{ld}</script>\n'
        )

        new_badge = ' <span class="new">New this week</span>' if s.get("is_new") else ""
        reg_html = "".join(f"<span>{e(r)}</span>" for r in regs) or '<span>—</span>'
        actions = []
        if repo:
            actions.append(f'<a class="primary" href="{attr(repo)}" target="_blank" rel="noopener nofollow">Repository ↗</a>')
        if web:
            actions.append(f'<a class="ghost" href="{attr(web)}" target="_blank" rel="noopener nofollow">Website ↗</a>')
        actions.append(f'<a class="ghost" href="https://registry.modelcontextprotocol.io/?search={urllib.parse.quote(name)}" target="_blank" rel="noopener nofollow">Registry entry ↗</a>')
        actions_html = "".join(actions)

        desc_html = f'<p class="d-desc">{e(desc)}</p>' if desc else ""

        body = (
            '<main class="detail"><div class="wrap">'
            '<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Home</a><span class="sep">/</span>'
            '<a href="/#index">The MCP Index</a><span class="sep">/</span>'
            f'<span>{e(title)}</span></nav>'
            '<a class="back" href="/">← Back to the index</a>'
            '<div class="d-head"><div class="d-title">'
            f'<h1>{e(title)}{new_badge}</h1>'
            f'<div class="d-name">{e(name)}</div></div></div>'
            f'{desc_html}'
            f'<div class="d-actions">{actions_html}</div>'
            '<div class="d-grid">'
            f'<div class="cell"><span>Category</span><b>{e(cat)}</b></div>'
            f'<div class="cell"><span>Transport</span><b>{e(transport)}</b></div>'
            f'<div class="cell"><span>Health</span><b><span class="d {e(health)}"></span>{e(health)}</b></div>'
            f'<div class="cell"><span>Last updated</span><b>{e(_fmt_days(ud))}</b></div>'
            f'<div class="cell"><span>Version</span><b>{e(version)}</b></div>'
            f'<div class="cell reg"><span>Registries</span><b>{reg_html}</b></div>'
            '</div>'
            '<div class="d-meta">'
            f'<div>Published · <b>{e(_fmt_date(s.get("published_at")))}</b></div>'
            f'<div>Updated · <b>{e(_fmt_date(s.get("updated_at")))}</b></div>'
            f'<div>Source · <b>official Model Context Protocol registry</b></div>'
            '</div></div></main>'
        )

        page = head_top + head_dyn + head_static + nav + body + footer + theme_js
        d = os.path.join(s_root, slug)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(page)
        count += 1

    write_sitemap(servers, out_dir)
    write_llms_txt(data, out_dir)
    print(f"generated {count} detail pages under s/", file=sys.stderr)
    return count


def write_sitemap(servers, out_dir=None):
    out_dir = out_dir or HERE
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
             f'  <url><loc>{SITE}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>']
    for s in servers:
        lines.append(f'  <url><loc>{SITE}/s/{s["slug"]}</loc><changefreq>weekly</changefreq><priority>0.6</priority></url>')
    lines.append('</urlset>')
    with open(os.path.join(out_dir, "sitemap.xml"), "w") as f:
        f.write("\n".join(lines) + "\n")


def write_llms_txt(data, out_dir=None):
    out_dir = out_dir or HERE
    sc = data.get("server_count", len(data.get("servers", [])))
    txt = f"""# The MCP Index

> A living, searchable index of every server in the official Model Context Protocol (MCP) registry — categorized, freshness-tracked, and updated daily by an AI agent at Kymata Labs.

The MCP Index is the registry of record made browsable. It pulls the official MCP registry (registry.modelcontextprotocol.io) once per day, dedupes to the latest version of each server, infers a category, and computes freshness (active / maintained / stale) from each server's last update. No data is hand-maintained or fabricated — every field comes from the registry response.

- Servers indexed: {sc}
- Source: registry.modelcontextprotocol.io (official MCP registry)
- Update cadence: daily
- Publisher: Kymata Labs (https://kymatalabs.com/)
- License of underlying data: the official MCP registry

## Routes

- `/` — the searchable hub: full-text search, category / transport / health filters, sortable columns, "new this week".
- `/s/<slug>` — one static page per server, where `<slug>` is the URL-safe form of the server's registry name. Each page carries the server's full data (title, description, version, transport, registries, category, health, published/updated dates) plus outbound links to its repository and website.
- `/sitemap.xml` — every page, regenerated each build.

## Notes for agents

- Slugs are lowercase, non-alphanumeric runs collapsed to a single hyphen (e.g. `io.github.acme/server` → `io-github-acme-server`).
- "Health" is freshness-derived: active ≤30d, maintained ≤120d, stale otherwise.
- To search programmatically, the hub supports `/?q=<term>`.
"""
    with open(os.path.join(out_dir, "llms.txt"), "w") as f:
        f.write(txt)


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
    # static-generate the SEO surface: /s/<slug> detail pages + sitemap + llms.txt
    generate_details(data)
    # resilience guard: the registry has thousands of servers; a run that returns far
    # fewer means the API hiccupped mid-pagination. Refuse to publish a gutted index —
    # fail so the cron skips commit+deploy and the last-good page stays live.
    if len(items) < 500:
        print(f"GUARD: only {len(items)} servers (< 500); refusing to publish a partial index.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
