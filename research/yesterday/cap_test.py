"""Run replay_day with a modified endgame cap. Usage: cap_test.py CAP DAY..."""
import runpy, sys
sys.path.insert(0, '.')
import fair as F
cap = int(sys.argv[1])
F.ENDGAME_SCHEDULE = [(t, k, cap, e) for t, k, _, e in F.ENDGAME_SCHEDULE]
tot = 0
for day in sys.argv[2:]:
    sys.argv = ['replay_day.py', day]
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        runpy.run_path('research/yesterday/replay_day.py', run_name='__main__')
    line = [l for l in buf.getvalue().splitlines() if l.startswith('TOTAL')][0]
    eg = sum(float(l.split('pnl')[1].split('|')[0]) for l in buf.getvalue().splitlines() if ' pnl ' in l and l[:1].isdigit())
    print(f'cap {cap} {day} endgame {eg:+.0f} {line}', flush=True)
