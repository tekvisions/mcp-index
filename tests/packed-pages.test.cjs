const assert=require('node:assert/strict');
const http=require('node:http');
const handler=require(process.argv[2]);
(async()=>{
 const server=http.createServer(handler);await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const base='http://127.0.0.1:'+server.address().port;
 try{
  let r=await fetch(base+'/s/original-current/');assert.equal(r.status,200);let html=await r.text();
  assert.ok(html.includes('org.example/current'));assert.ok(!html.includes('</script><script>alert(1)</script>'));
  assert.ok(!html.includes('"isAccessibleForFree":true'));assert.ok(!html.includes('"publisher":{"@type":"Organization","name":"Kymata Labs"'));
  r=await fetch(base+'/details?route=original-current');assert.equal(r.status,200);assert.equal(await r.text(),html);
  r=await fetch(base+'/s/original-current/',{method:'HEAD'});assert.equal(r.status,200);assert.equal(await r.text(),'');
  r=await fetch(base+'/s/missing/');assert.equal(r.status,200);let t=await r.text();assert.ok(t.includes('noindex,follow'));assert.ok(t.includes('Absence alone does not establish why'));
  r=await fetch(base+'/s/removed/');assert.equal(r.status,200);assert.ok((await r.text()).includes('marks this server as deleted'));
  for(const p of ['/s/not-real/','/details?route=../../.env','/details?route=missing&route=original-current','/s/__proto__/'])assert.equal((await fetch(base+p)).status,404,p);
  assert.equal((await fetch(base+'/s/missing/',{method:'POST'})).status,405);
 }finally{await new Promise(r=>server.close(r));}
 console.log('Packed-page HTTP journeys passed');
})().catch(e=>{console.error(e);process.exitCode=1});
