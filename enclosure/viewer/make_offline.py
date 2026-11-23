#!/usr/bin/env python3
"""Build ONE self-contained viewer file for people without a claude.ai login: index.html with every GLB embedded as
base64, opened by double click (file://, no server). Only three.js still comes from cdn.jsdelivr.net (internet).
Run after viewer/make_assets.py:  python3 enclosure/viewer/make_offline.py
Out: export/viewer/OpenFireworks_enclosure_viewer.html
"""
import base64, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "export", "viewer", "OpenFireworks_enclosure_viewer.html")
NAMES = ["base", "lid", "windows", "leds", "pcb", "antenna"]

OLD = "  loader.load(file+'.glb', (gltf)=>{"
NEW = ("  Promise.resolve(document.getElementById('glb-'+file).textContent)\n"
       "   .then(t=>{ const s=atob(t.trim()), b=new Uint8Array(s.length); for(let i=0;i<s.length;i++) b[i]=s.charCodeAt(i);\n"
       "              return new Promise((ok,bad)=>loader.parse(b.buffer,'',ok,bad)); })\n"
       "   .then((gltf)=>{")
OLD_END = "  }, undefined, (err)=>{ document.getElementById('loading').textContent='failed to load '+file+'.glb — run serve.sh (needs http)'; console.error(err); });"
NEW_END = "  }).catch((err)=>{ document.getElementById('loading').textContent='failed to load '+file; console.error(err); });"


def main():
    html = open(os.path.join(HERE, "index.html")).read()
    assert OLD in html and OLD_END in html, "viewer load code changed: update make_offline.py"
    html = html.replace(OLD, NEW).replace(OLD_END, NEW_END)
    html = html.replace("loader.setRequestHeader({'Cache-Control':'no-cache'});", "")
    blobs = "".join('<script type="application/octet-stream" id="glb-%s">%s</script>\n'
                    % (n, base64.b64encode(open(os.path.join(HERE, n + ".glb"), "rb").read()).decode()) for n in NAMES)
    i = html.index("<script type=\"importmap\"") if "<script type=\"importmap\"" in html else html.index("<script")
    html = html[:i] + blobs + html[i:]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write(html)
    print("offline viewer -> %s (%.1f MB)" % (OUT, os.path.getsize(OUT) / 1e6))


if __name__ == "__main__":
    main()
