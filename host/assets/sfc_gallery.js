/* Public forecasts are rendered by the publication job. Custom tools load explicitly. */
async function sfOpenPublished(host) {
  const language = LANG === 'fa' ? 'fa' : 'en';
  const translate = (fa, en) => language === 'fa' ? fa : en;
  const element = (tag, text = '') => Object.assign(document.createElement(tag), {textContent: text});
  const panel = element('section');
  panel.className = 'sfPublished';
  panel.dataset.sfcPublished = '1';
  const title = element('h2', translate('پیش‌بینی ماهانه و فصلی', 'Monthly and seasonal forecast'));
  const dates = element('p');
  const controls = element('div');
  controls.className = 'sfCtl';
  const status = element('p', translate('دریافت فهرست نقشه‌ها…', 'Loading forecast catalog…'));
  status.setAttribute('role', 'status');
  const image = element('img');
  image.style.width = '100%';
  image.hidden = true;
  const save = element('a', translate('ذخیره PNG', 'Save PNG'));
  save.className = 'btn';
  save.hidden = true;
  const retry = element('button', translate('تلاش دوباره', 'Retry'));
  retry.type = 'button';
  retry.className = 'btn';
  retry.hidden = true;
  const advanced = element('button', translate('سناریوی سفارشی، استان‌ها و ابزارهای نقشه', 'Custom scenarios, provinces and map tools'));
  advanced.type = 'button';
  advanced.className = 'btn';
  advanced.onclick = () => openSF(true);
  const grid = element('div');
  grid.className = 'sfGrid';
  const sidebar = element('div');
  sidebar.className = 'sfSide';
  const settings = element('section');
  settings.className = 'card sfSet';
  settings.append(controls, advanced);
  sidebar.append(settings);
  const body = element('div');
  body.className = 'sfBody';
  const mapCard = element('section');
  mapCard.className = 'card wide';
  mapCard.append(status, image, save, retry);
  body.append(mapCard);
  grid.append(sidebar, body);
  panel.append(title, dates, grid);
  host.replaceChildren(panel);
  const active = () => host.contains(panel) && LANG === language;
  async function readJSON(url) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 25000);
    try {
      const response = await fetch(url, {cache: 'no-cache', signal: controller.signal});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return await response.json();
    } finally { clearTimeout(timer); }
  }
  let catalog;
  try {
    catalog = await readJSON('online/data/sfc/gallery_latest.json');
    const products = catalog.products?.[language];
    if (catalog.version !== 1 || !Number.isFinite(Date.parse(catalog.issued)) ||
        !Array.isArray(catalog.run) || catalog.run.length !== 2 ||
        !['prcp', 'tmean'].every(par => Array.isArray(products?.[par]) && products[par].length > 0 &&
          products[par].every(row => typeof row.label === 'string' && Number.isFinite(Date.parse(row.validUntil)) && row.maps))) {
      throw new Error('Invalid forecast catalog');
    }
  } catch (error) {
    if (!active()) return;
    status.textContent = translate('نقشهٔ آماده فعلاً در دسترس نیست. دوباره تلاش کنید.', 'Published maps are currently unavailable. Please retry.');
    retry.hidden = false;
    retry.onclick = () => sfOpenPublished(host);
    return;
  }
  if (!active()) return;
  const products = Object.fromEntries(Object.entries(catalog.products[language]).map(([par, rows]) =>
    [par, rows.filter(row => Date.parse(row.validUntil) > Date.now())]));
  if (!products.prcp.length || !products.tmean.length) {
    status.textContent = translate('اعتبار زمانی نقشه‌ها پایان یافته؛ در انتظار انتشار پیش‌بینی تازه.', 'These maps have expired. Awaiting the next forecast.');
    retry.hidden = false;
    retry.onclick = () => sfOpenPublished(host);
    return;
  }
  dates.textContent = translate('تاریخ ورودی‌ها', 'Input issue date') + ' ' + catalog.issued.slice(0, 10) +
    ' · SEAS ' + catalog.run.join('/');
  function select(label, options) {
    const wrapper = element('label', label + ' ');
    const input = element('select');
    for (const [value, text] of options) input.add(new Option(text, value));
    wrapper.append(input);
    controls.append(wrapper);
    return input;
  }
  const parameter = select(translate('پارامتر', 'Parameter'), [['prcp', translate('بارش', 'Precipitation')], ['tmean', translate('دمای میانگین', 'Mean temperature')]]);
  parameter.value = SF.o.par === 'tmean' ? 'tmean' : 'prcp';
  const month = select(translate('ماه', 'Month'), []);
  const kind = select(translate('نقشه', 'Map'), [['c', translate('کنترل', 'Control')], ['mean', translate('میانگین', 'Mean')],
    ['skill', translate('مهارت', 'Skill')], ...Array.from({length: 10}, (_, index) => ['m' + (index + 1), translate('عضو', 'Member') + ' ' + (index + 1)])]);
  let requestToken = 0;
  const cache = new Map();
  async function draw() {
    const token = ++requestToken;
    image.hidden = save.hidden = true;
    retry.hidden = true;
    status.textContent = translate('دریافت نقشه…', 'Loading map…');
    const row = products[parameter.value][month.selectedIndex];
    const name = row.maps[kind.value];
    try {
      if (!/^g_[a-f0-9]{32}$/.test(name)) throw new Error('Invalid map reference');
      let png = cache.get(name);
      if (!png) {
        const data = await readJSON('online/data/sfc/' + name + '.json');
        if (!data.png?.startsWith('data:image/png;base64,iVBOR')) throw new Error('Invalid PNG');
        png = data.png;
        if (cache.size >= 4) cache.delete(cache.keys().next().value);
        cache.set(name, png);
      }
      const preview = new Image();
      preview.src = png;
      await preview.decode();
      if (token !== requestToken || !active()) return;
      image.src = save.href = png;
      image.alt = row.label + ' ' + kind.selectedOptions[0].text;
      save.download = 'MetStat_' + parameter.value + '_' + row.t + '_' + kind.value + '.png';
      image.hidden = save.hidden = false;
      status.textContent = '';
    } catch (error) {
      if (token !== requestToken || !active()) return;
      status.textContent = translate('دریافت نقشه ناموفق بود. دوباره تلاش کنید.', 'Map download failed. Please retry.');
      retry.hidden = false;
      retry.onclick = draw;
    }
  }
  function fillMonths() {
    SF.o.par = parameter.value;
    sfSave();
    const selected = month.value;
    month.replaceChildren(...products[parameter.value].map(row => new Option(row.label, String(row.t))));
    if (products[parameter.value].some(row => String(row.t) === selected)) month.value = selected;
    return draw();
  }
  parameter.onchange = fillMonths;
  month.onchange = kind.onchange = draw;
  await fillMonths();
}
