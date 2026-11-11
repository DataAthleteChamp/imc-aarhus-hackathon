import sys; sys.path.insert(0,'.')
import numpy as np, itertools
from load import load, HS, P
D=load(); days=sorted(D)
S,E=15*60,17*60+44
def nowc(x,i,h):  # x series, i = last published index
    d=np.diff(x[i-60:i+1]); a=d[:-1]-d[:-1].mean(); b=d[1:]-d[1:].mean()
    phi=float(np.clip((a*b).sum()/max((a*a).sum(),1e-9),-0.9,0.9))
    tr=d[-2:].mean(); return x[i]+tr*sum(phi**k for k in range(1,h+1))
def run(pi,h,H,c,cap,peek=False,lot=5):
    hs=HS[P[pi]]; res=[];nt=0
    for dd in days:
        x=D[dd][:,pi]; pos=[]; pnl=0  # pos list of (exit_minute, qty, entry)
        for T in range(S,E-H+1):
            mid=x[T-2]
            # exits
            for p in [p for p in pos if p[0]==T]:
                pnl+=p[1]*(x[T-2]-p[2]) - abs(p[1])*hs; pos.remove(p)
            net=sum(p[1] for p in pos)
            info = x[T-1] if peek else None
            f = (x[T-1] + 0) if peek else nowc(x,T-2,h)
            e=f-mid
            if e>c*hs and net+lot<=cap: pos.append((T+H,lot,mid+0)); pnl-=lot*hs; nt+=1
            elif -e>c*hs and net-lot>=-cap: pos.append((T+H,-lot,mid)); pnl-=lot*hs; nt+=1
        # note: pnl accounting: entry cost hs charged at entry, exit hs at exit; mid->mid move
        for p in pos: pnl+=p[1]*(x[E-2]-p[2])-abs(p[1])*hs
        res.append(pnl)
    r=np.array(res); return r.mean(),r.std(),(r<0).mean(),nt/len(days)
if __name__=='__main__':
    for pi in range(4):
        best=[]
        for h,H,c,cap in itertools.product([1,2,3],[1,2,5],[1,2,3,4],[10,20,50]):
            m,s,l,n=run(pi,h,H,c,cap); best.append((m,s,l,n,h,H,c,cap))
        best.sort(reverse=True)
        print(P[pi],'top:'); [print('  mean %.0f sd %.0f lose %.2f trades %.1f h%d H%d c%d cap%d'%b) for b in best[:3]]
        print('  worst', '%.0f'%best[-1][0])
        for H in [1,2]:
          for c in [1,2,3]:
            m,s,l,n=run(pi,0,H,c,50,peek=True); print('  PEEK(x[T-1]) H%d c%d mean %.0f sd %.0f lose %.2f trades %.1f'%(H,c,m,s,l,n))
