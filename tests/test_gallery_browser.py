"""Browser regression checks for the public forecast viewer, without model data."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6VAAAAABJRU5ErkJggg=='
NAMES = ['g_' + str(i) * 32 for i in range(1, 4)]
KINDS = ['c','mean','skill'] + [f'm{i}' for i in range(1,11)]
ROWS = [dict(label=f'Month {i}', t=1000+i, validUntil='2099-01-01T00:00:00Z', maps={k:NAMES[i] for k in KINDS}) for i in range(2)]
CATALOG = dict(version=1, issued='2026-11-19T00:00:00Z', run=[2026,11], products={lang:{par:ROWS for par in ('prcp','tmean')} for lang in ('fa','en')})

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    requests = []
    fail = {'catalog': False, 'image': False}
    def serve(route):
        url = route.request.url
        requests.append(url)
        if url.endswith('/test'):
            route.fulfill(body='<div id="host"></div>',content_type='text/html')
        elif url.endswith('gallery_latest.json'):
            route.fulfill(status=503 if fail['catalog'] else 200, json=CATALOG)
        elif '/g_' in url:
            route.fulfill(status=503 if fail['image'] else 200, json={'png':PNG})
        else:
            raise AssertionError('Unexpected request '+url)
    page.route('http://gallery.test/**', serve)
    page.goto('http://gallery.test/test')
    page.add_script_tag(content="let LANG='en'; const SF={o:{par:'prcp'}}; function sfSave(){}; let advancedCalls=0; function openSF(flag){if(flag===true)advancedCalls++;}")
    page.add_script_tag(path=str(ROOT/'host/assets/sfc_gallery.js'))
    # A generated browser PNG avoids decoder differences in fixture images.
    PNG = page.evaluate("()=>{const c=document.createElement('canvas');c.width=c.height=8;c.getContext('2d').fillRect(0,0,8,8);return c.toDataURL()}")
    page.evaluate("sfOpenPublished(document.getElementById('host'))")
    assert page.locator('img').is_visible()
    assert len([u for u in requests if '/g_' in u]) == 1
    page.locator('select').nth(1).select_option('1001')
    page.wait_for_function("document.querySelector('img').alt.startsWith('Month 1')")
    page.locator('select').nth(0).select_option('tmean')
    page.wait_for_function("document.querySelector('a').download.includes('tmean_1001')")
    assert page.locator('select').nth(1).input_value() == '1001'
    page.locator('button').last.click()
    assert page.evaluate('advancedCalls') == 1
    fail['catalog'] = True
    page.evaluate("sfOpenPublished(document.getElementById('host'))")
    assert not page.locator('img').is_visible()
    assert page.get_by_role('button',name='Retry',exact=True).is_visible()
    fail['catalog'] = False
    fail['image'] = True
    page.get_by_role('button',name='Retry',exact=True).click()
    page.wait_for_function("document.querySelector('[role=status]').textContent.includes('download failed')")
    fail['image'] = False
    page.get_by_role('button',name='Retry',exact=True).click()
    page.wait_for_function("!document.querySelector('img').hidden")
    for row in ROWS: row['validUntil']='2000-01-01T00:00:00Z'
    page.evaluate("sfOpenPublished(document.getElementById('host'))")
    assert 'expired' in page.locator('[role=status]').inner_text()
    assert not page.locator('img').is_visible()
    browser.close()
print('PASS initial rendering, month/parameter selection, saved month, advanced entry, catalog failure, image retry, expiry')
