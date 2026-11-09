"""Preview routing and failed/stale image controls; no scientific data or network."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

SPACE = Path(__file__).resolve().parents[1] / "spaces" / "lasagna-fields"


class TestPreviewCatalog(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "needs Node for catalog count labels")
    def test_counts_distinguish_scrolls_from_fragments(self):
        page = (SPACE / "guide" / "index.html").read_text()
        code = page[page.index("function fieldCountLabel("):page.index("const srcOf=")]
        harness = """
const assert=require('node:assert/strict'),fs=require('node:fs');
const sampleTypes=new Map(JSON.parse(fs.readFileSync(COVERAGE,'utf8')).samples.map(s=>[s.scroll,s.sample_type]));
const fields=JSON.parse(fs.readFileSync(FIELDS,'utf8')).fields;
""".replace("COVERAGE", json.dumps(str(SPACE / "coverage.json"))).replace(
            "FIELDS", json.dumps(str(SPACE / "fields.json")))
        checks = """
assert.equal(fieldCountLabel(fields),'56 fields · 35 scrolls · 4 fragments');
assert.equal(fieldCountLabel(fields.filter(f=>f.scroll==='PHerc0009B')),'3 fields · 1 fragment');
assert.equal(fieldCountLabel(fields.filter(f=>f.scroll==='PHerc0009B').slice(0,1)),'1 field · 1 fragment');
assert.equal(fieldCountLabel(fields.filter(f=>f.scroll==='PHerc0139')),'10 fields · 1 scroll');
assert.equal(fieldCountLabel([]),'0 fields');
assert.equal(fieldCountLabel([{scroll:'unknown'}]),'1 field · 1 other sample');
"""
        result = subprocess.run(["node", "-e", harness + code + checks],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_smoothed_urls_are_separate_from_originals(self):
        fields = json.loads((SPACE / "fields.json").read_text())["fields"]
        paired = [f for f in fields if f.get("preview_smoothed")]
        self.assertTrue(paired)
        for field in paired:
            self.assertNotEqual(field.get("preview_kind"), "cos")
            for view, smooth in field["preview_smoothed"].items():
                self.assertIn(view, ("xy", "xz"))
                self.assertTrue(smooth.startswith("https://"))
                self.assertNotEqual(smooth, field["preview_" + view])


@unittest.skipUnless(shutil.which("node"), "needs Node for browser JavaScript controls")
class TestPreviewLoading(unittest.TestCase):
    def test_catalog_thumbnail_uses_a_listed_url_or_published_preview(self):
        page = (SPACE / "guide" / "index.html").read_text()
        code = page[page.index("function thumbOf("):page.index("const srcOf=")]
        checks = r"""
const assert=require('node:assert/strict');
const f={scroll:'PHerc0139',volume:'20250728140407',preview_xy:'https://example.test/raw.png'};
assert.equal(thumbOf([f]).src,f.preview_xy); // no guessed assets/thumbs path
assert.equal(thumbOf([{...f,preview_thumb:'https://example.test/thumb.webp'}]).src,'https://example.test/thumb.webp');
assert.equal(thumbOf([{preview_xz:'https://example.test/side.png'}]).src,'https://example.test/side.png');
assert.equal(thumbOf([{}]).src,null);
"""
        result = subprocess.run(["node", "-e", code + checks],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def run_js(self, checks):
        page = (SPACE / "guide" / "index.html").read_text()
        code = page[page.index("const failedPreviews="):page.index("let pvMode=")]
        harness = r"""
const assert=require('node:assert/strict');
const location={href:'https://example.test/guide'};
const elements=new Map();
const $=id=>{if(!elements.has(id))elements.set(id,{
  hidden:false,disabled:false,attributes:{},
  setAttribute(k,v){this.attributes[k]=v},removeAttribute(k){delete this[k]}
});return elements.get(id)};
const requests=[];
class Image{set src(value){this.url=value;requests.push(this)}}
const field={preview_xy:'https://example.test/raw.png',preview_xz:'https://example.test/side.png',
 preview_smoothed:{xy:'https://example.test/smooth.png',xz:'https://example.test/side-smooth.png'}};
"""
        result = subprocess.run(["node", "-e", harness + code + checks],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_original_and_smoothed_load_different_images(self):
        self.run_js("""
