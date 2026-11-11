import sys,os,json,requests
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from bot import load_env
load_env()
H={"Content-Type":"application/json; charset=utf-8"}
r=requests.post('https://gamma.cmi-exch.com/api/user/authenticate',headers=H,json={"username":os.environ['CMI_USER'],"password":os.environ['CMI_PASS']})
H['Authorization']=r.headers['Authorization']
t=requests.get('https://gamma.cmi-exch.com/api/trade',headers=H,timeout=30).json()
json.dump(t,open(os.path.join(os.path.dirname(__file__),'trades.json'),'w'))
print(len(t), t[:2] if isinstance(t,list) else str(t)[:300])
