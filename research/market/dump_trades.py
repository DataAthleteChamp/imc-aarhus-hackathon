import sys, os, json, requests
sys.path.insert(0, '/Users/jakubpiotrowski/imc-hackathon-prep/team-repo')
from bot import load_env, URL
load_env()
r = requests.post(f'{URL}/api/user/authenticate', json={'username': os.environ['CMI_USER'], 'password': os.environ['CMI_PASS']})
tok = r.headers['Authorization']
t = requests.get(f'{URL}/api/trade', headers={'Authorization': tok}).json()
json.dump(t, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trades.json'), 'w'))
print(len(t), t[:2])
