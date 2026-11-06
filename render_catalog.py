"""Offline presentation candidate. Does not collect data or release the publication hold."""
import hashlib,html,json,pathlib,re
from build_data import assign_slugs
PAGE_SIZE=120
SITE='https://mcp.kymatalabs.com'
def render(root,template):
 root=pathlib.Path(root);raw=(root/'data.json').read_bytes();data=json.loads(raw);rows=assign_slugs(data['servers']);digest=hashlib.sha256(raw).hexdigest();pages=max(1,(len(rows)+PAGE_SIZE-1)//PAGE_SIZE)
 slugs=[x['slug'] for x in rows]
 if len(set(slugs))!=len(slugs) or any(not re.fullmatch(r'[a-z0-9-]+',s) for s in slugs):raise ValueError('Unsafe or duplicate published slug')
 for page in range(1,pages+1):
  text=template.replace('<html lang="en">',f'<html lang="en" data-snapshot-sha256="{digest}">')
  part=rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE];cards=[]
  for x in part:
   esc=lambda k:html.escape(str(x.get(k) or ''),quote=True)
   cards.append(f'<a class="row" href="/s/{esc("slug")}/"><div class="nm"><h3>{esc("title")}</h3><div class="ns">{esc("name")}</div><p>{esc("description")}</p></div><div class="cat">{esc("category")}</div><div class="health">Registry updated {esc("updated_at")}</div><div class="cat tcell">{esc("transport")}</div></a>')
  nav=' '.join(f'<a href="{("/" if n==1 else "/catalog/"+str(n)+"/")}"'+(' aria-current="page"' if n==page else '')+f'>{n}</a>' for n in range(1,pages+1))
  start=text.index('  <div class="rows" id="rows">');end=text.index('</section>',start)
  status='Latest-version cursor traversal completed; registry-deleted records are excluded from search. Availability and safety are not independently verified.' if data.get('collection_complete') is True else 'Completeness unverified; refresh paused.'
  text=text[:start]+f'<p>Snapshot {html.escape(data["generated_at"])} · {len(rows):,} saved records · page {page} of {pages}. {status}</p>\n  <div class="rows" id="rows">'+''.join(cards)+'</div>\n<div class="more" id="more"></div>\n<nav aria-label="Catalog pages">'+nav+'</nav></div>\n'+text[end:]
  text=text.replace('href="style.css"','href="/style.css"').replace('href="favicon.svg"','href="/favicon.svg"')
  if page>1:
   text=text.replace(f'<link rel="canonical" href="{SITE}/">',f'<link rel="canonical" href="{SITE}/catalog/{page}/">')
   text=re.sub(r'<title>.*?</title>',f'<title>MCP registry snapshot — page {page} | The MCP Index</title>',text)
   text=re.sub(r'<script[^>]+src="app.js[^\"]*"[^>]*></script>','',text)
   a=text.index('  <div class="controls">');b=text.index('  <div class="colhead"',a)
   text=text[:a]+'<p><a href="/#index">Search and filter the complete saved snapshot</a></p>\n'+text[b:]
  dest=root/'index.html' if page==1 else root/'catalog'/str(page)/'index.html';dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text)
 return {'snapshot_sha256':digest,'records':len(rows),'pages':pages,'complete_source':data.get('collection_complete') is True,'publication':'candidate'}
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(render(a.out,pathlib.Path(__file__).with_name('index.source.html').read_text())))
