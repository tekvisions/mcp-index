#!/usr/bin/env python3
"""The MCP Index — data builder.

Pulls the OFFICIAL Model Context Protocol registry (registry.modelcontextprotocol.io),
dedupes to the latest version per server, derives category + freshness + transport,
and writes data.json. Authoritative source, no fabricated signals — every field
comes from the registry response.
"""
import json, os, re, html, math, shutil, sys, time, urllib.request, urllib.parse
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
    """Stable unique slug per server (collisions get a -2, -3, … suffix).
    IDEMPOTENT: a server that already carries a `slug` keeps it (and reserves it),
    so calling this twice on the same list (main() pre-assigns; generate_details()
    re-calls) can never reassign a different slug — badge files, feed URLs, and
    detail-page embeds therefore reference one and the same slug."""
    used = {}
    # first pass: reserve already-assigned slugs so a later new server can't steal them
    for s in servers:
        if s.get("slug"):
            used[s["slug"]] = True
    for s in servers:
        if s.get("slug"):
            continue
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


def _spark_svg(series, w=720, h=90):
    """Minimal inline-SVG polyline sparkline (no deps). `series` is already oriented
    so a higher value reads as a higher point on the chart. Self-contained: it scales
    to the series' own min/max, so it carries no dependency on an outer total."""
    pts = [v for v in series if isinstance(v, (int, float))]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1
    pad = 6
    n = len(pts)
    coords = []
    for i, v in enumerate(pts):
        x = pad + (w - 2 * pad) * (i / (n - 1))
        y = pad + (h - 2 * pad) * (1 - (v - lo) / span)
        coords.append(f"{x:.1f},{y:.1f}")
    poly = " ".join(coords)
    lx, ly = coords[-1].split(",")
    return (
        f'<svg class="mv-spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
        f'role="img" aria-hidden="true">'
        f'<polyline fill="none" stroke="var(--node)" stroke-width="2.5" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{poly}"/>'
        f'<circle cx="{lx}" cy="{ly}" r="4" fill="var(--node)"/></svg>'
    )


# ── public distribution: feed.json API + embeddable rank badges ──────────────
# Badge generation is CAPPED (see generate_badges) — the registry carries ~2250
# servers and one SVG file each would bloat the repo. feed.json is the full API.

# how many top-ranked badges to emit, on top of every is_new server (which always
# gets one — a freshly-published server is the most likely to want to show its rank).
BADGE_TOP_N = 250
# absolute ceiling on badge files written, so a freak day of thousands of is_new
# servers can never balloon the repo. The cap is documented; the top-ranked set is
# always retained first, then is_new fills the remaining budget.
BADGE_HARD_CAP = 600


def _badge_svg(s: dict) -> str:
    """shields.io-style embeddable rank badge. Left label "MCP Index", right
    "#<rank>" in the mesh node-blue; appends "▲N" when the server climbed
    (rank_delta > 0). Self-contained, theme-neutral, accessible (role/title).
    Character-width estimation keeps the right pill snug without a web font."""
    rank = s.get("rank")
    rank_txt = f"#{rank}" if isinstance(rank, int) else "#—"
    rd = s.get("rank_delta")
    if isinstance(rd, int) and rd > 0:
        rank_txt = f"{rank_txt} ▲{rd}"
    label = "MCP Index"
    name = s.get("name", "") or ""
    title = s.get("title") or name
    # ~6px per char @ 11px Verdana-ish; +pad. Stable, no font metrics needed.
    lw = len(label) * 6 + 18
    rw = len(rank_txt) * 6 + 18
    total = lw + rw
    aria = f"MCP Index — {html.escape(title)} ranked {rank_txt}"
    # unique gradient id per badge. Use the COLLISION-RESOLVED s["slug"] (assign_slugs
    # appends -2/-3… on dupes) rather than re-slugifying the name — so two servers that
    # slugify to the same base never produce a duplicate id. Re-filtered to [a-z0-9-]
    # so the id is always a valid SVG/XML name (defensive; slugify already guarantees it).
    gid = "mi" + (re.sub(r"[^a-z0-9-]", "", s.get("slug") or slugify(name)) or "badge")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" '
        f'role="img" aria-label="{aria}">'
        f'<title>{aria}</title>'
        f'<linearGradient id="{gid}" x2="0" y2="100%">'
        f'<stop offset="0" stop-color="#fff" stop-opacity=".12"/>'
        f'<stop offset="1" stop-opacity=".12"/></linearGradient>'
        f'<rect rx="3" width="{total}" height="20" fill="#555"/>'
        f'<rect rx="3" x="{lw}" width="{rw}" height="20" fill="#1d6fe0"/>'
        f'<rect rx="3" width="{total}" height="20" fill="url(#{gid})"/>'
        f'<g fill="#fff" text-anchor="middle" '
        f'font-family="Verdana,DejaVu Sans,Geneva,sans-serif" font-size="11">'
        f'<text x="{lw/2:.0f}" y="14">{label}</text>'
        f'<text x="{lw + rw/2:.0f}" y="14" font-weight="bold">{html.escape(rank_txt)}</text>'
        f'</g></svg>'
    )