for(const prefix of ['human','lb']){
 const id=prefix==='human'?'human-image':'lbimg';
 loadPreview(prefix,field,'xy','smoothed');
 assert.equal(requests.at(-1).url,field.preview_smoothed.xy);
 requests.at(-1).onload();assert.equal($(id).src,field.preview_smoothed.xy);
 loadPreview(prefix,field,'xy','original');assert.equal($(id).hidden,true);
 requests.at(-1).onload();assert.equal($(id).src,field.preview_xy);
 assert.equal($(prefix+'-original').attributes['aria-pressed'],'true');
}
""")

    def test_missing_identical_and_cos_only_smoothing_use_original(self):
        self.run_js("""
for(const f of [{...field,preview_smoothed:null},
 {...field,preview_smoothed:{xy:field.preview_xy+'#same-image'}},
 {...field,preview_smoothed:{xy:'not a URL'}}, {...field,preview_kind:'cos'}]){
 loadPreview('human',f,'xy','smoothed');
 assert.equal(requests.at(-1).url,field.preview_xy);
 assert.equal($('human-display').hidden,true);
 assert.match($('human-display-note').textContent,/Smoothing is not available/);
}
""")

    def test_failed_smoothing_falls_back_and_cannot_be_reselected(self):
        self.run_js("""
loadPreview('human',field,'xy','smoothed');requests.at(-1).onerror();
assert.equal(requests.at(-1).url,field.preview_xy);requests.at(-1).onload();
assert.equal($('human-image').src,field.preview_xy);
assert.equal($('human-original').attributes['aria-pressed'],'true');
assert.equal($('human-smoothed').disabled,true);
assert.match($('human-display-note').textContent,/could not load.*Original/);
loadPreview('lb',field,'xy','smoothed');assert.equal(requests.at(-1).url,field.preview_xy);
loadPreview('human',field,'xz','smoothed');
assert.equal(requests.at(-1).url,field.preview_smoothed.xz);
assert.equal($('human-smoothed').disabled,false);
""")

    def test_both_failures_clear_image_and_selected_mode(self):
        self.run_js("""
for(const prefix of ['human','lb']){
 failedPreviews.clear();loadPreview(prefix,field,'xy','smoothed');
 requests.at(-1).onerror();requests.at(-1).onerror();
 const image=$(prefix==='human'?'human-image':'lbimg');
 assert.equal(image.hidden,true);assert.equal(image.src,undefined);
 assert.equal($(prefix+'-display-note').textContent,'Preview unavailable.');
 for(const mode of ['original','smoothed'])assert.equal($(prefix+'-'+mode).attributes['aria-pressed'],'false');
}
""")

    def test_late_load_and_failure_cannot_replace_current_view(self):
        self.run_js("""
loadPreview('human',field,'xy','smoothed');const earlier=requests.at(-1);
loadPreview('human',field,'xz','original');requests.at(-1).onload();
earlier.onload();earlier.onerror();
assert.equal($('human-image').src,field.preview_xz);
assert.equal(failedPreviews.size,0);
loadPreview('lb',field,'xy','smoothed');const closed=requests.at(-1);
$('lbimg').previewRequest=null;closed.onload();
assert.equal($('lbimg').src,undefined);
""")


@unittest.skipUnless(shutil.which("node"), "needs Node for iframe geometry controls")
class TestPreviewViewport(unittest.TestCase):
    def run_js(self, checks):
        page = (SPACE / "guide" / "index.html").read_text()
        code = page[page.index("function onScreen()"):page.index("function toastOn()")]
        harness = r"""
const assert=require('node:assert/strict');
let rect={left:164,top:198,width:1112,height:1200};
const frame={offsetWidth:1112,offsetHeight:1200,clientWidth:1112,clientHeight:1200,
 clientLeft:0,clientTop:0,getBoundingClientRect:()=>rect};
const window={frameElement:frame,scrollX:0,scrollY:0};
const parent={innerWidth:1440,innerHeight:1050,visualViewport:null};
const panel={style:{}},overlay={style:{},querySelector:()=>panel};
const $=()=>overlay;
const getComputedStyle=()=>({paddingTop:'16px',paddingBottom:'16px'});
const near=(actual,expected)=>assert.ok(Math.abs(actual-expected)<1e-8,`${actual} != ${expected}`);
"""
        result = subprocess.run(["node", "-e", harness + code + checks],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gradio_header_reduces_available_height(self):
        self.run_js("""
assert.deepEqual(onScreen(),{left:0,top:0,w:1112,h:852});
assert.notEqual(onScreen().h,parent.innerHeight); // old full-window-height control
placeLb();assert.equal(overlay.style.height,'852px');
assert.equal(panel.style.maxHeight,'820px');
assert.equal(overlay.style.width,'1112px');assert.equal(overlay.style.right,'auto');
""")

    def test_scrolled_frame_uses_only_visible_intersection(self):
        self.run_js("""
