async function mapLimit(items,limit,mapper){
 if(!Number.isInteger(limit)||limit<1)throw new RangeError('limit');
 if(typeof mapper!=='function')throw new TypeError('mapper');
 const result=new Array(items.length);let next=0,failed=false;
 async function worker(){while(!failed){const i=next++;if(i>=items.length)return;try{result[i]=await mapper(items[i],i);}catch(e){failed=true;throw e;}}}
 await Promise.all(Array.from({length:Math.min(limit,items.length)},()=>worker()));return result;
}
module.exports={mapLimit};
