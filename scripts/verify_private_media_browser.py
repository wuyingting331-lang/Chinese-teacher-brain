"""Offline browser smoke test of the exact private media component JS; no API or secrets."""
from pathlib import Path
import base64
import json
import subprocess
import sys
import tempfile
import os
import shutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from teacher.private_media import JS


def main():
    browsers=[Path(path) for name in ('msedge','chromium','chromium-browser','google-chrome') if (path:=shutil.which(name))]
    for variable in ('PROGRAMFILES(X86)','PROGRAMFILES'):
        if os.environ.get(variable):
            browsers.extend([Path(os.environ[variable])/'Microsoft/Edge/Application/msedge.exe',
                             Path(os.environ[variable])/'Google/Chrome/Application/chrome.exe'])
    browser=next((p for p in browsers if p.exists()),None)
    if browser is None:
        raise SystemExit('No local Chromium browser found; browser smoke test not run.')
    import io
    from PIL import Image
    buffer=io.BytesIO(); Image.new('RGB',(64,64),'red').save(buffer,format='JPEG')
    picture=base64.b64encode(buffer.getvalue()).decode('ascii')
    text='匿名合成下载内容，仅用于浏览器测试。'
    encoded=base64.b64encode(text.encode()).decode()
    body='''<!doctype html><meta charset="utf-8"><div id="host"><button></button><img hidden></div><pre id="result">WAIT</pre>
<script type="module">
'''+JS.replace('export default function(','function render(')+'''
try {
  const host=document.querySelector('#host');
  let blob, filename;
  const create=URL.createObjectURL.bind(URL);
  URL.createObjectURL=(value)=>{blob=value;return create(value)};
  HTMLAnchorElement.prototype.click=function(){ filename=this.download; };
  const cleanup=render({parentElement:host,data:{kind:'download',label:'<b>literal label</b>',payload:ENCODED,filename:'synthetic.md',mime:'text/markdown',disabled:false}});
  host.querySelector('button').click();
  if ((await blob.text())!==TEXT || filename!=='synthetic.md') throw Error('payload');
  if (host.querySelector('button').innerHTML.includes('<b>')) throw Error('unsafe label');
  cleanup();
  render({parentElement:host,data:{kind:'image',label:'synthetic picture',payload:PICTURE}});
  const image=host.querySelector('img');
  await image.decode();
  if (image.naturalWidth!==64 || image.alt!=='synthetic picture') throw Error('image');
  document.querySelector('#result').textContent='PASS';
} catch(error) { document.querySelector('#result').textContent='FAIL: '+error.name; }
</script>'''
    body=body.replace('ENCODED',json.dumps(encoded)).replace('TEXT',json.dumps(text)).replace('PICTURE',json.dumps(picture))
    directory=Path(tempfile.mkdtemp(prefix='ctb-media-browser-'))
    page=directory/'test.html'; page.write_text(body,encoding='utf-8')
    result=subprocess.run([str(browser),'--headless=new','--disable-gpu','--no-first-run',
        '--disable-background-networking','--disable-component-update','--disable-sync','--disable-extensions',
        '--user-data-dir='+str(directory/'profile'),'--dump-dom','--virtual-time-budget=2500',page.as_uri()],
        capture_output=True,timeout=40)
    passed=b'id="result">PASS</pre>' in result.stdout
    print(json.dumps(dict(browser_component_smoke_passed=passed,exit_code=result.returncode)))
    if not passed: raise SystemExit(1)


if __name__=='__main__': main()
