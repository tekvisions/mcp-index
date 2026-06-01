/* The MCP Index — search + filter + render from the official registry data */
(function(){
  "use strict";
  var W = window;
  var nav = document.getElementById("nav");
  if(nav){ var on=function(){nav.classList.toggle("scrolled",W.scrollY>20)}; W.addEventListener("scroll",on,{passive:true}); on(); }

  var ALL=[], PAGE=120, limit=PAGE;
  var state={q:"",cat:"All",transport:"All",health:"All",onlyNew:false};

  function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];});}
  // only allow http(s) — block javascript:/data: from untrusted registry fields
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
  function linkFor(s){
    var u = safeUrl(s.repository);
    if(u) return u;
    if(s.name && s.name.indexOf("io.github.")===0){
      var rest=s.name.slice("io.github.".length), p=rest.split("/");
      if(p.length>=2) return "https://github.com/"+encodeURIComponent(p[0])+"/"+encodeURIComponent(p.slice(1).join("/"));
    }
    u = safeUrl(s.website);
    if(u) return u;
    return "https://registry.modelcontextprotocol.io/?search="+encodeURIComponent(s.name||"");
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

  function render(){
    var filtered=ALL.filter(matches);
    var shown=filtered.slice(0,limit);
    document.getElementById("rows").innerHTML = shown.length ? shown.map(function(s){
      var reg=(s.registries||[]).map(function(r){return '<span>'+esc(r)+'</span>';}).join("");
      var nw=s.is_new?'<span class="new">NEW</span>':'';
      return '<a class="row" href="'+esc(linkFor(s))+'" target="_blank" rel="noopener">'
        +'<div class="nm"><h3>'+esc(s.title)+' '+nw+'</h3><div class="ns">'+esc(s.name)+'</div>'
          +(s.description?'<p>'+esc(s.description)+'</p>':'')+(reg?'<div class="reg">'+reg+'</div>':'')+'</div>'
        +'<div class="cat">'+esc(s.category)+'</div>'
        +'<div class="health"><span class="d '+esc(s.health)+'"></span>'+esc(s.health)+' · '+fmtDays(s.updated_days)+'</div>'
        +'<div class="cat" style="color:var(--muted)">'+esc(s.transport)+'<span class="go" style="margin-left:8px">↗</span></div></a>';
    }).join("") : '<div class="loading">No servers match — try a broader search or clear filters.</div>';

    document.getElementById("count").innerHTML = 'Showing <b>'+Math.min(limit,filtered.length).toLocaleString()+'</b> of <b>'+filtered.length.toLocaleString()+'</b> matching'
      + (filtered.length!==ALL.length ? ' · '+ALL.length.toLocaleString()+' total' : '');
    var more=document.getElementById("more");
    more.innerHTML = filtered.length>limit ? '<button id="loadmore">Load more ('+(filtered.length-limit).toLocaleString()+' more)</button>' : '';
    var lm=document.getElementById("loadmore");
    if(lm) lm.addEventListener("click",function(){limit+=PAGE;render();});
  }

  function chip(label,group,val,n){
    return '<button class="chip" data-group="'+group+'" data-val="'+esc(val)+'">'+esc(label)+(n!=null?'<span class="n">'+n+'</span>':'')+'</button>';
  }
  function m(v,l){return '<div class="m"><b>'+v+'</b><span>'+l+'</span></div>';}

  function build(data){
    ALL=data.servers||[];
    document.getElementById("metarow").innerHTML =
      m(data.server_count.toLocaleString(),"Servers indexed")
      + m(data.new_this_week,"New this week")
      + m(data.active_count.toLocaleString(),"Active (&lt;30d)")
      + m(data.categories.length,"Categories");
    document.getElementById("liveline").textContent="Sourced from the official MCP registry · updated "+relDate(data.generated_at);
    var fg=document.getElementById("footgen"); if(fg) fg.textContent="Updated "+relDate(data.generated_at)+" from the official registry";

    var cc=data.category_counts||{};
    var cats=Object.keys(cc).sort(function(a,b){return cc[b]-cc[a];});
    document.getElementById("filters").innerHTML =
      chip("All","cat","All",data.server_count) + cats.map(function(c){return chip(c,"cat",c,cc[c]);}).join("");
    document.getElementById("toggles").innerHTML =
      chip("New ⚡","onlyNew","new",data.new_this_week)
      + chip("Remote","transport","Remote") + chip("Local","transport","Local")
      + chip("Active","health","active");

    // default-active: the "All" category chip
    document.querySelector('.chip[data-group="cat"][data-val="All"]').classList.add("active");

    document.querySelectorAll(".chip").forEach(function(c){
      c.addEventListener("click",function(){
        var g=c.getAttribute("data-group");
        if(g==="onlyNew"){
          state.onlyNew=c.classList.toggle("active");
        } else if(g==="transport" || g==="health"){
          // toggleable single-select within group: clicking active clears to All
          var wasActive=c.classList.contains("active");
          document.querySelectorAll('.chip[data-group="'+g+'"]').forEach(function(x){x.classList.remove("active");});
          if(wasActive){ state[g]="All"; } else { c.classList.add("active"); state[g]=c.getAttribute("data-val"); }
        } else { // cat
          document.querySelectorAll('.chip[data-group="cat"]').forEach(function(x){x.classList.remove("active");});
          c.classList.add("active"); state.cat=c.getAttribute("data-val");
        }
        limit=PAGE; render();
      });
    });

    var q=document.getElementById("q"), clear=document.getElementById("clear");
    q.addEventListener("input",function(){state.q=q.value.trim();clear.style.display=state.q?"":"none";limit=PAGE;render();});
    clear.addEventListener("click",function(){q.value="";state.q="";clear.style.display="none";limit=PAGE;render();q.focus();});

    render();
  }

  fetch("data.json",{cache:"no-store"}).then(function(r){return r.json();}).then(build).catch(function(e){
    document.getElementById("rows").innerHTML='<div class="loading">Could not load the index. '+esc(e.message||e)+'</div>';
  });
})();
