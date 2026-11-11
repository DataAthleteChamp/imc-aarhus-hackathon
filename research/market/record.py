import sys, os, json, time, requests, sseclient
sys.path.insert(0, '/Users/jakubpiotrowski/imc-hackathon-prep/team-repo')
from bot import load_env, URL
load_env()
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 300
r = requests.post(f'{URL}/api/user/authenticate', json={'username': os.environ['CMI_USER'], 'password': os.environ['CMI_PASS']})
tok = r.headers['Authorization']
out = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stream.jsonl'), 'a')
s = requests.get(f'{URL}/api/market/stream', stream=True, headers={'Authorization': tok, 'Accept': 'text/event-stream; charset=utf-8'}, timeout=30)
t0 = time.time()
for ev in sseclient.SSEClient(s).events():
    out.write(json.dumps({'rt': time.time(), 'ev': ev.event, 'd': json.loads(ev.data)}) + '\n'); out.flush()
    if time.time() - t0 > DUR: break
out.close()
