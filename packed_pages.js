'use strict';
// An immutable, pre-rendered page store. No network, user input execution or writes.
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const crypto = require('node:crypto');
const entries = JSON.parse(fs.readFileSync(path.join(__dirname, 'pages.json'), 'utf8'));
const fd = fs.openSync(path.join(__dirname, 'pages.bin'), 'r');
const dictionary = fs.readFileSync(path.join(__dirname, 'dictionary.bin'));
module.exports = function(req, res) {
  if (!['GET', 'HEAD'].includes(req.method)) {res.statusCode = 405;res.setHeader('Allow','GET, HEAD');return res.end('Method not allowed');}
  // Accept either the original route or the provider's explicit rewrite target.
  // Both select an exact immutable registry key, never a filesystem path.
  let url;
  try {url = new URL(String(req.url || ''), 'https://mcp.kymatalabs.com');} catch (_) {res.statusCode=400;return res.end('Invalid URL');}
  const pathname = url.pathname;
  const match = /^\/s\/([a-z0-9-]+)\/?$/.exec(pathname);
  const rewritten = pathname === '/details' && url.searchParams.getAll('route').length === 1 ? url.searchParams.get('route') : null;
  const slug = match ? match[1] : (rewritten && /^[a-z0-9-]{1,300}$/.test(rewritten) ? rewritten : null);
  const item = slug && Object.prototype.hasOwnProperty.call(entries, slug) ? entries[slug] : null;
  if (!item) {res.statusCode=404;return res.end('Page not found');}
  try {
    if (!Number.isSafeInteger(item.offset) || item.offset<0 || !Number.isSafeInteger(item.length) || item.length<1 || item.length>1000000) throw new Error('Invalid packed range');
    const packed = Buffer.alloc(item.length);
    if (fs.readSync(fd, packed, 0, item.length, item.offset) !== item.length) throw new Error('Short page read');
    const body = zlib.inflateRawSync(packed, {dictionary, maxOutputLength: 1000000});
    if (body.length !== item.bytes || crypto.createHash('sha256').update(body).digest('hex') !== item.sha256) throw new Error('Page integrity');
    res.setHeader('Content-Type','text/html; charset=utf-8');
    res.setHeader('Cache-Control','public, max-age=0, s-maxage=86400');
    res.setHeader('X-Content-SHA256',item.sha256);
    res.setHeader('X-Content-Type-Options','nosniff');
    res.statusCode=200;res.end(req.method==='HEAD'?undefined:body);
  } catch (_) {res.statusCode=503;res.setHeader('Cache-Control','no-store');res.end('Saved page unavailable');}
};
