/* Browser adapter for MetStatGeoNav. Does not mutate the live site until
 * explicitly mounted by the current site bundle. No map library dependency. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.MetStatGeoToolbar=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
'use strict';
const LABELS={fa:['قاره','منطقه','کشور','استان','شهرستان'],en:['Continent','Region','Country','Province','County']};
const LEVELS=['continent','region','country','province','county'];
function mount({container,nav,locale='fa',onBounds,storage,storageKey='metstat.favorite.region',resolveMapClick,document:doc}){
 if(!container||!nav||typeof onBounds!=='function')throw Error('container, nav, onBounds required');
 doc=doc||container.ownerDocument;if(!doc)throw Error('Document unavailable');
 const lang=locale==='fa'?'fa':'en';const controls=[];const root=doc.createElement('div');root.className='metstat-geo-toolbar';root.setAttribute('role','group');root.setAttribute('aria-label',lang==='fa'?'محدوده نقشه':'Map extent');
 function change(id){if(!nav.select(id))return false;render();onBounds(nav.state().bounds,nav.state());return true;}
 for(let i=0;i<LEVELS.length;i++){
   const label=doc.createElement('label');label.className='metstat-geo-label';label.textContent=LABELS[lang][i];
   const select=doc.createElement('select');select.className='metstat-geo-select';select.setAttribute('aria-label',LABELS[lang][i]);
   select.addEventListener('change',()=>{if(select.value)change(select.value);});label.appendChild(select);root.appendChild(label);controls.push(select);
 }
 const fav=doc.createElement('button');fav.type='button';fav.className='metstat-geo-favorite';fav.setAttribute('aria-label',lang==='fa'?'ذخیره محدوده محبوب':'Save favorite extent');fav.textContent='☆';
 fav.addEventListener('click',()=>{if(!storage)return;try{storage.setItem(storageKey,nav.state().selected);render();}catch(_e){/* private browsing / quota */}});root.appendChild(fav);
 function favorite(){try{return storage?.getItem(storageKey)||null;}catch(_e){return null;}}
 function render(){const s=nav.state();LEVELS.forEach((level,i)=>{const select=controls[i];const items=nav.menu(level);select.replaceChildren();const all=doc.createElement('option');all.value='';all.textContent=lang==='fa'?'همه':'All';select.appendChild(all);for(const item of items){const o=doc.createElement('option');o.value=item.id;o.textContent=(lang==='fa'?item.fa:item.en)||item.name||item.id;select.appendChild(o);}const active=s.path.find(id=>items.some(item=>item.id===id));select.value=active||'';select.disabled=!items.length;});fav.textContent=favorite()===s.selected?'★':'☆';}
 function zoomOut(){if(!nav.zoomOut())return false;render();onBounds(nav.state().bounds,nav.state());return true;}
 function zoomIn(id){if(!nav.zoomIn(id))return false;render();onBounds(nav.state().bounds,nav.state());return true;}
 function mapClick(lon,lat){if(typeof resolveMapClick!=='function')return false;const hits=resolveMapClick(lon,lat,nav.state());if(!Array.isArray(hits)||!nav.hit(hits))return false;render();onBounds(nav.state().bounds,nav.state());return true;}
 container.appendChild(root);render();return {element:root,controls,change,zoomOut,zoomIn,mapClick,render,destroy(){root.remove();}};
}
function savedFavorite(storage,key='metstat.favorite.region'){try{return storage?.getItem(key)||null;}catch(_e){return null;}}
return {mount,savedFavorite};
});
