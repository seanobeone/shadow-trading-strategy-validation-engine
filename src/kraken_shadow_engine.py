from __future__ import annotations
import json, os, tempfile, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent; STATE=ROOT/'kraken_shadow_state_v12_18_1.json'; LOG=ROOT/'kraken_shadow_trades_v12_18_1.jsonl'
PAIRS={'XXBTZUSD':'BTC/USD','XETHZUSD':'ETH/USD','SOLUSD':'SOL/USD','XXRPZUSD':'XRP/USD'}
def atomic(d):
    fd,tmp=tempfile.mkstemp(dir=str(ROOT),prefix='kraken_shadow_',suffix='.tmp',text=True)
    with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(d,f,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(tmp,STATE)
def fetch(pair):
    u='https://api.kraken.com/0/public/OHLC?'+urllib.parse.urlencode({'pair':pair,'interval':5})
    req=urllib.request.Request(u,headers={'User-Agent':'CoinbaseBot-v12.18.1-shadow'})
    with urllib.request.urlopen(req,timeout=10) as r:d=json.loads(r.read().decode())
    if d.get('error'):raise RuntimeError(';'.join(d['error']))
    k=next(k for k in d['result'] if k!='last'); return d['result'][k][-120:]
def ema(v,n):
    k=2/(n+1);e=v[0]
    for x in v[1:]:e=x*k+e*(1-k)
    return e
def analyze(rows):
    c=[float(x[4]) for x in rows]; v=[float(x[6]) for x in rows]; e9,e21,e50=ema(c[-60:],9),ema(c[-60:],21),ema(c[-60:],50); ret=(c[-1]/c[-4]-1)*100; base=sum(v[-21:-1])/20 if len(v)>=21 else 0; vr=v[-1]/base if base else 0
    bull=sum([e9>e21,e21>e50,ret>0,vr>=.75]); bear=sum([e9<e21,e21<e50,ret<0,vr>=.75]); side='LONG' if bull>=3 and bull>bear else 'SHORT' if bear>=3 and bear>bull else 'FLAT'
    return {'side':side,'score':bull-bear,'price':c[-1],'return_15m_pct':round(ret,3),'volume_ratio':round(vr,2)}
def cycle():
    signals={};errors=[]
    for p,label in PAIRS.items():
        try:signals[label]=analyze(fetch(p))
        except Exception as e:errors.append(f'{label}: {type(e).__name__}: {e}')
    d={'timestamp':datetime.now(timezone.utc).isoformat(),'mode':'SHADOW','live_authority':False,'strategy':'KRAKEN_UNIFIED','signals':signals,'errors':errors,'heartbeat_epoch':time.time()};atomic(d);return d
if __name__=='__main__':
    while True:
        try:cycle()
        except Exception as e:atomic({'timestamp':datetime.now(timezone.utc).isoformat(),'mode':'SHADOW','live_authority':False,'fatal_error':str(e),'heartbeat_epoch':time.time()})
        time.sleep(60)
