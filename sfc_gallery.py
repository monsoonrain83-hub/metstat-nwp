"""Render the public five-month Iran forecast with the production map renderer."""
import hashlib
import json
import os
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

SITE = os.getenv('SITE_URL', 'https://wtafkik.ir')
BASE = SITE + '/online/data/sfc/'
KINDS = ['c', 'mean', 'skill'] + [f'm{i}' for i in range(1, 11)]


def read(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def publish(name, data):
    target = os.getenv('MX_HOST')
    if not target:
        out = Path('gallery_out')
        out.mkdir(exist_ok=True)
        (out / name).write_bytes(data)
        return
    url = target.rstrip('/') + '/nwp_upload.php?a=sfput&name=' + name + '&key=' + os.environ['MX_KEY']
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=180) as response:
        if json.load(response).get('ok') is not True:
            raise RuntimeError('Map upload failed')


def main():
    inputs = json.loads(read(BASE + 'sfc_idx.json'))
    issued = inputs['issued']
    if not inputs.get('fc', {}).get('z') or inputs['fc'].get('mock'):
        raise ValueError('Missing SEAS forecast')
    catalog = {'issued': issued, 'run': inputs['fc']['start'], 'products': {}}
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
            page.add_init_script("localStorage.setItem('mmap.lang',JSON.stringify('" + lang + "'))")
            page.goto(SITE + '/index.html',wait_until='domcontentloaded',timeout=120000)
            page.wait_for_function("typeof sfShowMap === 'function'")
            page.evaluate("""async () => {await sfLoad(); const box=document.createElement('div');
              box.id='sfMapBox'; document.body.append(box);}""")
            for par, pack in packs.items():
                rows = products[par] = []
                page.evaluate("""p=>{SF.o.par=p.par; SF.o.reg=''; SF.upd=new Date(p.built);
                  SF.out.auto=p; SF.cards.clear();}""",pack)
                for idx in range(5):
                    row = {'label':page.evaluate('i=>sfMonLab(SF.out.auto.T[i].t)',idx),'maps':{}}
                    for kind in KINDS:
                        png = page.evaluate("""async ([ti,kind])=>{
                          SF.views.auto={mode:'auto',ti,kind}; SF.cards.clear();
                          const box=document.getElementById('sfMapBox'); box.replaceChildren();
                          await sfShowMap('auto'); return box.querySelector('.caImgWrap img').src;
                        }""",[idx,kind])
                        if not png.startswith('data:image/png;base64,iVBOR'):
                            raise ValueError('Invalid rendered PNG')
                        data = json.dumps({'png':png}).encode()
                        name = 'g_' + hashlib.sha256(data).hexdigest()[:32]
                        publish(name + '.json',data)
                        row['maps'][kind] = name
                    rows.append(row)
            page.close()
        browser.close()
    if json.loads(read(BASE + 'sfc_idx.json'))['issued'] != issued:
        raise RuntimeError('Inputs changed during rendering')
    publish('gallery_latest.json',json.dumps(catalog,ensure_ascii=False).encode())


if __name__ == '__main__':
    main()
