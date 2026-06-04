/* The MCP Index — search + filter + sort, rendered from the official registry data.
   Vanilla JS, no deps. Data: data.json (built daily by build_data.py). */
(function(){
  "use strict";
  var W = window, D = document;
  var nav = D.getElementById("nav");
  if(nav){ var on=function(){nav.classList.toggle("scrolled",W.scrollY>20)}; W.addEventListener("scroll",on,{passive:true}); on(); }
  var REDUCE = W.matchMedia && W.matchMedia("(prefers-reduced-motion:reduce)").matches;

  var ALL=[], PAGE=120, limit=PAGE;
  var state={q:"",cat:"All",transport:"All",health:"All",onlyNew:false};
  var sort={key:null,dir:1};          // null key = registry default order (freshest first)
  var firstPaint=true, prevLimit=0;   // entrance animation only on first paint + load-more

  function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];});}
  function rx(s){return String(s).replace(/[.*+?^${}()|[\]\\]/g,"\\$&");}
  // highlight query hits in already-escaped text
  function hi(escaped, q){
    if(!q) return escaped;
    try{ return escaped.replace(new RegExp("("+rx(esc(q))+")","ig"),'<mark>$1</mark>'); }
    catch(e){ return escaped; }
  }
  // URL-safe slug from a server name — MUST match build_data.py.slugify()
  function slugify(name){
    var s=String(name||"").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/-+/g,"-").replace(/^-|-$/g,"");
    return s||"server";
  }
  function safeUrl(u){
    if(!u) return null;
    try{ var p=new URL(u, location.href).protocol; return (p==="http:"||p==="https:")?u:null; }
    catch(e){ return null; }
  }
  function fmtDays(d){
    if(d==null) return "—";
    if(d<1) return "today"; if(d<2) return "1d ago";
    if(d<30) return Math.round(d)+"d ago";
    if(d<365) return Math.round(d/30)+"mo ago";
    return Math.round(d/365)+"y ago";
  }
  function relDate(iso){ if(!iso) return "recently"; return fmtDays((Date.now()-new Date(iso).getTime())/86400000); }

  // tiny recency micro-bar (the mesh motif, per row): how fresh, on a log 0–365d axis
  function freshPct(d){
    if(d==null) return 4;
    var p=(1-(Math.log10(Math.max(d,0.3)+1)/Math.log10(366)))*100;
    return Math.max(4, Math.min(100, p));
  }
  function spark(s){
    var p=freshPct(s.updated_days);
    return '<span class="spark '+esc(s.health)+'" title="updated '+esc(fmtDays(s.updated_days))+'" aria-hidden="true">'
      +'<i style="width:'+p.toFixed(0)+'%"></i></span>';
  }

  /* registry-position movement vs the prior daily run: ▲N climbed, ▼N slipped, → held.
     rank_delta>0 means a smaller (better) rank number — i.e. climbed toward the top.
     Returns '' when there's no prior history yet (fills in as the index runs daily). */
  function moveBadge(s){
    var d=s.rank_delta;
    if(d==null) return '';
    if(d>0) return ' <span class="mv up" title="Climbed '+d+' since the prior run">▲'+d+'</span>';
    if(d<0) return ' <span class="mv dn" title="Slipped '+Math.abs(d)+' since the prior run">▼'+Math.abs(d)+'</span>';
    return ' <span class="mv flat" title="Held position">→</span>';
  }

  /* movers strip: horizontally-scrollable chips linking to detail pages. Each shows
     the position climb (▲N) when tracked, else a NEW tag on day one before history. */
  function renderMovers(movers){
    var el=D.getElementById("movers"); if(!el) return;
    if(!movers||!movers.length){ el.hidden=true; return; }
    var chips=movers.map(function(m,i){
      var d=m.rank_delta;
      var climbed=(typeof d==="number" && d>0);
      // only a genuinely untracked item (null/undefined rank_delta) is NEW; a numeric 0
      // means it HELD position (→), never NEW.
      var tag=climbed?'<span class="mv up">▲'+d+'</span>'
        :(d==null?'<span class="mv new">NEW</span>':'<span class="mv flat" title="Held position">→</span>');
      var sub=climbed?("now #"+m.rank):(d==null?esc(m.category||"new"):("now #"+m.rank));
      return '<a class="mover" href="/s/'+esc(m.slug||slugify(m.name))+'/" style="--d:'+(i*50)+'ms">'
        +tag+'<span class="mvn">'+esc(m.title||m.name)+'</span><span class="mvs">'+sub+'</span></a>';
    }).join("");
    el.innerHTML='<span class="movers-l">Movers</span><div class="movers-track">'+chips+'</div>';
    el.hidden=false;
  }

  function matches(s){
    if(state.onlyNew && !s.is_new) return false;
    if(state.cat!=="All" && s.category!==state.cat) return false;
    if(state.transport!=="All" && s.transport!==state.transport) return false;
    if(state.health!=="All" && s.health!==state.health) return false;
    if(state.q){
      var q=state.q.toLowerCase();
      if((s.name+" "+s.title+" "+s.description).toLowerCase().indexOf(q)<0) return false;
    }
    return true;
  }
  function sortVal(s){
    var k=sort.key;
    if(k==="updated_days"){ var v=s.updated_days; return v==null?1e9:v; } // unknown sinks last
    return String(s[k]==null?"":s[k]).toLowerCase();
  }
  function applySort(arr){
    if(!sort.key) return arr;
    return arr.slice().sort(function(a,b){
      var av=sortVal(a), bv=sortVal(b);
      if(av<bv) return -1*sort.dir; if(av>bv) return 1*sort.dir; return 0;
    });
  }

  function rowHTML(s, i, animFrom){
    var q=state.q;
    var reg=(s.registries||[]).map(function(r){return '<span>'+esc(r)+'</span>';}).join("");
    var nw=s.is_new?'<span class="new">NEW</span>':'';
    var title=hi(esc(s.title),q), name=hi(esc(s.name),q);
    var desc=s.description?'<p>'+hi(esc(s.description),q)+'</p>':'';
    // entrance stagger only for freshly-revealed rows
    var anim = (animFrom!=null && i>=animFrom && i<animFrom+40)
      ? ' style="animation-delay:'+Math.min((i-animFrom)*22,420)+'ms"' : '';
    var cls = (animFrom!=null && i>=animFrom) ? 'row reveal' : 'row';
    return '<a class="'+cls+'" href="/s/'+esc(slugify(s.name))+'/"'+anim+'>'
      +'<div class="nm"><h3>'+title+' '+nw+moveBadge(s)+'</h3><div class="ns">'+name+'</div>'
        +desc+(reg?'<div class="reg">'+reg+'</div>':'')+'</div>'
      +'<div class="cat">'+esc(s.category)+'</div>'
      +'<div class="health">'+spark(s)+'<span class="hl"><span class="d '+esc(s.health)+'"></span>'+esc(s.health)+' · '+fmtDays(s.updated_days)+'</span></div>'
      +'<div class="cat tcell" style="color:var(--muted)">'+esc(s.transport)+'<span class="go" style="margin-left:8px">↗</span></div></a>';
  }

  function render(){
    var filtered=applySort(ALL.filter(matches));
    var shown=filtered.slice(0,limit);
    // animate first paint (all) or only the appended slice on load-more
    var animFrom = firstPaint ? 0 : (limit>prevLimit ? prevLimit : null);
    if(REDUCE) animFrom=null;
    D.getElementById("rows").innerHTML = shown.length ? shown.map(function(s,i){return rowHTML(s,i,animFrom);}).join("")
      : '<div class="empty"><div class="empty-mark">∅</div><b>No servers match.</b><span>Try a broader term or clear the filters.</span>'
        +'<button id="resetf" type="button">Reset filters</button></div>';
    var rf=D.getElementById("resetf"); if(rf) rf.addEventListener("click",resetAll);

    var cEl=D.getElementById("count");
    cEl.innerHTML = 'Showing <b>'+Math.min(limit,filtered.length).toLocaleString()+'</b> of <b>'+filtered.length.toLocaleString()+'</b> matching'
      + (filtered.length!==ALL.length ? ' · '+ALL.length.toLocaleString()+' total' : '')
      + (sort.key ? ' · sorted by <b>'+sortLabel(sort.key)+'</b> '+(sort.dir>0?'↑':'↓') : '');
    var more=D.getElementById("more");
    more.innerHTML = filtered.length>limit ? '<button id="loadmore">Load <b>'+Math.min(PAGE,filtered.length-limit)+'</b> more · '+(filtered.length-limit).toLocaleString()+' remaining</button>' : '';
    var lm=D.getElementById("loadmore");
    if(lm) lm.addEventListener("click",function(){prevLimit=limit;limit+=PAGE;firstPaint=false;render();});
    prevLimit=limit; firstPaint=false;
  }
  function sortLabel(k){return {title:"name",category:"category",updated_days:"freshness",transport:"transport"}[k]||k;}

  function chip(label,group,val,n){
    return '<button class="chip" data-group="'+group+'" data-val="'+esc(val)+'">'+esc(label)+(n!=null?'<span class="n">'+n.toLocaleString()+'</span>':'')+'</button>';
  }

  /* animated stat counter (count-up on load) */
  function counter(el, to){
    if(REDUCE || to>100000){ el.textContent=to.toLocaleString(); return; }
    var start=performance.now(), dur=900;
    function step(t){
      var k=Math.min(1,(t-start)/dur), e=1-Math.pow(1-k,3); // easeOutCubic
      el.textContent=Math.round(to*e).toLocaleString();
      if(k<1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  function statCell(value,label){
    return '<div class="m"><b data-to="'+value+'">0</b><span>'+label+'</span></div>';
  }

  function injectItemList(data){
    var top=(data.servers||[]).slice(0,50);
    var ld={"@context":"https://schema.org","@type":"ItemList","name":"The MCP Index — featured servers",
      "numberOfItems":top.length,
      "itemListElement":top.map(function(s,i){return {"@type":"ListItem","position":i+1,
        "url":"https://mcp.kymatalabs.com/s/"+slugify(s.name),"name":s.title||s.name};})};
    var el=D.createElement("script"); el.type="application/ld+json"; el.id="ld-itemlist";
    el.textContent=JSON.stringify(ld); D.head.appendChild(el);
  }

  function resetAll(){
    state={q:"",cat:"All",transport:"All",health:"All",onlyNew:false};
    var q=D.getElementById("q"); if(q) q.value="";
    var clear=D.getElementById("clear"); if(clear) clear.style.display="none";
    D.querySelectorAll(".chip").forEach(function(x){x.classList.remove("active");});
    var allc=D.querySelector('.chip[data-group="cat"][data-val="All"]'); if(allc) allc.classList.add("active");
    limit=PAGE; syncURL(); render();
  }

  // keep ?q= in the URL (the site's advertised SearchAction) without reloading
  function syncURL(){
    try{
      var u=new URL(location.href);
      if(state.q) u.searchParams.set("q",state.q); else u.searchParams.delete("q");
      history.replaceState(null,"",u.pathname+(u.search||"")+u.hash);
    }catch(e){}
  }

  function build(data){
    ALL=data.servers||[];
    injectItemList(data);
    // movers strip — biggest climbers since the prior run (rank_delta), or newest
    // servers on day one before registry-position history exists.
    renderMovers(data.movers||[]);
    D.getElementById("metarow").innerHTML =
      statCell(data.server_count,"Servers indexed")
      + statCell(data.new_this_week,"New this week")
      + statCell(data.active_count,"Active (&lt;30d)")
      + statCell(data.categories.length,"Categories");
    D.querySelectorAll("#metarow b[data-to]").forEach(function(b){counter(b, +b.getAttribute("data-to"));});

    D.getElementById("liveline").textContent="Sourced from the official MCP registry · updated "+relDate(data.generated_at);
    var fg=D.getElementById("footgen"); if(fg) fg.textContent="Updated "+relDate(data.generated_at)+" from the official registry";

    var cc=data.category_counts||{};
    var cats=Object.keys(cc).sort(function(a,b){return cc[b]-cc[a];});
    D.getElementById("filters").innerHTML =
      chip("All","cat","All",data.server_count) + cats.map(function(c){return chip(c,"cat",c,cc[c]);}).join("");
    D.getElementById("toggles").innerHTML =
      chip("New ⚡","onlyNew","new",data.new_this_week)
      + chip("Remote","transport","Remote") + chip("Local","transport","Local")
      + chip("Active","health","active");

    D.querySelector('.chip[data-group="cat"][data-val="All"]').classList.add("active");

    D.querySelectorAll(".chip").forEach(function(c){
      c.addEventListener("click",function(){
        var g=c.getAttribute("data-group");
        if(g==="onlyNew"){
          state.onlyNew=c.classList.toggle("active");
        } else if(g==="transport" || g==="health"){
          var wasActive=c.classList.contains("active");
          D.querySelectorAll('.chip[data-group="'+g+'"]').forEach(function(x){x.classList.remove("active");});
          if(wasActive){ state[g]="All"; } else { c.classList.add("active"); state[g]=c.getAttribute("data-val"); }
        } else {
          D.querySelectorAll('.chip[data-group="cat"]').forEach(function(x){x.classList.remove("active");});
          c.classList.add("active"); state.cat=c.getAttribute("data-val");
        }
        limit=PAGE; render();
      });
    });

    var q=D.getElementById("q"), clear=D.getElementById("clear"), tmr;
    // deep-link: ?q= from the advertised SearchAction
    try{ var pq=new URL(location.href).searchParams.get("q"); if(pq){ q.value=pq; state.q=pq.trim(); clear.style.display=state.q?"":"none"; } }catch(e){}
    function onQ(){ state.q=q.value.trim(); clear.style.display=state.q?"":"none"; limit=PAGE;
      clearTimeout(tmr); tmr=setTimeout(function(){ render(); syncURL(); }, 90); }
    q.addEventListener("input",onQ);
    clear.addEventListener("click",function(){q.value="";state.q="";clear.style.display="none";limit=PAGE;render();syncURL();q.focus();});

    // sortable column headers — click/Enter toggles asc/desc, third click clears to default
    var heads=D.querySelectorAll(".colhead .sortable");
    function paint(){ heads.forEach(function(h){
      var k=h.getAttribute("data-sort");
      h.setAttribute("aria-sort", sort.key===k ? (sort.dir>0?"ascending":"descending") : "none");
    }); }
    heads.forEach(function(h){
      h.addEventListener("click",function(){
        var k=h.getAttribute("data-sort");
        if(sort.key!==k){ sort.key=k; sort.dir=1; }
        else if(sort.dir===1){ sort.dir=-1; }
        else { sort.key=null; sort.dir=1; }
        paint(); limit=PAGE; render();
      });
    });

    // keyboard: "/" or Cmd/Ctrl-K focuses search; Esc clears it
    D.addEventListener("keydown",function(ev){
      if((ev.key==="/"&&!/^(input|textarea)$/i.test((ev.target.tagName||"")))||((ev.metaKey||ev.ctrlKey)&&ev.key.toLowerCase()==="k")){
        ev.preventDefault(); q.focus(); q.select();
      } else if(ev.key==="Escape" && D.activeElement===q && q.value){
        q.value="";state.q="";clear.style.display="none";limit=PAGE;render();syncURL();
      }
    });

    render();
  }

  fetch("data.json",{cache:"no-store"}).then(function(r){return r.json();}).then(build).catch(function(e){
    D.getElementById("rows").innerHTML='<div class="loading">Could not load the index. '+esc(e.message||e)+'</div>';
  });
})();
