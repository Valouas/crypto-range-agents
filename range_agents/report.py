"""Offline HTML, JSON/CSV logs. No public server or third-party CDN."""
from pathlib import Path
from html import escape
import csv,json
from .data import atomic_json

def table(rows,limit=200):
 if not rows: return '<p>Aucune observation.</p>'
 keys=list(dict.fromkeys(k for r in rows[:limit] for k in r))
 keys=[k for k in keys if not isinstance(rows[0].get(k),(dict,list))]
 body=''.join('<tr>'+''.join('<td>'+escape(str(r.get(k,'')))+'</td>' for k in keys)+'</tr>' for r in rows[:limit])
 return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+escape(k)+'</th>' for k in keys)+'</tr></thead><tbody>'+body+'</tbody></table></div>'

def page(title,body):
 return '''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>'''+escape(title)+'''</title><style>
 body{font:16px/1.55 system-ui,sans-serif;max-width:1220px;margin:40px auto;padding:0 28px;background:#f7f8fa;color:#18232e}h1{font-size:34px;line-height:1.2}h2{margin-top:38px}p{max-width:950px}.badge{display:inline-block;padding:7px 12px;border:1px solid #aaa;background:white;border-radius:6px;font-weight:600}.warning{padding:20px;background:#fff4df;border-left:5px solid #b27b17}.scroll{overflow:auto;background:white;border:1px solid #d8dde3;border-radius:7px}table{border-collapse:collapse;font-size:13px;white-space:nowrap;width:100%}td,th{padding:10px 12px;border-bottom:1px solid #e6e8eb;text-align:left}th{background:#e9eef4}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:20px}button,select{padding:9px;font:inherit}canvas{width:100%;height:360px;background:white;border:1px solid #bbb}.muted{color:#586577}a{color:#164b76}code{background:#e5e9ed;padding:2px 5px}
 </style><body><span class="badge">RANGE AGENTS 2.0 · SIMULATION</span><h1>'''+escape(title)+'</h1>'+body+'</body></html>'

def export_result(result,out,cfg,manifest,extras=None):
 out=Path(out); out.mkdir(parents=True,exist_ok=True)
 atomic_json(out/'result.json',{'config':cfg,'manifest':manifest,'result':result})
 for name in ('trades','signals','orders','ranges','lifecycle','equity','funding','incidents','open_positions'):
  rows=result.get(name,[]); atomic_json(out/(name+'.json'),rows)
  if rows:
   keys=list(dict.fromkeys(k for row in rows for k in row))
   with open(out/(name+'.csv'),'w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=keys); w.writeheader()
    for row in rows: w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})
 syn=manifest.get('synthetic',False)
 warning='DONNEES ARTIFICIELLES : aucune mesure de rentabilite de marche.' if syn else 'REPLAY EXPLORATOIRE : executions et couts modelises, non identiques a des ordres reels.'
 s=result['summary']; scalar=[{'mesure':k,'valeur':v} for k,v in s.items() if not isinstance(v,(dict,list))]
 body='<div class="warning">'+warning+'<br>Un seul capital partage. Aucun connecteur d’ordres reels. Les positions non fermees sont censurees, pas forcees gagnantes.</div>'
 body+='<h2>Compte commun</h2>'+table(scalar)+'<h2>Agents</h2>'+table([{'agent':k,**v} for k,v in s.get('agents',{}).items()])
 body+='<h2>Decisions et motifs de refus</h2>'+table(result.get('signals',[]))
 body+='<h2>Transactions fictives cloturees</h2>'+table(result.get('trades',[]))
 body+='<h2>Incidents et controles</h2>'+table(result.get('incidents',[]))
 body+='<p>Les tableaux affichent au plus 200 lignes. Les fichiers JSON et CSV contiennent les journaux complets.</p>'
 if extras:
  for k,v in extras.items(): atomic_json(out/(k+'.json'),v)
  body+='<h2>Diagnostics complementaires</h2><p>'+escape(', '.join(extras))+' : exports JSON dans le meme dossier. Les trajectoires futures sont des diagnostics, jamais des variables d’entree.</p>'
 (out/'rapport.html').write_text(page('Rapport du portefeuille',body),encoding='utf-8')