def badge_eligible(servers):
    """The capped badge set: top BADGE_TOP_N by rank PLUS every is_new server,
    bounded by BADGE_HARD_CAP total. Keeps the repo from gaining one SVG per ~2250
    servers while guaranteeing a badge for the entries most likely to embed one
    (top-ranked + just-published). Top-ranked is retained first; is_new fills the
    remaining budget (also rank-ordered) so the set is deterministic and bounded."""
    by_rank = sorted(servers, key=lambda x: x.get("rank") or 10**9)
    chosen = {}
    for s in by_rank[:BADGE_TOP_N]:
        chosen[s["slug"]] = s
    for s in by_rank:  # is_new in rank order — deterministic fill of the remaining budget
        if len(chosen) >= BADGE_HARD_CAP:
            break
        if s.get("is_new"):
            chosen[s["slug"]] = s
    return list(chosen.values())


def generate_badges(servers, out_dir=None) -> set:
    """Write a static /badge/<slug>.svg for the capped eligible set (mirrors the
    detail-page generation; static-deployable, refreshed each daily build).
    Returns the set of slugs that got a badge (so detail pages can gate the embed
    block to only those that actually have a badge file)."""
    out_dir = out_dir or HERE
    b_dir = os.path.join(out_dir, "badge")
    if os.path.isdir(b_dir):
        shutil.rmtree(b_dir)  # drop badges for servers that fell out of the cap
    os.makedirs(b_dir, exist_ok=True)
    eligible = badge_eligible(servers)
    written = set()
    for s in eligible:
        # slug comes from slugify() (only [a-z0-9-], never "." or "/"), but re-clamp
        # to [a-z0-9-] here so the filename is provably traversal-free at the write site
        # — no registry-controlled name can escape badge/ regardless of upstream changes.
        slug = re.sub(r"[^a-z0-9-]", "", s.get("slug") or "") or "server"
        with open(os.path.join(b_dir, f"{slug}.svg"), "w") as f:
            f.write(_badge_svg(s))
        written.add(slug)
    print(f"  generated {len(written)} rank badges in /badge/ "
          f"(cap: top {BADGE_TOP_N} by rank + all is_new)", file=sys.stderr)
    return written


