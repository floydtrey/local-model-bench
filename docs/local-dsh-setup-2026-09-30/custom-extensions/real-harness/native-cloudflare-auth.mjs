/** Host-profile extension: verified Access identity for the public Lab authority.
 * Native connection methods are synchronous, including WebSocket admission.
 * Public signing keys refresh asynchronously; no user credential is stored.
 */
import {readFileSync} from 'node:fs';
import {createPublicKey, verify} from 'node:crypto';

export const name='lab-native-cloudflare-auth';
export const inject=['connection'];
export const HOST='LAB_PUBLIC_HOST';
const MAX_AGE=3600_000;

export function verifyIdentity(token,keys,settings,now=Date.now()) {
  try {
    if(typeof token!=='string'||token.length>16384) return false;
    const parts=token.split('.');
    if(parts.length!==3||parts.some(p=>!p||!/^[A-Za-z0-9_-]+$/.test(p))) return false;
    const header=JSON.parse(Buffer.from(parts[0],'base64url'));
    const claims=JSON.parse(Buffer.from(parts[1],'base64url'));
    if(header.alg!=='RS256'||typeof header.kid!=='string'||header.crit!==undefined) return false;
    const key=keys.get(header.kid);
    if(!key||!verify('RSA-SHA256',Buffer.from(parts.slice(0,2).join('.')),key,Buffer.from(parts[2],'base64url'))) return false;
    const t=now/1000;
    if(!Number.isFinite(claims.exp)||!Number.isFinite(claims.iat)||claims.exp<=t||claims.iat>t+5||claims.exp<=claims.iat) return false;
    if(claims.nbf!==undefined&&(!Number.isFinite(claims.nbf)||claims.nbf>t+5)) return false;
    if(claims.iss!==settings.issuer||!Array.isArray(claims.aud)||!claims.aud.includes(settings.audience)) return false;
    return claims.type==='app'&&typeof claims.sub==='string'&&claims.sub.length>0&&claims.sub.length<=512&&typeof claims.email==='string'&&claims.email.toLowerCase()===settings.owner;
  } catch {return false;}
}

export function attach(connection,authenticate) {
  if(typeof connection.requestRejection!=='function'||typeof connection.authorizeIndex!=='function') throw Error('Native authentication interface changed');
  const reject=connection.requestRejection, index=connection.authorizeIndex;
  const remote=req=>typeof req.headers?.host==='string'&&[HOST,HOST+':443'].includes(req.headers.host.toLowerCase());
  function requestRejection(req) {
    const native=reject.call(connection,req);
    if(!remote(req)) return native;
    // Preserve native Host, Origin and Fetch-Metadata rejection even with a valid JWT.
    if(native===403) return 403;
    if(native!==undefined&&native!==401) return native;
    return authenticate(req.headers['cf-access-jwt-assertion'])?undefined:401;
  }
  function authorizeIndex(req,res) {
    if(!remote(req)) return index.call(connection,req,res);
    const rejection=requestRejection(req);
    if(rejection===undefined) return true;
    res.writeHead(rejection,{'content-type':'text/plain; charset=utf-8','cache-control':'no-store'});
    res.end('Cloudflare sign-in could not be verified. Reload after signing in, or try again shortly.');
    return false;
  }
  connection.requestRejection=requestRejection;
  connection.authorizeIndex=authorizeIndex;
  return ()=>{
    if(connection.requestRejection===requestRejection)connection.requestRejection=reject;
    if(connection.authorizeIndex===authorizeIndex)connection.authorizeIndex=index;
  };
}

export function apply(ctx) {
  // Reuse the existing bridge's authority configuration; never read its owner API key.
  const cfg=JSON.parse(readFileSync('${USERPROFILE}/AppData/Local/KnowledgeCore/remote-dashboard/state/config.json','utf8'));
  if(!/^[a-z0-9][a-z0-9-]{0,62}$/.test(cfg.access_team)||typeof cfg.access_audience!=='string'||!cfg.access_audience||typeof cfg.owner_email!=='string'||!cfg.owner_email.includes('@')) throw Error('Existing Access configuration is invalid');
  const settings={issuer:`https://${cfg.access_team}.cloudflareaccess.com`,audience:cfg.access_audience,owner:cfg.owner_email.toLowerCase()};
  let keys=new Map(),freshUntil=0,inflight,lastAttempt=0,disposed=false;
  const controller=new AbortController();
  async function refresh() {
    if(disposed||inflight||Date.now()-lastAttempt<30_000)return;
    lastAttempt=Date.now();
    inflight=(async()=>{
      const response=await fetch(settings.issuer+'/cdn-cgi/access/certs',{redirect:'error',signal:AbortSignal.any([controller.signal,AbortSignal.timeout(8000)])});
      if(!response.ok)throw Error('Access public keys unavailable');
      const body=await response.json(),next=new Map();
      if(!Array.isArray(body.keys)||body.keys.length>32)throw Error('Invalid Access public keys');
      for(const jwk of body.keys)if(jwk.kty==='RSA'&&jwk.alg==='RS256'&&jwk.use==='sig'&&typeof jwk.kid==='string')next.set(jwk.kid,createPublicKey({key:jwk,format:'jwk'}));
      if(!next.size)throw Error('No Access public signing keys');
      if(!disposed){keys=next;freshUntil=Date.now()+MAX_AGE;}
    })().catch(()=>{ /* Keep still-fresh keys; stale/missing keys deny access. Never log tokens. */ }).finally(()=>{inflight=undefined;});
    await inflight;
  }
  ctx.effect(()=>{
    const detach=attach(ctx.connection,token=>{
      if(Date.now()>=freshUntil){void refresh();return false;}
      const valid=verifyIdentity(token,keys,settings);
      if(!valid&&typeof token==='string')void refresh();
      return valid;
    });
    void refresh();
    const timer=setInterval(()=>void refresh(),300_000);timer.unref();
    return ()=>{disposed=true;clearInterval(timer);controller.abort();detach();};
  });
}
