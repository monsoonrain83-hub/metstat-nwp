const assert=require('node:assert/strict');
const nav=require('../host/assets/metstat_geo_nav.js');
const B=[20,10,60,50];
const nodes=[
{id:'world',level:'world',bounds:[-180,-90,180,90]},
{id:'asia',level:'continent',parent:'world',bounds:[20,-10,180,80]},
{id:'europe',level:'continent',parent:'world',bounds:[-12,35,60,72]},
{id:'me',level:'region',parent:'asia',bounds:B},
{id:'east_asia',level:'region',parent:'asia',bounds:[90,0,150,60]},
{id:'iran',level:'country',parent:'me',bounds:[44,25,64,40]},
{id:'iraq',level:'country',parent:'me',bounds:[38,29,49,38]},
{id:'fars',level:'province',parent:'iran',bounds:[50,27,55,32]},
{id:'estahban',level:'county',parent:'fars',bounds:[53,28,55,30]},
];
const fa=nav.create(nodes,{locale:'fa'});assert.equal(fa.state().selected,'iran');
assert.equal(fa.zoomOut(),true);assert.equal(fa.state().selected,'me');
assert.equal(fa.zoomOut(),true);assert.equal(fa.state().selected,'asia');
assert.equal(fa.zoomOut(),true);assert.equal(fa.state().selected,'world');
assert.equal(fa.zoomIn('asia'),true);assert.equal(fa.zoomIn('me'),true);assert.equal(fa.zoomIn('iran'),true);
assert.equal(fa.zoomIn('fars'),true);assert.equal(fa.zoomIn('estahban'),true);
assert.equal(fa.zoomIn(),false);assert.deepEqual(fa.state().path,['world','asia','me','iran','fars','estahban']);
assert.deepEqual(fa.menu('country').map(n=>n.id),['iran','iraq']);
assert.deepEqual(fa.menu('region').map(n=>n.id),['me','east_asia']);
assert.equal(fa.hit(['iran']),false); // map hit must not jump backwards
assert.equal(fa.select('me'),true);assert.equal(fa.hit(['fars','iran']),true);assert.equal(fa.state().selected,'fars');
assert.equal(fa.select('me'),true);assert.equal(fa.hit(['iran','fars']),true);assert.equal(fa.state().selected,'fars'); // permutation cannot alter geographic drill-down
const en=nav.create(nodes,{locale:'en'});assert.equal(en.state().selected,'world');
const fav=nav.create(nodes,{locale:'en',favorite:'fars'});assert.equal(fav.state().selected,'fars');
assert.throws(()=>nav.create([...nodes,{id:'bad',level:'county',parent:'iraq',bounds:B}]),/only supported in Iran/);
assert.throws(()=>nav.create([...nodes,{id:'bad',level:'region',parent:'iran',bounds:B}]),/Invalid hierarchy/);
console.log('MetStat geographic navigation tests passed');
