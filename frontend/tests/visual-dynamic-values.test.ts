import test from "node:test";
import assert from "node:assert/strict";
import {pairedStorageMasks,type StorageMask} from "../scripts/visual-dynamic-values.mjs";
test("storage masks cover only paired dynamic values and never swallow a layout shift",()=>{
  const a:StorageMask={key:"storage-number:1:0",x:100.2,y:200,width:50.1,height:16,reason:"Live size"};
  const paired=pairedStorageMasks([a],[{...a,x:90,width:60.3}]);
  assert.deepEqual(paired.masks,[{...a,x:90,y:200,width:61,height:16}]);
  assert.deepEqual(pairedStorageMasks([a],[{...a,y:220}]),{masks:[],skipped:[a.key]});
  assert.deepEqual(pairedStorageMasks([a],[]),{masks:[],skipped:[a.key]});
});
