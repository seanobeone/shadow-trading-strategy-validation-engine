from __future__ import annotations
import json, math, os, tempfile, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent
STATE=ROOT/'futures_shadow_state_v12_18_1.json'; LOG=ROOT/'futures_shadow_trades_v12_18_1.jsonl'
PRODUCTS={'BTC-USD':0.01,'ETH-USD':0.10,'SOL-USD':5.0,'XRP-USD':500.0}

def atomic(path,data):
    fd,tmp=tempfile.mkstemp(dir=str(ROOT),prefix=path.stem,suffix='.tmp',text=True)
    with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(data,f,indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)
def get_json(url,timeout=10):
    req=urllib.request.Request(url,headers={'User-Agent':'CoinbaseBot-v12.18.1-shadow'})
    with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode())
def candles(product,limit=120):
    end=int(time.time()); start=end-limit*300
    q=urllib.parse.urlencode({'start':start,'end':end,'granularity':'FIVE_MINUTE','limit':limit})
    u=f'https://api.coinbase.com/api/v3/brokerage/market/products/{product}/candles?{q}'
    d=get_json(u); rows=d.get('candles',[])
    out=[]
    for x in rows:
        try: out.append((int(x['start']),float(x['open']),float(x['high']),float(x['low']),float(x['close']),float(x['volume'])))
        except Exception: pass
    return sorted(out)
def ema(vals,n):
    if not vals:return 0.0
    k=2/(n+1); e=vals[0]
    for v in vals[1:]:e=v*k+e*(1-k)
    return e
def rsi(vals,n=14):
    if len(vals)<n+1:return 50.0
    ds=[vals[i]-vals[i-1] for i in range(1,len(vals))][-n:]; g=sum(max(x,0) for x in ds)/n; l=sum(max(-x,0) for x in ds)/n
    return 100.0 if l==0 else 100-(100/(1+g/l))
def signal(rows):
    closes=[r[4] for r in rows]; vols=[r[5] for r in rows]
    if len(closes)<55:return {'side':'FLAT','score':0,'reason':'insufficient candles'}
    e9,e21,e50=ema(closes[-60:],9),ema(closes[-60:],21),ema(closes[-60:],50); rr=rsi(closes); ret=(closes[-1]/closes[-4]-1)*100
    base=sum(vols[-21:-1])/20 if len(vols)>=21 else 0; vr=vols[-1]/base if base else 0
    long=sum([e9>e21,e21>e50,rr>=52,rr<=70,ret>0,vr>=0.75]); short=sum([e9<e21,e21<e50,rr<=48,rr>=30,ret<0,vr>=0.75])
    if long>=5 and long>short:side='LONG'; score=long
    elif short>=5 and short>long:side='SHORT'; score=-short
    else:side='FLAT'; score=long-short
    return {'side':side,'score':score,'price':closes[-1],'rsi':round(rr,2),'ema9':e9,'ema21':e21,'ema50':e50,'return_15m_pct':round(ret,3),'volume_ratio':round(vr,2)}
def load_cfg():
    try:return json.loads((ROOT.parent/'config'/'shadow_config.example.json').read_text(encoding='utf-8')).get('futures',{})
    except Exception:return {}
def load_state():
    try:return json.loads(STATE.read_text(encoding='utf-8'))
    except Exception:return {'positions':{},'closed':[],'realized_pnl':0.0,'fees':0.0,'cycles':0}
def append_event(x):
    with LOG.open('a',encoding='utf-8') as f:f.write(json.dumps(x,separators=(',',':'))+'\n')
def cycle():
    cfg=load_cfg(); s=load_state(); s.setdefault('positions',{}); s.setdefault('closed',[]); signals={}; errors=[]
    maxpos=int(cfg.get('max_open_positions',2) or 2); risk=float(cfg.get('risk_per_trade_pct',1) or 1)/100; capital=float(cfg.get('shadow_capital_usd',10000) or 10000)
    stop_pct=float(cfg.get('shadow_stop_pct',2.0) or 2.0)/100; take_pct=float(cfg.get('shadow_take_profit_pct',3.0) or 3.0)/100
    for product,contract_size in PRODUCTS.items():
        try:
            rows=candles(product); sg=signal(rows); signals[product]=sg; px=float(sg.get('price',0) or 0); pos=s['positions'].get(product)
            if pos and px:
                direction=1 if pos['side']=='LONG' else -1; pnl=(px-pos['entry'])*direction*pos['contract_size']*pos['contracts']; pnlpct=(px/pos['entry']-1)*direction
                pos.update({'mark':px,'unrealized_pnl':round(pnl,4),'pnl_pct':round(pnlpct*100,3),'updated':datetime.now(timezone.utc).isoformat()})
                exit_reason=None
                if pnlpct<=-stop_pct:exit_reason='STOP'
                elif pnlpct>=take_pct:exit_reason='TAKE_PROFIT'
                elif sg['side']!='FLAT' and sg['side']!=pos['side']:exit_reason='SIGNAL_FLIP'
                if exit_reason:
                    rec={**pos,'exit':px,'realized_pnl':round(pnl,4),'exit_reason':exit_reason,'closed':datetime.now(timezone.utc).isoformat()}; s['closed'].append(rec); s['closed']=s['closed'][-500:]; s['realized_pnl']=round(float(s.get('realized_pnl',0))+pnl,4); del s['positions'][product]; append_event({'event':'CLOSE',**rec}); pos=None
            if not pos and sg['side'] in ('LONG','SHORT') and len(s['positions'])<maxpos and px:
                risk_dollars=max(1.0,capital*risk); per_contract_risk=px*contract_size*stop_pct; contracts=max(1,min(int(cfg.get('max_contracts_per_trade',1) or 1),int(risk_dollars/per_contract_risk) if per_contract_risk else 1))
                p={'product':product,'side':sg['side'],'contracts':contracts,'contract_size':contract_size,'entry':px,'mark':px,'opened':datetime.now(timezone.utc).isoformat(),'unrealized_pnl':0.0,'score':sg['score']}; s['positions'][product]=p; append_event({'event':'OPEN',**p})
        except Exception as e:errors.append(f'{product}: {type(e).__name__}: {e}')
    s.update({'timestamp':datetime.now(timezone.utc).isoformat(),'mode':'SHADOW','live_authority':False,'signals':signals,'errors':errors[-20:],'cycles':int(s.get('cycles',0))+1,'heartbeat_epoch':time.time()})
    atomic(STATE,s); return s
if __name__=='__main__':
    while True:
        try:cycle()
        except Exception as e: atomic(STATE,{'timestamp':datetime.now(timezone.utc).isoformat(),'mode':'SHADOW','live_authority':False,'fatal_error':f'{type(e).__name__}: {e}','heartbeat_epoch':time.time()})
        time.sleep(60)
