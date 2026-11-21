const assert=require('node:assert/strict');
const {create}=require('../host/assets/metstat_geo_nav.js');
const {mount,savedFavorite}=require('../host/assets/metstat_geo_toolbar.js');
class El{constructor(tag){this.tagName=tag;this.children=[];this.handlers={};this.attributes={};this.value='';this.disabled=false;this.ownerDocument=doc;}appendChild(x){this.children.push(x);return x;}setAttribute(k,v){this.attributes[k]=v;}addEventListener(k,f){this.handlers[k]=f;}replaceChildren(...x){this.children=x;}remove(){this.removed=true;}}
const doc={createElement(tag){return new El(tag);}};
const nodes=[{id:'world',level:'world',bounds:[-180,-90,180,90]},{id:'asia',parent:'world',level:'continent',bounds:[20,-10,180,80],fa:'آسیا'},{id:'me',parent:'asia',level:'region',bounds:[20,10,65,50]},{id:'iran',parent:'me',level:'country',bounds:[44,25,64,40]},{id:'fars',parent:'iran',level:'province',bounds:[50,27,55,32]},{id:'estahban',parent:'fars',level:'county',bounds:[53,28,55,30]}];
const store=new Map();const storage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)};
const nav=create(nodes,{locale:'fa'}),out=[];const container=new El('div');
const ui=mount({container,nav,locale:'fa',storage,onBounds:(bounds,state)=>out.push(state.selected),resolveMapClick:()=>['estahban','fars','iran'],document:doc});
assert.equal(ui.controls.length,5);assert.equal(ui.controls[3].disabled,false);assert.equal(ui.controls[4].disabled,true);
assert.equal(ui.zoomOut(),true);assert.equal(nav.state().selected,'me');assert.equal(ui.controls[3].disabled,true);
assert.equal(ui.mapClick(53,29),true);assert.equal(nav.state().selected,'estahban');
assert.equal(ui.change('fars'),true);assert.equal(ui.controls[4].disabled,false);
ui.element.children[5].handlers.click();assert.equal(savedFavorite(storage),'fars');
const reload=create(nodes,{locale:'en',favorite:savedFavorite(storage)});assert.equal(reload.state().selected,'fars');
assert.deepEqual(out,['me','estahban','fars']);ui.destroy();assert.equal(ui.element.removed,true);
console.log('MetStat geographic toolbar tests passed');
