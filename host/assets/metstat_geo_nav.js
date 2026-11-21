/* MetStat geographic navigation state engine (no DOM side effects).
 * Geographic data and valid bounds MUST be supplied by the site; this module
 * never guesses counties, borders, or map coverage. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.MetStatGeoNav=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
'use strict';
const LEVELS=['world','continent','region','country','province','county'];
function node(index,id){return index[id]||null;}
function chain(index,id){const seen=new Set(),out=[];while(id){if(seen.has(id))throw Error('Geographic hierarchy cycle');seen.add(id);const n=node(index,id);if(!n)throw Error('Unknown geographic node: '+id);out.unshift(n);id=n.parent||null;}return out;}
function validBounds(b){return Array.isArray(b)&&b.length===4&&b.every(Number.isFinite)&&b[0]<b[2]&&b[1]<b[3]&&b[0]>=-180&&b[2]<=180&&b[1]>=-90&&b[3]<=90;}
function create(nodes,opts={}){
 const index=Object.create(null);for(const n of nodes){if(!n||!n.id||!LEVELS.includes(n.level)||index[n.id])throw Error('Invalid/duplicate geographic node');index[n.id]=n;}
 for(const n of nodes){if(!validBounds(n.bounds))throw Error('Invalid bounds: '+n.id);const ancestors=chain(index,n.id);if((n.level==='province'||n.level==='county')&&!ancestors.some(x=>x.level==='country'&&x.id==='iran'))throw Error('Province/county only supported in Iran');if(ancestors.length>1){const p=ancestors[ancestors.length-2];if(LEVELS.indexOf(n.level)!==LEVELS.indexOf(p.level)+1)throw Error('Invalid hierarchy: '+n.id);}}
 const initial=opts.favorite&&index[opts.favorite]?opts.favorite:(opts.locale==='fa'&&index.iran?'iran':(index.world?'world':nodes[0]?.id));let selected=initial;
 function select(id){if(!index[id])return false;selected=id;return true;}
 function ancestors(){return chain(index,selected);}
 function children(id=selected){return nodes.filter(n=>n.parent===id);}
 function zoomOut(){const p=node(index,selected)?.parent;if(!p)return false;selected=p;return true;}
 function zoomIn(id){const options=children();const target=id?options.find(n=>n.id===id):options.length===1?options[0]:null;if(!target)return false;selected=target.id;return true;}
 function menu(level){const i=LEVELS.indexOf(level);if(i<0)throw Error('Unknown level');const path=ancestors();if(level==='continent')return nodes.filter(n=>n.level==='continent');if(level==='world')return nodes.filter(n=>n.level==='world');const parent=path.find(n=>LEVELS.indexOf(n.level)===i-1);return parent?children(parent.id):[];}
 function state(){return {selected,level:index[selected]?.level||null,path:ancestors().map(n=>n.id),bounds:index[selected]?.bounds||null};}
 function hit(ids){for(let i=ids.length-1;i>=0;i--)if(index[ids[i]]&&chain(index,ids[i]).some(n=>n.id===selected)){return select(ids[i]);}return false;}
 return {select,zoomOut,zoomIn,menu,children,state,hit,levels:LEVELS.slice()};
}
return {create,LEVELS};
});