def generate_feed(data, badge_slugs=None, out_dir=None) -> None:
    """Write feed.json — a documented, stable-schema public API subset of the
    board (read-only data already public on the page / in data.json; no secrets).
    Includes ALL ranked servers (the full directory is already public). The per-item
    `badge` URL is emitted ONLY for the capped set that actually has a badge file
    (`badge_slugs`); other servers carry `"badge": null` so consumers never get a
    dead link."""
    out_dir = out_dir or HERE
    badge_slugs = badge_slugs if badge_slugs is not None else set()
    servers = sorted(data.get("servers", []), key=lambda x: x.get("rank") or 10**9)

    def _item(s):
        slug = s.get("slug") or slugify(s.get("name"))
        return {
            "rank": s.get("rank"),
            "name": s.get("title") or s.get("name"),
            "server_id": s.get("name"),
            "category": s.get("category"),
            "updated_at": s.get("updated_at"),
            "rank_delta": s.get("rank_delta"),
            "url": f"{SITE}/s/{slug}/",
            "badge": f"{SITE}/badge/{slug}.svg" if slug in badge_slugs else None,
        }

    feed = {
        "$schema_version": "1",
        "generator": "The MCP Index (Kymata Labs)",
        "generated_at": data.get("generated_at"),
        "site": SITE,
        "docs": f"{SITE}/#how",
        "license": "Data derived from the official Model Context Protocol registry; attribution to The MCP Index (mcp.kymatalabs.com) appreciated.",
        "count": len(servers),
        "items": [_item(s) for s in servers],
        "movers": data.get("movers", []),
    }
    with open(os.path.join(out_dir, "feed.json"), "w") as f:
        json.dump(feed, f, indent=2)
    print(f"  wrote feed.json: {len(servers)} servers", file=sys.stderr)


# ── derivation helpers for the detail deep-dives (all from real registry fields) ──

# reverse-DNS-ish registry names → a human owner/namespace.
#   io.github.Acme/server   → ("Acme", "github")
#   com.mambabuilt/suite    → ("mambabuilt", "com")
#   dev.goodbarber/x        → ("goodbarber", "dev")
def owner_of(name):
    if not name:
        return None, None
    ns = name.split("/", 1)[0]
    parts = ns.split(".")
    if name.startswith("io.github.") and len(parts) >= 3:
        return parts[2], "github"
    if len(parts) >= 2:
        # com.mambabuilt → mambabuilt ; ai.foo.bar → bar
        return parts[-1], parts[0]
    return ns, None


# best-guess package coordinate for an install snippet: the trailing path
# segment of the registry name (after the namespace), else the title.
def _pkg_guess(name, title):
    if name and "/" in name:
        seg = name.split("/", 1)[1].strip("/")
        if seg:
            return seg
    return (title or "server").strip()


# Human-readable, copy-pasteable install/config snippet derived from the
# registry TYPE + name. No fabricated package versions — these are the canonical
# invocation shapes the MCP ecosystem uses, with the inferred coordinate.
def install_snippet(server):
    regs = server.get("registries") or []
    name = server.get("name") or ""
    title = server.get("title") or name
    web = safe_url(server.get("website"))
    pkg = _pkg_guess(name, title)
    if "npm" in regs:
        return ("npx", "npm", f"npx -y {pkg}",
                "Run directly with npx, or add to your client's mcpServers config.")
    if "pypi" in regs:
        return ("uvx", "PyPI", f"uvx {pkg}",
                "Run with uv (uvx), or pip install into your environment.")
    if "oci" in regs:
        return ("docker", "OCI image", f"docker run -i --rm {pkg}",
                "Pull and run the published container over stdio.")
    if "mcpb" in regs:
        return ("mcpb", "MCP Bundle", f"# install the .mcpb bundle for “{title}”",
                "Distributed as an MCP Bundle — install via your client's bundle loader.")
    if "nuget" in regs:
        return ("dotnet", "NuGet", f"dnx {pkg}",
                "Run the published .NET tool.")
    if "hosted" in regs or server.get("transport") == "Remote":
        url = web or "https://<server-endpoint>"
        return ("remote", "hosted", url,
                "A hosted server — point your client at its remote endpoint (HTTP/SSE).")
    return (None, None, None, None)


