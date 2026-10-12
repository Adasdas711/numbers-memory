'use strict';
const CACHE = 'numbers-memory-305dc7540402a9aa';
const FILES = ['./','./index.html','./features.js','./features.css','./manifest.webmanifest','./icons/icon-192.png','./icons/icon-512.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(FILES.map(path=>new Request(path,{cache:"reload"}))))));
self.addEventListener('activate',event=>event.waitUntil((async()=>{
  for(const key of await caches.keys()) if(key.startsWith('numbers-memory-') && key!==CACHE) await caches.delete(key);
  await self.clients.claim();
})()));
self.addEventListener('message',event=>{if(event.data?.type==='SKIP_WAITING')self.skipWaiting();});
self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET' || new URL(event.request.url).origin!==self.location.origin)return;
  const url=new URL(event.request.url);
  const asset=FILES.some(path=>new URL(path,self.registration.scope).pathname===url.pathname);
  if(!asset && event.request.mode!=='navigate')return;
  event.respondWith((async()=>{
    const cache=await caches.open(CACHE);
    if(event.request.mode==='navigate') return await cache.match('./index.html') || fetch(event.request);
    return await cache.match(event.request,{ignoreSearch:true}) || fetch(event.request);
  })());
});
