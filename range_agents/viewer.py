"""Offline causal visual review. Future hidden in the UI, not encrypted in HTML.
Never include the final holdout in this file before deliberate opening.
"""
import json
from pathlib import Path
from .config import TF_MS
from .report import page

def export_viewer(dataset,result,out,start_ms,end_ms):
 panels=[]
 for (symbol,tf),bars in dataset.structures.items():
  sub=bars[(bars.timestamp_ms+TF_MS[tf]>=start_ms)&(bars.timestamp_ms+TF_MS[tf]<=end_ms)]
  panels.append({'label':symbol+' '+tf,'symbol':symbol,'tf':tf,'duration':TF_MS[tf],
   'bars':sub[['timestamp_ms','open','high','low','close']].values.tolist(),
   'ranges':[r for r in result.get('ranges',[]) if r.get('symbol')==symbol and r.get('tf')==tf and r['known_ms']<end_ms],
   'signals':[s for s in result.get('signals',[]) if s['symbol']==symbol and s['tf']==tf and s['timestamp_ms']<end_ms]})
 payload=json.dumps(panels,allow_nan=False).replace('</','<\\/')
 body='''<div class="warning">Lecture causale : seules les bougies déjà closes au curseur sont dessinées. La zone finale réservée n’est pas incluse. Masquage visuel, pas chiffrement des données. Aucun ordre réel.</div><p><select id="panel"></select> <button id="back">Reculer</button> <button id="next">Avancer une bougie</button></p><input id="cursor" type="range" min="1" value="1" style="width:100%"><p id="when"></p><canvas id="chart" width="1160" height="380"></canvas><h2>Décisions connues à cet instant</h2><pre id="signals"></pre><h2>Annotation personnelle (sans résultat futur)</h2><textarea id="note" style="width:100%;height:90px" placeholder="Les bornes correspondent-elles à un range majeur ?"></textarea><p><button id="save">Exporter mon annotation JSON</button></p>'''
 js='''<script>
 const panels=PAYLOAD; const $=id=>document.getElementById(id);
 panels.forEach((p,i)=>{let o=document.createElement('option');o.value=i;o.textContent=p.label;$('panel').appendChild(o)});
 const fmt=t=>new Date(t).toISOString();
 function reset(){let p=panels[+$('panel').value];$('cursor').max=Math.max(1,p.bars.length);$('cursor').value=Math.min(20,p.bars.length);draw()}
 function draw(){const p=panels[+$('panel').value];if(!p)return;let k=+$('cursor').value;
 const bars=p.bars.slice(Math.max(0,k-150),k);const ctx=$('chart').getContext('2d');ctx.clearRect(0,0,1160,380);if(!bars.length){$('when').textContent='Pas de bougie';return;}
 const cutoff=bars[bars.length-1][0]+p.duration;const rr=p.ranges.filter(r=>r.known_ms<=cutoff&&r.expiry_ms>cutoff).slice(-1);
 let lo=Math.min(...bars.map(b=>b[3]),...rr.map(r=>r.lower));let hi=Math.max(...bars.map(b=>b[2]),...rr.map(r=>r.upper));const pad=(hi-lo)*.12||1;lo-=pad;hi+=pad;
 const y=v=>350-(v-lo)/(hi-lo)*320;const step=1040/bars.length;
 ctx.font='13px system-ui';ctx.fillStyle='#263445';ctx.fillText(hi.toFixed(3),1060,25);ctx.fillText(lo.toFixed(3),1060,350);
 bars.forEach((b,i)=>{let x=12+i*step;ctx.strokeStyle=b[4]>=b[1]?'#287e68':'#a54547';ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();ctx.moveTo(x,y(b[2]));ctx.lineTo(x,y(b[3]));ctx.stroke();ctx.fillRect(x-Math.max(1,step*.25),Math.min(y(b[1]),y(b[4])),Math.max(2,step*.5),Math.max(1,Math.abs(y(b[1])-y(b[4]))))});
 rr.forEach(r=>{ctx.strokeStyle='#ba7a00';[r.lower,r.upper].forEach(v=>{ctx.beginPath();ctx.moveTo(0,y(v));ctx.lineTo(1050,y(v));ctx.stroke();ctx.fillText(v.toFixed(3),1060,y(v))})});
 $('when').textContent='Informations disponibles jusqu’au '+fmt(cutoff)+' · '+k+'/'+p.bars.length+' bougies';
 const ss=p.signals.filter(s=>s.timestamp_ms<=cutoff).slice(-10).map(s=>({heure:fmt(s.timestamp_ms),agent:s.agent,sens:s.side===1?'LONG':'SHORT',niveau:s.threshold}));$('signals').textContent=JSON.stringify(ss,null,2);
 }
 $('panel').onchange=reset;$('cursor').oninput=draw;$('next').onclick=()=>{$('cursor').value=Math.min(+$('cursor').max,+$('cursor').value+1);draw()};$('back').onclick=()=>{$('cursor').value=Math.max(1,+$('cursor').value-1);draw()};
 $('save').onclick=()=>{const p=panels[+$('panel').value],b=p.bars[+$('cursor').value-1];if(!b)return;const data={symbol:p.symbol,timeframe:p.tf,available_ms:b[0]+p.duration,note:$('note').value};let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.download='annotation_range.json';a.click();URL.revokeObjectURL(a.href)};reset();
 </script>'''.replace('PAYLOAD',payload)
 p=Path(out);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(page('Replay visuel — futur masqué',body+js),encoding='utf-8')
