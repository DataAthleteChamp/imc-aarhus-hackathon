import json, time, os
p='/Users/jakubpiotrowski/imc-hackathon-prep/team-repo/data/live_rows.json'
out=open('/Users/jakubpiotrowski/imc-hackathon-prep/team-repo/research/market/rows_seen.jsonl','a')
last=None; t0=time.time()
while time.time()-t0<200:
    try:
        d=json.load(open(p)); r=d['rows'][-1]
        if r!=last: out.write(json.dumps({'rt':time.time(),'fetched_at':d['fetched_at'],'last':r,'n':len(d['rows'])})+'\n'); out.flush(); last=r
    except Exception: pass
    time.sleep(1)