rect.top=-300;parent.innerHeight=844;
assert.deepEqual(onScreen(),{left:0,top:300,w:1112,h:844});
rect.top=100;frame.clientHeight=frame.offsetHeight=rect.height=300;
assert.deepEqual(onScreen(),{left:0,top:0,w:1112,h:300});
""")

    def test_visual_viewport_offsets_and_dpr_are_css_coordinates(self):
        self.run_js("""
rect.left=10;rect.top=80;
parent.visualViewport={offsetLeft:30,offsetTop:120,width:300,height:500};
for(const dpr of [1,1.25,2,3]){
 parent.devicePixelRatio=window.devicePixelRatio=dpr;
 assert.deepEqual(onScreen(),{left:20,top:40,w:300,h:500});
}
window.scrollX=4;window.scrollY=12;
assert.deepEqual(onScreen(),{left:24,top:52,w:300,h:500});
placeLb();assert.equal(overlay.style.left,'24px');assert.equal(overlay.style.top,'52px');
""")

    def test_transformed_bordered_frame_maps_back_to_local_units(self):
        self.run_js("""
Object.assign(frame,{offsetWidth:404,clientWidth:400,clientLeft:2,
 offsetHeight:1004,clientHeight:1000,clientTop:2});
rect={left:-20,top:-100,width:808,height:1506};
parent.innerWidth=600;parent.innerHeight=600;
const view=onScreen();near(view.left,8);near(view.top,97/1.5);
near(view.w,300);near(view.h,400);
""")

    def test_empty_intersection_and_standalone(self):
        self.run_js("""
rect.top=2000;assert.equal(onScreen().h,0);
placeLb();assert.equal(overlay.style.height,'0px');assert.equal(panel.style.maxHeight,'0px');
rect.left=2000;assert.equal(onScreen().w,0);
window.frameElement=null;assert.equal(onScreen(),null);
""")


@unittest.skipUnless(shutil.which("node"), "needs Node for selected-field links and recipes")
class TestFieldLinksAndRecipes(unittest.TestCase):
    def run_js(self, checks):
        page = (SPACE / "guide" / "index.html").read_text()
        code = page[page.index("  const url = value =>"):page.index("  function shareURL()")]
        region = page[page.index("function regionBundle("):page.index("/* region picker */")]
        harness = r"""
const assert=require('node:assert/strict'),fs=require('node:fs');
const page=fs.readFileSync(PAGE,'utf8');
const D=JSON.parse(page.match(/<script id="data" type="application\/json">(.*?)<\/script>/s)[1]);
const fields=JSON.parse(fs.readFileSync(FIELDS,'utf8')).fields;
const bundle=fields.find(f=>f.scroll==='PHerc0175A');
const other=fields.find(f=>f.scroll==='PHerc0009B');
const open=fields.find(f=>f.normals_access.download.kind==='open_data_zarr');
const BUCKET='https://huggingface.co/buckets/SharpMeow/lasagna-fields/resolve/';
let cur=-1,recipeField=null,resets=0,copied=[];
function node(){return {hidden:false,open:false,textContent:'',children:[],dataset:{},attributes:{},
 setAttribute(k,v){this.attributes[k]=v},append(...v){this.children.push(...v)},
 replaceChildren(...v){this.children=v}}}
const elements=new Map(),el=id=>{if(!elements.has(id))elements.set(id,node());return elements.get(id)};
const $=id=>el(id.startsWith('human-')?id.slice(6):id);
const document={createElement:node};
const regionReset=()=>resets++;
const copy=async value=>{copied.push(value);return true};
const setTimeout=()=>{};
""".replace("PAGE", json.dumps(str(SPACE / "guide" / "index.html"))).replace(
            "FIELDS", json.dumps(str(SPACE / "fields.json")))
        result = subprocess.run(["node", "-e", harness + region + code + checks],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_catalog_links_preserve_exact_arrays_and_real_file_metadata(self):
        self.run_js("""
