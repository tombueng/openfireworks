// Single-page web UI, served from flash. %N% is replaced per request with a CSP nonce.
// Jack numbers J1..J24 are shown to the operator; the API uses channel index 0..23 (= J - 1).
//
// Mobile first, for outdoor use at night or in the cold with gloves on a phone:
// - big touch targets (>= 52 px), 17 px base text, no double-tap zoom, no long-press menu;
// - STOP is a full-width bar at the bottom (thumb reach), fires on touch-down, works without login;
// - FIRE is press-and-hold (0.9 s, the button fills) instead of two taps: robust with gloves, hard to
//   trigger by brushing the screen; releasing early cancels;
// - the channel grid is only rebuilt when its content changes and never while a finger is down;
// - a banner shows when the node has not answered for 3 s; FIRE is then hidden (stale data);
// - "Sun" toggles a high-contrast light theme for daylight; the screen is kept awake (Wake Lock);
// - diagnostics (device, self-test, battery, events, settings) are folded away below the channels.
#pragma once

static const char WEBUI_HTML[] = R"HTML(<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name=color-scheme content="dark light">
<title>Firing node</title>
<style nonce="%N%">
:root{--bg:#0d1117;--card:#161b22;--line:#3d444d;--tx:#f0f3f6;--mu:#9da7b3;--ok:#3fb950;--warn:#e3b341;--bad:#ff6a69;--arm:#ff2d55;--info:#58a6ff;--btn:#262c34;--fire:#ff2d55;--firetx:#fff}
body.sun{--bg:#fff;--card:#f3f3f3;--line:#222;--tx:#000;--mu:#333;--ok:#006b1b;--warn:#8a5a00;--bad:#c00000;--arm:#c00030;--info:#0645ad;--btn:#e2e2e2}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--tx);font:17px/1.35 system-ui,-apple-system,sans-serif;padding-bottom:calc(96px + env(safe-area-inset-bottom))}
button,label.ov,.firebtn{touch-action:manipulation;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:2px solid var(--line);padding:8px 10px;padding-top:calc(8px + env(safe-area-inset-top));display:flex;gap:8px;align-items:center}
header .t{flex:1;min-width:0}header b{font-size:18px}.mu{color:var(--mu);font-size:15px}
.badge{display:inline-block;padding:3px 10px;border-radius:12px;font-weight:800;font-size:16px;vertical-align:middle}
.SAFE{background:#1f3d2a;color:#5ee07a}.ARMED{background:var(--arm);color:#fff}.FAULT{background:#5a1d1d;color:#ffc9c5}.BOOT{background:#1d2d4a;color:#8cc4ff}
button{font:inherit;color:var(--tx);background:var(--btn);border:2px solid var(--line);border-radius:12px;min-height:52px;padding:10px 14px;cursor:pointer}
button:active{filter:brightness(1.4)}button:disabled{opacity:.35}
.sunb{min-height:44px;min-width:56px;padding:6px 10px;font-size:15px}
.stopbar{position:fixed;left:0;right:0;bottom:0;z-index:9;padding:8px 10px calc(8px + env(safe-area-inset-bottom));background:var(--bg);border-top:2px solid var(--line)}
.stop{display:block;width:100%;min-height:68px;background:#c00000;border:3px solid #ff8080;color:#fff;font-weight:900;font-size:28px;letter-spacing:.12em}
#conn{position:sticky;top:64px;z-index:4;background:#7a1d00;color:#fff;font-weight:800;text-align:center;padding:10px;font-size:17px}
.armb{background:#6e1a1a;border-color:var(--arm);color:#fff;font-weight:800}body.sun .armb{background:#ffd6dd;color:#900}
main{padding:10px;max-width:1100px;margin:auto}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px;margin-bottom:10px}
h2{font-size:15px;margin:0 0 8px;color:var(--mu);text-transform:uppercase;letter-spacing:.05em}
.acts{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}.acts #arm{grid-column:1/-1;min-height:64px;font-size:22px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px 12px}
.kv div span{color:var(--mu);font-size:14px;display:block}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}@media(min-width:420px){.grid{grid-template-columns:repeat(4,1fr)}}@media(min-width:760px){.grid{grid-template-columns:repeat(6,1fr)}}
.ch{border:3px solid var(--line);border-radius:12px;padding:7px;font-size:14px;min-height:104px;display:flex;flex-direction:column;gap:2px}
.ch .n{font-weight:900;font-size:22px;line-height:1.1}.ch.ok{border-color:var(--ok)}.ch.open{border-color:var(--warn)}.ch.short{border-color:var(--bad);background:#3a1414}
body.sun .ch.short{background:#ffe0e0}.ch.noplug{opacity:.6}.ch.fired{border-color:#999;background:#24272c}body.sun .ch.fired{background:#ddd}
.ch.elig{box-shadow:0 0 0 3px var(--arm) inset}
.cls{font-weight:800;font-size:16px}.c-ok{color:var(--ok)}.c-open{color:var(--warn)}.c-short{color:var(--bad)}.c-noplug{color:var(--mu)}
.firebtn{position:relative;overflow:hidden;margin-top:auto;width:100%;min-height:58px;background:var(--fire);border:2px solid #ff9db0;color:var(--firetx);font-weight:900;font-size:17px;padding:4px}
.firebtn::before{content:"";position:absolute;left:0;top:0;bottom:0;width:0;background:#fff;opacity:.55}
.firebtn.hold::before{width:100%;transition:width .9s linear}.firebtn span{position:relative}
label.ov{margin-top:auto;display:flex;gap:8px;align-items:center;justify-content:center;min-height:48px;border:2px solid var(--line);border-radius:10px;font-size:15px;color:var(--mu)}
label.ov input{width:24px;height:24px;margin:0}label.ov.on{border-color:var(--info);color:var(--tx)}
.pass{color:var(--ok)}.FAIL{color:var(--bad);font-weight:800}.skip{color:var(--mu)}
input,textarea{font:inherit;font-size:17px;background:var(--bg);color:var(--tx);border:2px solid var(--line);border-radius:10px;padding:10px;min-height:52px}
textarea{width:100%;min-height:120px;font-family:ui-monospace,monospace}
details{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:10px}
summary{min-height:52px;padding:14px 12px;font-weight:700;color:var(--mu);text-transform:uppercase;letter-spacing:.05em;font-size:15px;cursor:pointer;touch-action:manipulation}
details>div{padding:0 10px 10px}
.ev{font:14px ui-monospace,monospace;max-height:320px;overflow:auto;white-space:pre-wrap}.hide{display:none}.err{color:var(--bad);font-weight:700}
.mb{margin-bottom:6px}.mt{margin-top:8px}.w90{width:90px}.w150{width:150px}.lnk{color:var(--info);padding:14px 4px;display:inline-block}
.big{font-size:19px;font-weight:800}
</style></head><body>
<header><div class=t><b id=hn>Firing node</b> <span id=hs class="badge BOOT">...</span><div class=mu id=hsub></div></div>
<button class=sunb id=sun>Sun</button></header>
<div id=conn class=hide></div>
<main>
<div id=login class=card><h2>Sign in</h2><div class=row><input id=pw type=password placeholder=Password autocomplete=current-password>
<button id=lb>Login</button></div><div class=err id=le></div>
<div class="mu mt">STOP works without signing in. The password was printed once on the USB console.</div></div>
<div id=app class=hide>
<div class=card><div class=acts>
<button id=arm class=armb>ARM</button><button id=scan>Continuity</button><button id=self>Self-test</button><button id=bat>Battery</button></div>
<div id=armmsg class="big mt"></div><div class=err id=fault></div></div>
<div class=card><h2>Channels</h2><div class="mu mb">green = e-match OK · yellow = plug, match open · red = short · grey = no plug · red frame = will fire when armed. Armed: <b>hold FIRE</b> until it is full.</div><div class=grid id=grid></div></div>
<div class=card><h2>Sequence</h2><div class=mu>One cue per line: seconds after start, jack 1-24. Example: <code>0 1</code> / <code>2.5 2</code>. The node disarms when the list is done.</div>
<textarea id=cues placeholder="0 1&#10;2.5 2&#10;5 3"></textarea>
<div class="acts mt"><button id=ld>Load</button><button id=go class=armb>Start</button><button id=clr>Clear</button></div><div id=sq class="mu mt"></div></div>
<details><summary>Battery (loaded test)</summary><div class=kv id=bt></div></details>
<details><summary>Self-test</summary><div class=kv id=st></div></details>
<details><summary>Device</summary><div class=kv id=dev></div></details>
<details><summary>Events</summary><div class=ev id=ev></div></details>
<details><summary>Settings</summary><div>
<div class=row><span class=mu>Pulse ms</span><input id=pl class=w90 type=number inputmode=decimal min=2 max=15 step=0.5><button id=pls>Set</button></div>
<div class="row mt"><span class=mu>Name</span><input id=nm class=w150 maxlength=20><button id=nms>Set</button></div>
<div class="row mt"><input id=op type=password placeholder="Old password" autocomplete=current-password>
<input id=np type=password placeholder="New password (min 8)" autocomplete=new-password><button id=pwc>Change password</button><span id=pwm class=mu></span></div>
<div class="row mt"><button id=bth class=hide>Set birth time from this phone</button><a href=/cert.pem class=lnk>Device certificate</a><button id=lo>Logout</button></div></div></details>
</div></main>
<div class=stopbar><button class=stop id=stop>STOP</button></div>
<script nonce="%N%">
let csrf='',S=null,lastOk=0,lastG='',holdI=-1,holdT=0,stopT=0,wl=null;const $=i=>document.getElementById(i);
const HOLD_MS=900,STALE_MS=3000;
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function buzz(p){try{navigator.vibrate&&navigator.vibrate(p)}catch(e){}}
async function keepAwake(){try{if('wakeLock' in navigator&&!wl&&document.visibilityState=='visible'){wl=await navigator.wakeLock.request('screen');wl.addEventListener('release',()=>{wl=null})}}catch(e){}}
async function post(u,b){let r=await fetch(u,{method:'POST',headers:{'X-CSRF-Token':csrf,'Content-Type':'application/x-www-form-urlencoded'},body:b||''});if(r.status==401){show(0)}return r}
function show(a){$('login').className=a?'card hide':'card';$('app').className=a?'':'hide'}
function ago(ms){let s=Math.round(ms/1000);return s<60?s+' s':s<3600?Math.round(s/60)+' min':Math.round(s/3600)+' h'}
function kv(id,a){$(id).innerHTML=a.map(x=>'<div><span>'+x[0]+'</span>'+x[1]+'</div>').join('')}
function tcls(v){return '<b class="'+v+'">'+v+'</b>'}
function stale(){return !lastOk||Date.now()-lastOk>STALE_MS}
async function load(){let r;try{r=await fetch('/api/status',{cache:'no-store'})}catch(e){conn();return}
if(r.status==401){lastOk=Date.now();show(0);conn();return}let s;try{s=await r.json()}catch(e){return}if(s.error)return;lastOk=Date.now();S=s;csrf=s.csrf;show(1);render(s);conn()}
function conn(){let c=$('conn');if(lastOk&&stale()){c.textContent='NO CONNECTION to the node — data '+Math.round((Date.now()-lastOk)/1000)+' s old';c.className=''}else if(!lastOk){c.textContent='connecting…';c.className=''}else c.className='hide';
if(S&&stale()&&lastG!=='stale'){lastG='';render(S)}}
function render(s){let armed=s.state=='ARMED',old=stale();$('hn').textContent=s.name;let b=$('hs');b.textContent=s.state;b.className='badge '+s.state;
$('hsub').textContent=s.ssid+' · '+s.vsys+' V · '+(armed?'armed '+ago(s.armedMs)+' (auto-disarm '+Math.round(s.armTimeoutS/60)+' min)':'ready '+s.ch.filter(c=>c.cls=='ok'&&!c.fired).length+'/24');
$('fault').textContent=s.state=='FAULT'?'FAULT: '+s.fault+' — reset the node (SW1 off/on) to clear':'';
$('arm').disabled=s.state!='SAFE'||s.st.all!='pass'||old;$('arm').textContent=armed?'ARMED — STOP to disarm':'ARM';
$('armmsg').textContent=s.armPending?'Press BOOT on the node now ('+Math.ceil(s.armPendingMs/1000)+' s)':(s.st.all!='pass'?'Arming needs a passed self-test.':'');
['scan','self','bat'].forEach(i=>$(i).disabled=s.state!='SAFE'||old);
let g='';s.ch.forEach((c,i)=>{let k=c.fired?'fired':c.cls;let cl='ch '+k+(c.elig&&armed?' elig':'');
let info=c.cls=='noplug'?'no plug':(c.cls=='ok'?'OK':c.cls=='open'?'plug, open':c.cls=='short'?'SHORT':'?');
let r=c.cls=='ok'||c.cls=='short'?'&lt;0.5 kΩ':(c.r!=null&&c.r>=0?'~'+Math.round(c.r/1000)+' kΩ':'');
let h='<div class="'+cl+'"><div class=n>J'+(i+1)+'</div><div class="cls c-'+c.cls+'">'+info+'</div><div class=mu>'+(c.v!=null&&c.v>=0?c.v.toFixed(2)+' V ':'')+r+'</div>';
if(c.fired)h+='<div>fired '+ago(c.firedAgo)+' ago, '+c.res+' '+(c.fms||0).toFixed(1)+' ms</div>';
if(c.fault)h+='<div class=err>'+esc(c.fault)+'</div>';
if(armed){h+=c.elig&&!old?'<button class=firebtn data-f='+i+'><span>HOLD TO FIRE</span></button>':'<div class=mu>'+(old?'no connection':'not ready')+'</div>'}
else if(s.state=='SAFE'&&c.cls!='noplug'){h+='<label class="ov'+(c.ovr?' on':'')+'"><input type=checkbox data-o='+i+(c.ovr?' checked':'')+'>override</label>'}
g+=h+'</div>'});
if(holdI<0&&g!==lastG){$('grid').innerHTML=g;lastG=old?'stale':g}
kv('dev',[['VSYS now / rest',s.vsys+' / '+s.vrest+' V'],['VFIRE',s.vfire+' V'],['V5_LED (estimate)',s.v5led+' V'],['Chip temp',s.temp==null?'-':s.temp+' °C'],
['FW_ARM / FW_OE',s.fwArm+' / '+s.fwOe],['OE readback (GPIO2)',s.oeRb+(s.oeRb?' (gates off)':' (gates enabled)')],['Arm key','none on r3: '+(s.armBtn?'BOOT button confirms web arming':'BOOT confirm OFF')],
['Pulse',s.pulse+' ms'],['WiFi clients',s.clients+(s.clients?' (weakest '+s.rssiMin+' dBm)':'')],['Uptime',ago(s.uptime)],['Watchdog',s.wdt+' ms'],['Chain latched','0x'+s.latched],
['Serial',esc(s.serial)+(s.birthUnknown?' (birth time unknown)':'')],['Firmware',esc(s.fw+' '+s.variant+' '+s.build)]]);
kv('st',Object.keys(s.st).filter(k=>k!='at').map(k=>[k,tcls(s.st[k])]).concat([['run',s.st.at?ago(s.uptime-s.st.at)+' ago':'-']]));
let B=s.batt;kv('bt',[['result',tcls(B.ok)],['rest',B.rest+' V'],['under load',B.load+' V @ '+B.loadMa+' mA'],['R internal',B.r+' Ω'],['predicted fire current',B.ipred+' A (min 1.2)'],['run',B.at?ago(s.uptime-B.at)+' ago':'-']]);
$('sq').textContent=s.seqRun?('running: cue '+s.seqIdx+'/'+s.seqN+' at '+(s.seqT/1000).toFixed(1)+' s'):(s.seqN?s.seqN+' cue(s) loaded':'no cues loaded');
$('go').disabled=!armed||s.seqRun||!s.seqN||old;$('ld').disabled=armed||s.seqRun;
$('ev').textContent=s.ev.map(e=>'['+(e.t/1000).toFixed(1)+'] '+e.m).join('\n');
if(document.activeElement!=$('pl'))$('pl').value=s.pulse;if(document.activeElement!=$('nm'))$('nm').value=s.name;
$('bth').className=s.birthUnknown?'':'hide'}
// hold-to-fire (event delegation: survives grid rebuilds)
function holdEnd(){if(holdI<0)return;clearTimeout(holdT);let e=document.querySelector('[data-f="'+holdI+'"]');if(e)e.classList.remove('hold');holdI=-1}
$('grid').addEventListener('pointerdown',ev=>{let e=ev.target.closest('[data-f]');if(!e||stale())return;ev.preventDefault();keepAwake();holdEnd();
holdI=+e.dataset.f;e.classList.add('hold');buzz(20);try{e.setPointerCapture(ev.pointerId)}catch(x){}
holdT=setTimeout(()=>{let i=holdI;holdEnd();if(i<0||stale())return;buzz([80,40,80]);post('/api/fire','ch='+i).then(load)},HOLD_MS)});
['pointerup','pointercancel','lostpointercapture'].forEach(t=>$('grid').addEventListener(t,holdEnd));
$('grid').addEventListener('contextmenu',ev=>ev.preventDefault());
$('grid').addEventListener('change',ev=>{let e=ev.target;if(!e.dataset||e.dataset.o==null)return;
if(e.checked&&!confirm('Override J'+(+e.dataset.o+1)+': fire it even without plug/continuity OK, or again after it fired?')){e.checked=false;return}
post('/api/override','ch='+e.dataset.o+'&on='+(e.checked?1:0)).then(load)});
function stop(){if(Date.now()-stopT<500)return;stopT=Date.now();buzz([120,60,120]);holdEnd();fetch('/api/stop',{method:'POST'}).then(load,load)}
$('stop').addEventListener('pointerdown',ev=>{ev.preventDefault();stop()});$('stop').onclick=stop;
function theme(t){document.body.classList.toggle('sun',t=='sun');$('sun').textContent=t=='sun'?'Night':'Sun';try{localStorage.setItem('ofw_theme',t)}catch(e){}}
$('sun').onclick=()=>theme(document.body.classList.contains('sun')?'night':'sun');
try{theme(localStorage.getItem('ofw_theme')||'night')}catch(e){theme('night')}
$('lb').onclick=async()=>{let r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'password='+encodeURIComponent($('pw').value)});$('pw').value='';
if(r.ok){$('le').textContent='';load()}else $('le').textContent=r.status==429?'Too many attempts - wait':'Wrong password'};
$('pw').onkeydown=e=>{if(e.key=='Enter')$('lb').onclick()};
$('arm').onclick=()=>{keepAwake();if(confirm('ARM the node? Firing becomes possible. '+(S&&S.armBtn?'You must press BOOT on the node within 30 s.':'')))post('/api/arm').then(load)};
$('scan').onclick=()=>post('/api/scan');$('self').onclick=()=>post('/api/selftest');$('bat').onclick=()=>post('/api/batt');
$('ld').onclick=async()=>{let r=await post('/api/seq','cues='+encodeURIComponent($('cues').value));let j=await r.json();$('sq').textContent=j.ok?j.n+' cue(s) loaded':'error: '+j.error};
$('go').onclick=()=>{if(confirm('Start the sequence now?'))post('/api/seqstart').then(load)};$('clr').onclick=()=>post('/api/seqclear');
$('pls').onclick=()=>post('/api/pulse','ms10='+Math.round(parseFloat($('pl').value)*10));
$('nms').onclick=()=>post('/api/name','name='+encodeURIComponent($('nm').value));
$('pwc').onclick=async()=>{let r=await post('/api/passwd','old='+encodeURIComponent($('op').value)+'&new='+encodeURIComponent($('np').value));$('pwm').textContent=r.ok?'changed':'failed';$('op').value='';$('np').value=''};
$('bth').onclick=()=>post('/api/birthtime','epochMs='+Date.now());
$('lo').onclick=async()=>{await post('/api/logout');show(0)};
document.addEventListener('visibilitychange',()=>{if(document.visibilityState=='visible'){keepAwake();load()}else holdEnd()});
document.addEventListener('pointerdown',keepAwake,{once:true});
load();setInterval(load,1000);setInterval(conn,500);
</script></body></html>)HTML";
