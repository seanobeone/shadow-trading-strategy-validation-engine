#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import json, os, threading, time, uuid
from decimal import Decimal

ROOT=Path(__file__).resolve().parent
DIR=ROOT/'telemetry_v12_17_0'/'hypothetical'
PENDING=DIR/'pending.json'
COMPLETED=DIR/'completed.jsonl'
EVENTS=DIR/'events.jsonl'
LOCK=threading.Lock()
PROCESS_LOCK=DIR/'pending.lock'
LOCK_TIMEOUT_SEC=20.0
LOCK_STALE_SEC=120.0
CHECKPOINTS=[('15m',900),('30m',1800),('1h',3600),('4h',14400),('12h',43200),('24h',86400)]

def _d(v):
    try:return Decimal(str(v))
    except:return Decimal('0')
def _now(): return time.time()
def _iso(ts=None): return datetime.fromtimestamp(ts or _now(), timezone.utc).isoformat()
def _load():
    try:
        d=json.loads(PENDING.read_text(encoding='utf-8')); return d if isinstance(d,dict) else {}
    except:return {}
def _acquire_process_lock():
    DIR.mkdir(parents=True,exist_ok=True)
    deadline=time.time()+LOCK_TIMEOUT_SEC
    while True:
        try:
            fd=os.open(str(PROCESS_LOCK), os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            os.write(fd, f"pid={os.getpid()} ts={time.time()}\n".encode('utf-8'))
            os.close(fd)
            return
        except FileExistsError:
            try:
                if time.time()-PROCESS_LOCK.stat().st_mtime > LOCK_STALE_SEC:
                    PROCESS_LOCK.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.time() >= deadline:
                raise TimeoutError(f"hypothetical process lock timeout: {PROCESS_LOCK}")
            time.sleep(0.05)

def _release_process_lock():
    try: PROCESS_LOCK.unlink(missing_ok=True)
    except Exception: pass

class _ProcessLock:
    def __enter__(self): _acquire_process_lock(); return self
    def __exit__(self, exc_type, exc, tb): _release_process_lock()

def _save(d):
    DIR.mkdir(parents=True,exist_ok=True)
    tmp=DIR/f"pending.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    payload=json.dumps(d,indent=2)
    try:
        with tmp.open('w',encoding='utf-8') as f:
            f.write(payload); f.flush(); os.fsync(f.fileno())
        last=None
        for attempt in range(9):
            try:
                os.replace(tmp,PENDING); return
            except PermissionError as e:
                last=e; time.sleep(0.05*(attempt+1))
            except OSError as e:
                if getattr(e,'winerror',None) in (5,32,33):
                    last=e; time.sleep(0.05*(attempt+1))
                else: raise
        raise last or RuntimeError('pending.json replace failed')
    finally:
        try: tmp.unlink(missing_ok=True)
        except Exception: pass

def _event(row):
    DIR.mkdir(parents=True,exist_ok=True)
    with EVENTS.open('a',encoding='utf-8') as f:f.write(json.dumps(row,sort_keys=True)+'\n')

def register(bot_id, product_id, price, stage, reason, signal=None, estimated_fee_pct='1.8'):
    price=_d(price)
    if price<=0:return ''
    with LOCK, _ProcessLock():
        d=_load(); now=_now()
        for k,r in list(d.items()):
            if r.get('bot_id')==bot_id and r.get('product_id')==product_id and r.get('stage')==stage and now-float(r.get('registered_ts',0))<600:
                return k
        rid=str(uuid.uuid4())
        sig=signal or {}
        row={
            'id':rid,'bot_id':bot_id,'product_id':product_id,'entry_price':str(price),'stage':stage,'reason':reason,
            'registered_ts':now,'registered_at':_iso(now),'estimated_round_trip_fee_pct':str(estimated_fee_pct),
            'score':sig.get('score'),'predicted_move_pct':str(sig.get('predicted_move_pct','')),
            'move_confidence':sig.get('move_confidence'),'move_class':sig.get('move_class'),
            'mfe_pct':'0','mae_pct':'0','high_price':str(price),'low_price':str(price),'last_price':str(price),'checkpoints':{}
        }
        d[rid]=row; _save(d); _event({'type':'REGISTER',**row})
        return rid

def observe(bot_id, product_id, price):
    price=_d(price)
    if price<=0:return []
    msgs=[]; now=_now()
    with LOCK, _ProcessLock():
        d=_load(); changed=False; finished=[]
        for rid,r in list(d.items()):
            if r.get('bot_id')!=bot_id or r.get('product_id')!=product_id: continue
            entry=_d(r.get('entry_price'))
            high=max(_d(r.get('high_price')),price); low=min(_d(r.get('low_price')) or price,price)
            r['high_price']=str(high); r['low_price']=str(low); r['last_price']=str(price)
            r['mfe_pct']=str(((high-entry)/entry*100) if entry>0 else 0); r['mae_pct']=str(((low-entry)/entry*100) if entry>0 else 0)
            age=now-float(r.get('registered_ts',now)); cps=r.setdefault('checkpoints',{})
            for label,secs in CHECKPOINTS:
                if age>=secs and label not in cps:
                    gross=((price-entry)/entry*100) if entry>0 else Decimal('0')
                    fees=_d(r.get('estimated_round_trip_fee_pct'))
                    net=gross-fees
                    cps[label]={'ts':now,'at':_iso(now),'price':str(price),'gross_pct':str(gross),'estimated_net_pct':str(net),'mfe_pct':r['mfe_pct'],'mae_pct':r['mae_pct']}
                    msgs.append(f"HYPOTHETICAL SHADOW | {product_id} | {label} | gross {gross:+.2f}% | est net {net:+.2f}% | MFE {Decimal(r['mfe_pct']):+.2f}% | MAE {Decimal(r['mae_pct']):+.2f}% | NO ORDER AUTHORITY")
                    _event({'type':'CHECKPOINT','id':rid,'bot_id':bot_id,'product_id':product_id,'checkpoint':label,**cps[label]})
                    changed=True
            if '24h' in cps: finished.append(rid)
            changed=True
        for rid in finished:
            r=d.pop(rid); DIR.mkdir(parents=True,exist_ok=True)
            with COMPLETED.open('a',encoding='utf-8') as f:f.write(json.dumps(r,sort_keys=True)+'\n')
        if changed:_save(d)
    return msgs

def rows(limit=250):
    with LOCK, _ProcessLock():
        out=list(_load().values())
        try:
            for line in COMPLETED.read_text(encoding='utf-8').splitlines():
                try: out.append(json.loads(line))
                except: pass
        except: pass
    out.sort(key=lambda r:float(r.get('registered_ts',0)),reverse=True)
    return out[:limit]