for(const f of fields){
 const rows=dataLinks(f),get=k=>rows.find(r=>r.key===k),a=f.normals_access,d=a.download;
 assert.deepEqual(rows.filter(r=>r.kind==='zarr').map(r=>r.key),['nx','ny','cos','grad_mag']);
 for(const k of ['nx','ny'])assert.equal(get(k).href,a.channels[k].array_url);
 for(const k of ['cos','grad_mag'])assert.equal(get(k).href,f.availability.arrays[k].url);
 assert.equal(get('manifest').href,a.manifest_url);
 if(d.kind==='hf_dataset_bundle'){
  assert.equal(get('source').href,`https://huggingface.co/datasets/${d.dataset_id}/tree/${d.revision}`);
  assert.equal(get('index').href,d.index_url);assert.equal(get('checksums').href,d.checksums_url);
  d.finalize_archives.forEach((archive,i)=>assert.equal(get('final-'+i).href,archive.url));
 }else{assert.equal(get('source').href,d.page_url);assert.equal(get('index'),undefined);assert.equal(get('final-0'),undefined)}
 assert.ok(rows.every(r=>r.href.startsWith('https://')&&!r.href.endsWith('.zip')));
}
""")

    def test_missing_or_unsafe_metadata_does_not_invent_downloads(self):
        self.run_js("""
assert.deepEqual(dataLinks(null),[]);assert.deepEqual(dataLinks({}),[]);
const f=structuredClone(other);f.normals_access.channels.nx.array_url='javascript:alert(1)';
f.normals_access.download={kind:'open_data_zarr',page_url:'data:text/html,bad'};
f.normals_access.manifest_url='javascript:bad';
const rows=dataLinks(f);assert.equal(rows.find(r=>r.key==='nx'),undefined);
assert.equal(rows.find(r=>r.key==='source'),undefined);assert.equal(rows.find(r=>r.key==='manifest'),undefined);
assert.equal(fieldRecipes(f).download,'');
const bad=structuredClone(other);bad.normals_access.download.finalize_archives[0].path='../escape.tar';
assert.equal(fieldRecipes(bad).download,'');
""")

    def test_recipes_follow_bundle_open_data_missing_and_alternate_acquisition(self):
        self.run_js("""
assert.ok(regionBundle(bundle)>=0);assert.equal(regionBundle(other),-1);assert.equal(regionBundle(open),-1);
assert.equal(regionBundle({...bundle,volume:other.volume}),-1);
assert.equal(regionBundle({...bundle,stream:other.stream}),-1);
assert.equal(regionBundle({...bundle,normals_access:other.normals_access}),-1);
for(const f of [bundle,open,other,null,{...bundle,volume:other.volume}]){
 showRecipes(f);const recipe=fieldRecipes(f),d=f?.normals_access?.download;
 assert.equal(el('stream-code').textContent,recipe.python);assert.equal(el('bundle-code').textContent,recipe.download);
 assert.equal(el('stream-recipe').hidden,!recipe.python);assert.equal(el('bundle-recipe').hidden,!recipe.download);
 assert.equal(el('region-recipe').hidden,regionBundle(f)<0);
 if(recipe.download){assert.ok(recipe.download.includes(d.revision));assert.ok(recipe.download.includes(d.dataset_id));
  for(const a of d.finalize_archives)assert.ok(recipe.download.includes(a.path));}
 if(!f){assert.equal(recipe.python,'');assert.equal(recipe.download,'');assert.equal(recipeField,null)}
 if(f===open){assert.ok(!recipe.python.includes(bundle.dataset));assert.equal(recipe.download,'');assert.equal(el('rcode').textContent,'')}
}
""")

    def test_visible_copy_actions_follow_the_current_links(self):
        self.run_js("""
(async()=>{
 for(const f of [other,open,null]){
  showDataLinks(f);const rows=dataLinks(f),cards=[...el('data-arrays').children,...el('data-files').children];
  assert.equal(cards.length,rows.length);
  const quick=el('quick-links').children;
  assert.equal(quick.length,rows.filter(r=>r.kind==='zarr'||r.key==='source').length);
  for(const line of quick){const row=rows.find(r=>r.key===line.dataset.key);
   assert.equal(line.children[1].href,row.href);await line.children[2].onclick();assert.equal(copied.at(-1),row.href);
  }
  for(const card of cards){const row=rows.find(r=>r.key===card.dataset.key),actions=card.children[2];
   assert.equal(card.children[3].textContent,row.href);assert.equal(actions.children[0].href,row.href);
   assert.equal(actions.children[0].target,'_blank');assert.equal(actions.children[0].rel,'noopener');
   await actions.children[1].onclick();assert.equal(copied.at(-1),row.href);
  }
 }
})().catch(e=>{console.error(e);process.exitCode=1});
""")


if __name__ == "__main__":
    unittest.main()
