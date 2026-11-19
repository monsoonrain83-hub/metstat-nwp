"""Render the public five-month Iran forecast with the production map renderer."""
import sys
import hashlib
import base64
import struct
import json
import os
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright

SITE = os.getenv('SITE_URL', 'https://wtafkik.ir')
BASE = SITE + '/online/data/sfc/'
KINDS = ['c', 'mean', 'skill'] + [f'm{i}' for i in range(1, 11)]


def read(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'Cache-Control':'no-cache'}), timeout=120) as response:
        return response.read()


def publish(name, data):
    target = os.getenv('MX_HOST')
    if not target:
        out = Path('gallery_out')
        out.mkdir(exist_ok=True)
        (out / name).write_bytes(data)
        return
    url = target.rstrip('/') + '/nwp_upload.php?' + urlencode({'a':'sfput','name':name,'key':os.environ['MX_KEY']})
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=180) as response:
        if json.load(response).get('ok') is not True:
            raise RuntimeError('Map upload failed')


def main():
    smoke = '--smoke' in sys.argv
    if smoke and os.getenv('MX_HOST'):
        raise ValueError('Smoke tests cannot publish to the host')
    kinds = ['c', 'mean', 'skill', 'm1', 'm10'] if smoke else KINDS
    index_data = read(BASE + 'sfc_idx.json')
    era_data = read(BASE + 'era5_iran.json')
    inputs = json.loads(index_data)
    source_hash = hashlib.sha256(index_data + era_data).hexdigest()
    issued = inputs['issued']
    if not inputs.get('fc', {}).get('z') or inputs['fc'].get('mock'):
        raise ValueError('Missing SEAS forecast')
    catalog = {'version': 0 if smoke else 1, 'source_sha256': source_hash, 'built': datetime.now(timezone.utc).isoformat(), 'issued': issued, 'run': inputs['fc']['start'], 'products': {}}
    pack_dir = os.getenv('SFC_PACK_DIR')
    packs = {}
    for p in ('prcp', 'tmean'):
        filename = f'sfc_result_{p}.json'
        raw = (Path(pack_dir) / filename).read_bytes() if pack_dir else read(BASE + filename)
        packs[p] = json.loads(raw)
    for par, pack in packs.items():
        if pack['issued'].replace('.000Z','Z') != issued.replace('.000Z','Z') or pack['par'] != par or len(pack['T']) != 5:
            raise ValueError('Incomplete or mismatched product ' + par)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv('CHROME_BIN') or None)
        for lang in ('fa','en'):
            products = catalog['products'][lang] = {}
            page = browser.new_page(viewport={'width':1200,'height':900})
            page.set_default_timeout(900000)
            page.route('**/version.json*', lambda route: route.abort())
            page.route('**/online/data/sfc/sfc_idx.json*', lambda route: route.fulfill(body=index_data, content_type='application/json'))
            page.route('**/online/data/sfc/era5_iran.json*', lambda route: route.fulfill(body=era_data, content_type='application/json'))
            page.add_init_script("localStorage.setItem('mmap.lang',JSON.stringify('" + lang + "'))")
            page.goto(SITE + '/index.html',wait_until='domcontentloaded',timeout=120000)
            page.wait_for_function("typeof sfShowMap === 'function'")
            page.evaluate("""async () => {
              await sfLoad();
              const box=document.createElement('div');
              box.id='sfMapBox'; document.body.append(box);
              // Export the unchanged canvas without installing interactive resize handlers.
              // Each normal card retains its canvas through a window listener.
              window.caCard=(title,canvas,note,host)=>{
                const card=document.createElement('article'), wrap=document.createElement('div');
                wrap.className='caImgWrap';
                const image=new Image(); image.src=canvas.toDataURL('image/png');
                wrap.append(image);card.append(wrap);host.prepend(card);return card;
              };
            }""")
            for par, pack in packs.items():
                rows = products[par] = []
                page.evaluate("""p=>{SF.o.par=p.par; SF.o.reg=''; SF.upd=new Date(p.built);
                  SF.out.auto=p; SF.cards.clear();}""",pack)
                for idx in range(1 if smoke else 5):
                    row = page.evaluate('''i => {const t=SF.out.auto.T[i].t; return {t,label:sfMonLab(t),validUntil:new Date(sfGDate(t).getTime()+15*864e5).toISOString(),maps:{}}}''',idx)
                    for kind in kinds:
                        print('Rendering',lang,par,idx+1,kind,flush=True)
                        png = page.evaluate("""async ([ti,kind])=>{
                          SF.views.auto={mode:'auto',ti,kind}; SF.cards.clear();
                          const box=document.getElementById('sfMapBox'); box.replaceChildren();
                          await sfShowMap('auto'); return box.querySelector('.caImgWrap img').src;
                        }""",[idx,kind])
                        if not png.startswith('data:image/png;base64,iVBOR'):
                            raise ValueError('Invalid rendered PNG')
                        raw_png = base64.b64decode(png.split(',',1)[1], validate=True)
                        width, height = struct.unpack('>II',raw_png[16:24])
                        if min(width,height) < 1000:
                            raise ValueError('Unexpected map dimensions')
                        data = json.dumps({'png':png}).encode()
                        name = 'g_' + hashlib.sha256(data).hexdigest()[:32]
                        publish(name + '.json',data)
                        row['maps'][kind] = name
                    rows.append(row)
                    print(lang, par, idx + 1, 'rendered', flush=True)
            page.close()
        browser.close()
    if hashlib.sha256(read(BASE + 'sfc_idx.json') + read(BASE + 'era5_iran.json')).hexdigest() != source_hash:
        raise RuntimeError('Inputs changed during rendering')
    publish('gallery_preview.json' if smoke else 'gallery_latest.json',json.dumps(catalog,ensure_ascii=False).encode())


if __name__ == '__main__':
    main()
