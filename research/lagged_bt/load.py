import json, numpy as np
from pathlib import Path
R = Path(__file__).resolve().parents[2]
HS = {'1_WIND':3,'2_CO2':5,'3_FLOW':6,'4_ETF':12}
P = list(HS)
def load():
    recs = json.loads((R/'data'/'hist.json').read_text())['records']
    days = {}
    for r in recs:
        d, hm = r['Minutes1DK'][:10], r['Minutes1DK'][11:16]
        m = int(hm[:2])*60+int(hm[3:])
        if any(r.get(k) is None for k in ['OnshoreWindPower','OffshoreWindPower','CO2Emission','Exchange_Sum']): continue
        w=(r['OnshoreWindPower']+r['OffshoreWindPower'])/3; c=r['CO2Emission']*10; f=1000+r['Exchange_Sum']/3
        days.setdefault(d,{})[m]=(w,c,f,w+c+f)
    out={}
    for d,dd in days.items():
        if all(m in dd for m in range(13*60,17*60+45)):
            arr=np.full((1440,4),np.nan)
            for m,v in dd.items(): arr[m]=v
            # ffill
            for i in range(1,1440):
                if np.isnan(arr[i,0]): arr[i]=arr[i-1]
            out[d]=arr
    return out
