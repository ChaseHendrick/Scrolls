"""Preview routing and failed/stale image controls; no scientific data or network."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

SPACE = Path(__file__).resolve().parents[1] / "spaces" / "lasagna-fields"


class TestPreviewCatalog(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
