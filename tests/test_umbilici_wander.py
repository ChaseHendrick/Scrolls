"""Generated display-default controls; no network, real coordinates or CT."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(os.environ.get('UMBILICI_ROOT', Path(__file__).resolve().parents[1]))
APP = ROOT / 'spaces/umbilici/app.js'
NODE = os.environ.get('NODE') or shutil.which('node')
JS = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(process.argv[1],'utf8'),which=process.argv[2];
function fn(name){const at=src.indexOf('function '+name+'(');assert(at>=0,name);const end=src.indexOf('\n}',at);assert(end>=0);return src.slice(at,end+2);}
function match(re){const m=src.match(re);assert(m,String(re));return m[0];}
const nodes={};const frames=[];const timers=new Map();let timerId=0;
const ctx=vm.createContext({assert,URLSearchParams,nodes,frames,timers,draws:0,applied:0,lastURL:null,
 $:id=>nodes[id]??=( {value:'',textContent:'',addEventListener(type,cb){this[type]=cb;}} ),
 requestAnimationFrame:cb=>frames.push(cb),buildArray:()=>{ctx.draws++},applySettings:()=>{ctx.applied++},
 setTimeout:cb=>{timers.set(++timerId,cb);return timerId},clearTimeout:id=>timers.delete(id),
 history:{replaceState:(_a,_b,u)=>{ctx.lastURL=u}},location:{pathname:'/'}});
vm.runInContext(match(/const DEFAULT_EX = [^;]+;/)+'\n'+match(/const S = \{[\s\S]*?\n\};/)+
 '\nconst OFF={src:new Set(),line:new Set()}; let exQueued=false; let urlT=0;'+
 match(/const SET_DEFAULT = [^;]+;/)+'\nconst SET={...SET_DEFAULT};\n'+fn('setEx')+'\n'+fn('syncURLSoon')+'\n'+fn('syncURL')+'\n'+
 match(/\$\('ex'\)\.addEventListener\('input',[^\n]+/)+ '\n'+match(/\$\('s-reset'\)\.addEventListener\('click',[^\n]+/),ctx);
const run=code=>vm.runInContext(code,ctx);
function flush(){while(frames.length)frames.shift()();for(const [id,cb]of [...timers]){timers.delete(id);cb();}}
const cases={
 fresh(){assert.equal(run('S.ex'),2);assert.equal(run('DEFAULT_EX'),2);},
 reset(){run("setEx(9); SET.glow=1; S.data={points:[1,2,3],grade:'FLAG'}");flush();ctx.draws=0;nodes['s-reset'].click();flush();assert.equal(run('S.ex'),2);assert.equal(Number(nodes.ex.value),2);assert.equal(Number(nodes['ex-v'].textContent),2);assert.equal(ctx.lastURL,'/');assert.equal(ctx.draws,1);assert.equal(ctx.applied,1);assert.equal(run('SET.glow'),0.25);assert.equal(run('JSON.stringify(S.data)'),'{"points":[1,2,3],"grade":"FLAG"}');},
 url(){run('S.ex=2;syncURL()');assert.equal(ctx.lastURL,'/');for(const v of [3,7,20]){ctx.q=new URLSearchParams('ex='+v);run(match(/if \(q\.get\('ex'\)\) \{[^\n]+/));assert.equal(run('S.ex'),v);assert.equal(Number(nodes.ex.value),v);run('syncURL()');assert.equal(ctx.lastURL,'?ex='+v);} },
 input(){run("S.data={points:[1,2,3],grade:'FLAG'}");nodes.ex.input({target:{value:'7'}});nodes.ex.input({target:{value:'8'}});assert.equal(frames.length,1);flush();assert.equal(run('S.ex'),8);assert.equal(Number(nodes.ex.value),8);assert.equal(Number(nodes['ex-v'].textContent),8);assert.equal(ctx.draws,1);assert.equal(ctx.lastURL,'?ex=8');assert.equal(run('JSON.stringify(S.data)'),'{"points":[1,2,3],"grade":"FLAG"}');}
};assert(cases[which]);cases[which]();console.log('PASS '+which);
'''

@unittest.skipUnless(NODE, 'Node is required; frozen runner forbids skips')
class Wander(unittest.TestCase):
    def run_case(self, name, path=APP):
        return subprocess.run([NODE, '-e', JS, str(path), name], text=True, capture_output=True, timeout=15)
    def check(self, name):
        r=self.run_case(name);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
    def test_fresh_state_and_native_control_default(self):
        self.check('fresh')
        html=(ROOT/'spaces/umbilici/index.html').read_text()
        self.assertIn('<b id="ex-v">2</b>',html)
        self.assertRegex(html,r'id="ex"[^>]*value="2"')
    def test_reset_restores_display_settings_and_canonical_url(self): self.check('reset')
    def test_explicit_urls_survive_and_default_is_omitted(self): self.check('url')
    def test_slider_redraw_coalesces_without_data_or_grade_mutation(self): self.check('input')
    def test_docs_and_recent_wording_cleanup_preserved(self):
        readme=(ROOT/'spaces/umbilici/README.md').read_text();doc=(ROOT/'docs/tools/umbilici.md').read_text()
        self.assertIn('(default 2x)',readme);self.assertIn('Reset returns it to 2x',readme)
        self.assertIn('| `ex` | `2` |',doc);self.assertIn('Published coordinates are unchanged',doc)
        for path in ['spaces/umbilici/app.js','spaces/umbilici/index.html','spaces/umbilici/README.md']:
            self.assertNotIn('model output, not checked by eye',(ROOT/path).read_text())
    def test_controls_reject_old_default_and_disconnected_reset(self):
        src=APP.read_text()
        mutants=[('fresh',src.replace('const DEFAULT_EX = 2;','const DEFAULT_EX = 3;')),
                 ('reset',src.replace('Object.assign(SET, SET_DEFAULT); setEx(DEFAULT_EX); applySettings();','Object.assign(SET, SET_DEFAULT); applySettings();'))]
        for case,text in mutants:
            self.assertNotEqual(src,text)
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'mutant.js';p.write_text(text);self.assertNotEqual(self.run_case(case,p).returncode,0)

if __name__ == '__main__': unittest.main(verbosity=2)