# A small, HONEST recency timeline. The registry exposes a single publish moment
# (published_at == updated_at), so we render a lifecycle arc: how long the server
# has existed and how fresh it is — not fabricated commit history.
def _recency_phase(ud):
    if ud is None:
        return "unknown", "Freshness unknown"
    if ud < 1:
        return "active", "Updated today"
    if ud <= 7:
        return "active", "Updated this week"
    if ud <= 30:
        return "active", "Updated this month"
    if ud <= 120:
        return "maintained", "Maintained · updated this quarter"
    if ud <= 365:
        return "stale", "Quiet · no update in months"
    return "stale", "Dormant · over a year since update"


def generate_details(data, out_dir=None, badge_slugs=None):
    """Static-generate /s/<slug>/index.html for every server — the SEO surface.
    Reuses the hub's exact header/nav/footer/theme (style.css). Shared head/footer
    built once for speed; only the per-server body is templated in the loop.
    `badge_slugs` (optional set) gates the "Embed this badge" block to only the
    servers that actually have a /badge/<slug>.svg (the capped set).
    """
    out_dir = out_dir or HERE
    badge_slugs = badge_slugs if badge_slugs is not None else set()
    servers = assign_slugs(data.get("servers", []))

    # category index (freshest-first) — used to render "category peers" cross-links.
    by_cat = {}
    for s in servers:
        by_cat.setdefault(s.get("category") or "Other", []).append(s)
    cat_total = {c: len(v) for c, v in by_cat.items()}

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
        # copy-to-clipboard for [data-copy] (code snippet + registry name)
        '(function(){function flash(el){if(!el||el.classList.contains("ok"))return;var p=el.getAttribute("data-orig");if(p==null){p=el.textContent;el.setAttribute("data-orig",p);}'
        'el.textContent="copied ✓";el.classList.add("ok");setTimeout(function(){el.textContent=el.getAttribute("data-orig")||p;el.classList.remove("ok");},1400);}'
        'function legacy(t){try{var a=document.createElement("textarea");a.value=t;a.style.position="fixed";a.style.opacity="0";document.body.appendChild(a);a.select();document.execCommand("copy");document.body.removeChild(a);}catch(e){}}'
        'function copy(t,btn){flash(btn);if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).catch(function(){legacy(t);});}else{legacy(t);}}'
        'document.addEventListener("click",function(ev){var host=ev.target.closest("[data-copy]");if(!host)return;'
        'var t=host.getAttribute("data-copy");var btn=ev.target.closest(".copy")||host.querySelector(".copy")||host.querySelector(".ncopy")||host;copy(t,btn);});})();'
        # scroll-reveal for detail cards
        '(function(){var els=document.querySelectorAll(".d-card,.d-grid");if(!("IntersectionObserver"in window)||(window.matchMedia&&window.matchMedia("(prefers-reduced-motion:reduce)").matches)){els.forEach(function(e){e.classList.add("in");});return;}'
        'var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add("in");io.unobserve(e.target);}});},{rootMargin:"0px 0px -8% 0px"});'
        'els.forEach(function(e){io.observe(e);});})();'
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

        # ── registry-position movement: the climbed/slipped badge + an inverted
        #    rank-over-time sparkline (fits the mesh/index theme). rank_delta > 0
        #    means the server climbed toward the top of the freshest-first board. ──
        rank = s.get("rank")
        rank_delta = s.get("rank_delta")
        rhist = s.get("rank_history") or []
        peak = s.get("peak_rank", rank)
        if isinstance(rank_delta, int) and rank_delta > 0:
            move_badge = f'<span class="d-move up" title="Climbed {rank_delta} since the prior run">▲ {rank_delta}</span>'
            move_word = f"climbed {rank_delta} place{'s' if rank_delta != 1 else ''}"
        elif isinstance(rank_delta, int) and rank_delta < 0:
            move_badge = f'<span class="d-move dn" title="Slipped {abs(rank_delta)} since the prior run">▼ {abs(rank_delta)}</span>'
            move_word = f"slipped {abs(rank_delta)} place{'s' if abs(rank_delta) != 1 else ''}"
        elif isinstance(rank_delta, int):
            move_badge = '<span class="d-move flat" title="Held position">→</span>'
            move_word = "held position"
        else:
            move_badge = '<span class="d-move new" title="New to the tracked index">NEW</span>'
            move_word = "new to the tracked index"
        if len(rhist) >= 2:
            # invert so a climb reads as an upward line: use the series' own worst
            # (largest) rank as the baseline — worst→0, best→largest — self-contained,
            # no dependency on the outer server_count.
            _ranks = [int(p.get("rank", rank) or (rank or 1)) for p in rhist]
            _worst = max(_ranks)
            rank_series = [max(1, (_worst + 1) - rv) for rv in _ranks]
            rank_chart = f'<div class="mv-sparkwrap">{_spark_svg(rank_series, 720, 90)}</div>'
            rank_note = f"position over the last {len(rhist)} days tracked · best: #{peak}"
        else:
            rank_chart = ""
            rank_note = "position movement fills in as the index runs daily"
        rank_cur = f"#{rank}" if isinstance(rank, int) else "—"
        rank_best = f"#{peak}" if isinstance(peak, int) else "—"
        position_block = (
            '<section class="d-card position">'
            '<h2 class="d-h">Registry position over time</h2>'
            f'<p class="run-note">Where {e(title)} sits in the freshest-first index, tracked daily — '
            f'{move_word} since the prior run. {rank_note}.</p>'
            f'{rank_chart}'
            '<div class="d-grid pos-stats" style="margin-top:18px">'
            f'<div class="cell"><span>Current position</span><b>{rank_cur}</b></div>'
            f'<div class="cell"><span>Best position</span><b>{rank_best}</b></div>'
            f'<div class="cell"><span>Since prior run</span><b>{move_badge}</b></div>'
            '</div>'
            '</section>'
        )

        # ── derived context ──
        owner, owner_kind = owner_of(name)
        verb, reg_label, snippet, snippet_note = install_snippet(s)
        phase_cls, phase_label = _recency_phase(ud)
        health_word = {"active": "Actively maintained", "maintained": "Maintained",
                       "stale": "Quiet", "unknown": "Unknown freshness"}.get(health, "Unknown")
        transport_note = {
            "Remote": "Hosted — runs on the provider's infrastructure; connect over HTTP/SSE.",
            "Local": "Local — runs on your machine over stdio (npx / uvx / docker / bundle).",
            "Unknown": "Transport not declared in the registry entry.",
        }.get(transport, "")
        is_github = owner_kind == "github" and "/" in name
        gh_user = name.split(".")[2] if (is_github and len(name.split(".")) >= 3) else None
        gh_url = repo or (f"https://github.com/{gh_user}" if gh_user else None)

        # primary actions
        actions = []
        if repo:
            actions.append(f'<a class="primary" href="{attr(repo)}" target="_blank" rel="noopener nofollow">View source ↗</a>')
        if web:
            actions.append(f'<a class="ghost" href="{attr(web)}" target="_blank" rel="noopener nofollow">Website ↗</a>')
        actions.append(f'<a class="ghost" href="https://registry.modelcontextprotocol.io/?search={urllib.parse.quote(name, safe="")}" target="_blank" rel="noopener nofollow">Registry entry ↗</a>')
        actions_html = "".join(actions)

        desc_html = f'<p class="d-desc">{e(desc)}</p>' if desc else ""

        # ── install / connect panel ──
        if snippet:
            verb_badge = f'<span class="run-verb">{e(verb)}</span>' if verb else ""
            if verb == "remote":
                install_inner = (
                    f'<div class="run-head"><span class="run-label">Connect · {e(reg_label)}</span>{verb_badge}</div>'
                    f'<pre class="code" data-copy="{attr(snippet)}"><code>{e(snippet)}</code><button class="copy" type="button" aria-label="Copy">copy</button></pre>'
                    f'<p class="run-note">{e(snippet_note)}</p>'
                )
            else:
                install_inner = (
                    f'<div class="run-head"><span class="run-label">Install · {e(reg_label)}</span>{verb_badge}</div>'
                    f'<pre class="code" data-copy="{attr(snippet)}"><code><span class="prompt">$</span> {e(snippet)}</code><button class="copy" type="button" aria-label="Copy">copy</button></pre>'
                    f'<p class="run-note">{e(snippet_note)}</p>'
                )
            install_block = f'<section class="d-card run"><h2 class="d-h">Install &amp; connect</h2>{install_inner}</section>'
        else:
            install_block = ""

        # ── recency lifecycle arc (honest: existence span + freshness) ──
        # position the freshness marker on a log-ish 0–365d axis
        pos = 100.0
        if ud is not None:
            pos = max(2.0, min(98.0, (1 - (math.log10(max(ud, 0.3) + 1) / math.log10(366))) * 100))
        recency_block = (
            '<section class="d-card recency">'
            '<h2 class="d-h">Freshness</h2>'
            f'<div class="rec-state {phase_cls}"><span class="d {phase_cls}"></span>{e(phase_label)}</div>'
            '<div class="rec-track" aria-hidden="true">'
            '<div class="rec-scale"><span>today</span><span>1mo</span><span>4mo</span><span>1yr+</span></div>'
            '<div class="rec-bar"><i class="rec-fill" style="width:' + f'{pos:.1f}%' + '"></i>'
            f'<i class="rec-dot {phase_cls}" style="left:{pos:.1f}%"></i></div>'
            '</div>'
            f'<p class="run-note">Last registry update {e(_fmt_days(ud))} · published {e(_fmt_date(s.get("published_at")))}.</p>'
            '</section>'
        )

        # ── facts grid (exactly 6 cells → clean 3×2; "Last updated" lives in the
        #    Freshness card, so it's omitted here to avoid a ragged 7th cell) ──
        if owner:
            owner_disp = f"{e(owner)}" + (' <span class="kind">github</span>' if owner_kind == "github" else "")
            if gh_url:
                owner_b = f'<a class="cell-link" href="{attr(gh_url)}" target="_blank" rel="noopener nofollow">{owner_disp} ↗</a>'
            else:
                owner_b = owner_disp
        else:
            owner_b = '<span style="color:var(--muted)">—</span>'
        facts = (
            '<div class="d-grid">'
            f'<div class="cell"><span>Category</span><b><a class="cell-link" href="/#index">{e(cat)}</a></b></div>'
            f'<div class="cell"><span>Transport</span><b>{e(transport)}</b></div>'
            f'<div class="cell"><span>Health</span><b><span class="d {e(health)}"></span>{e(health_word)}</b></div>'
            f'<div class="cell"><span>Version</span><b>{e(version)}</b></div>'
            f'<div class="cell reg"><span>Distribution</span><b>{reg_html}</b></div>'
            f'<div class="cell"><span>Maintainer</span><b>{owner_b}</b></div>'
            '</div>'
        )

        # ── category peers (cross-links to keep the directory connected) ──
        peers = [p for p in by_cat.get(cat, []) if p.get("slug") != slug][:8]
        peers_block = ""
        if peers:
            chips = "".join(
                f'<a class="peer" href="/s/{e(p["slug"])}/"><span class="pd {e(p.get("health") or "unknown")}"></span>'
                f'<span class="pn">{e(p.get("title") or p.get("name"))}</span>'
                f'<span class="pm">{e(p.get("transport") or "")}</span></a>'
                for p in peers
            )
            more_n = cat_total.get(cat, 0) - 1
            more_link = (f'<a class="peer-all" href="/#index">Browse all {more_n} in {e(cat)} →</a>'
                         if more_n > len(peers) else "")
            peers_block = (
                '<section class="d-card peers">'
                f'<h2 class="d-h">More in {e(cat)} <span class="d-h-n">{cat_total.get(cat,0)}</span></h2>'
                f'<div class="peer-grid">{chips}</div>{more_link}'
                '</section>'
            )

        about_block = (
            '<section class="d-card about">'
            '<h2 class="d-h">About this server</h2>'
            f'<p class="about-p">{e(desc) if desc else e(title) + " is a " + transport.lower() + " Model Context Protocol server."}</p>'
            f'<p class="about-p sub">{e(transport_note)} Indexed under <b>{e(cat)}</b>, alongside {cat_total.get(cat,0)-1} other server{"s" if cat_total.get(cat,0)!=2 else ""}. '
            'Health is freshness-derived from the registry\'s last-update timestamp; this index does not run the server, so capabilities and tool lists live in the source repository.</p>'
            '</section>'
        )

        # ── embeddable rank badge — the viral loop (servers show their live rank,
        #    linking back here). Only rendered for the capped set that has a badge. ──
        embed_block = ""
        if slug in badge_slugs:
            badge_url = f"{SITE}/badge/{slug}.svg"
            embed_md = f"[![MCP Index rank]({badge_url})]({canon}/)"
            embed_html = f'<a href="{canon}/"><img src="{badge_url}" alt="MCP Index rank"></a>'
            embed_block = (
                '<section class="d-card embed">'
                '<h2 class="d-h">📛 Embed this badge</h2>'
                '<p class="run-note">Show your live MCP Index rank in your README — it updates daily and links back here.</p>'
                f'<p style="margin-top:14px"><img src="{attr(badge_url)}" alt="MCP Index rank badge for {attr(title)}" style="vertical-align:middle"></p>'
                '<div style="margin-top:14px">'
                '<div class="run-head"><span class="run-label">Markdown</span></div>'
                f'<pre class="code" data-copy="{attr(embed_md)}"><code>{e(embed_md)}</code><button class="copy" type="button" aria-label="Copy">copy</button></pre>'
                '<div class="run-head" style="margin-top:14px"><span class="run-label">HTML</span></div>'
                f'<pre class="code" data-copy="{attr(embed_html)}"><code>{e(embed_html)}</code><button class="copy" type="button" aria-label="Copy">copy</button></pre>'
                '</div>'
                '</section>'
            )

        body = (
            '<main class="detail"><div class="wrap">'
            '<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Home</a><span class="sep">/</span>'
            f'<a href="/#index">The MCP Index</a><span class="sep">/</span><a href="/#index">{e(cat)}</a><span class="sep">/</span>'
            f'<span>{e(title)}</span></nav>'
            '<a class="back" href="/">← Back to the index</a>'
            '<div class="d-head"><div class="d-title">'
            f'<div class="d-kicker"><span class="d {e(health)}"></span>{e(health_word)} · {e(transport)}{" · " + e(reg_label) if reg_label else ""}</div>'
            f'<h1>{e(title)}{new_badge} {move_badge}</h1>'
            f'<div class="d-name" data-copy="{attr(name)}" title="Click to copy the registry name">{e(name)} <span class="ncopy">copy</span></div></div></div>'
            f'{desc_html}'
            f'<div class="d-actions">{actions_html}</div>'
            f'{facts}'
            '<div class="d-cols">'
            f'{install_block}'
            f'{recency_block}'
            '</div>'
            f'{position_block}'
            f'{about_block}'
            f'{embed_block}'
            f'{peers_block}'
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
    # read the prior data.json to extend each server's rank_history — the daily
    # "registry position" series (rank = position in the freshest-first list; the
    # score behind that rank is the server's updated_at timestamp). Keyed on the
    # stable server id (`name`, the reverse-DNS registry name). Same cold-start as
    # any history series: on day one deltas are None and the UI shows a "new" state.
    prior_rankh = {}
    _prior_path = os.path.join(HERE, "data.json")
    if os.path.exists(_prior_path):
        try:
            _prev = json.load(open(_prior_path))
            for _r in _prev.get("servers", []):
                prior_rankh[_r["name"]] = _r.get("rank_history", [])
        except Exception:
            pass

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
        it["category"] = categorize((it.get("title") or "") + " " + (it.get("description") or "") + " " + (it.get("name") or ""))
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

    # ── movement tracking ─────────────────────────────────────────────────────
    # rank = 1-based position in the freshest-first display list. Append today's
    # (rank, score=updated_at) to each server's rank_history (capped 90 days), then
    # derive position movement vs the most recent PRIOR day. rank_delta > 0 means the
    # server CLIMBED (a smaller rank number is better — closer to the top). On day one
    # there is no prior, so deltas are None and the UI shows a "new"/no-change state.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for i, it in enumerate(items):
        it["rank"] = i + 1
        rh = list(prior_rankh.get(it["name"], []))
        # only PRIOR points with a real int rank are comparable (a malformed/None rank
        # in the persisted history must never crash the daily cron build).
        prior_pts = [p for p in rh if p.get("date") != today and isinstance(p.get("rank"), int)]
        if not rh or rh[-1].get("date") != today:
            rh.append({"date": today, "rank": it["rank"], "score": it["updated_at"]})
        rh = rh[-90:]
        it["rank_history"] = rh
        if prior_pts:
            prev_rank = prior_pts[-1].get("rank")
            it["rank_prev"] = prev_rank
            it["rank_delta"] = prev_rank - it["rank"]   # prior_pts are int-rank only
            it["peak_rank"] = min([p["rank"] for p in prior_pts] + [it["rank"]])
            it["tracked_days"] = len(prior_pts) + 1
        else:
            it["rank_prev"] = None
            it["rank_delta"] = None       # None == new/untracked (distinct from 0 == held)
            it["peak_rank"] = it["rank"]
            it["tracked_days"] = 1

    # biggest climbers over the tracked window — the "Movers" strip. Default-guard the
    # sort keys so a malformed record can never crash the daily cron build (production
    # blast radius). Falls back to the newest-published servers on day one (before any
    # position history exists) so the strip is never empty.
    climbers = [x for x in items if isinstance(x.get("rank_delta"), int) and x["rank_delta"] > 0]
    movers = sorted(climbers, key=lambda x: (x["rank_delta"], -(x.get("rank") or 0)),
                    reverse=True)[:5]
    if not movers:
        # day-one fallback: newest servers. Sort by a stable key (updated_at desc, then
        # name) so the build output is deterministic across runs with identical input.
        movers = sorted([x for x in items if x.get("is_new")],
                        key=lambda x: (x.get("updated_at") or "", x.get("name") or ""),
                        reverse=True)[:5]

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
        "movers": [{"name": m["name"], "title": m.get("title"), "slug": slugify(m["name"]),
                    "category": m.get("category"), "rank": m["rank"],
                    "rank_delta": m.get("rank_delta"), "is_new": bool(m.get("is_new"))}
                   for m in movers],
        "servers": items,
    }
    json.dump(data, open(os.path.join(HERE, "data.json"), "w"), indent=2)
    print(f"wrote data.json: {len(items)} servers, {data['new_this_week']} new this week, {data['active_count']} active", file=sys.stderr)
    # assign stable slugs once, up front, so badges + feed + detail pages all agree.
    assign_slugs(data["servers"])
    # public distribution surface: capped rank badges (/badge/<slug>.svg) + feed.json API.
    badge_slugs = generate_badges(data["servers"])
    generate_feed(data, badge_slugs=badge_slugs)
    # static-generate the SEO surface: /s/<slug> detail pages + sitemap + llms.txt
    generate_details(data, badge_slugs=badge_slugs)
    # resilience guard: the registry has thousands of servers; a run that returns far
    # fewer means the API hiccupped mid-pagination. Refuse to publish a gutted index —
    # fail so the cron skips commit+deploy and the last-good page stays live.
    if len(items) < 500:
        print(f"GUARD: only {len(items)} servers (< 500); refusing to publish a partial index.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
