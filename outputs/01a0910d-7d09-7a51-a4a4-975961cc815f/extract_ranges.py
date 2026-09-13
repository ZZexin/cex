import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cex_tool.ndax import parse_ndax

sources = json.loads(Path(__file__).with_name('discharge_data.json').read_text(encoding='utf-8'))
rows = []
for file_id, source in enumerate(sources, 1):
    path = Path(source['path'])
    if not path.exists():
        matches = [p for p in path.parent.rglob('*.ndax') if p.name == path.name]
        assert len(matches) == 1, (path, matches)
        path = matches[0]
    ds = parse_ndax(path.read_bytes())
    assert ds.data.Mode.str.endswith(('_Chg', '_DChg')).all(), 'Additional phases need inclusion'
    for cycle, group in ds.data.groupby('Cycle', sort=True):
        for label, suffix in [('充电', '_Chg'), ('放电', '_DChg')]:
            phase = group[group.Mode.str.endswith(suffix)]
            item = dict(id=file_id, material=source['filename'].split(',')[0], filename=source['filename'], cycle=int(cycle), phase=label, n=len(phase))
            if phase.empty:
                item.update(vmin=None, vmax=None, imin=None, imax=None, status='无对应记录')
            else:
                vals = phase[['Voltage_V', 'Current_mA']]
                item.update(vmin=float(vals.Voltage_V.min()), vmax=float(vals.Voltage_V.max()), imin=float(vals.Current_mA.min()*1000), imax=float(vals.Current_mA.max()*1000))
                limits = ds.recipe.loc[ds.recipe['类型'].str.endswith(suffix), '截止电压 V'].dropna().unique()
                assert len(limits) == 1
                voltage, limit = float(phase.Voltage_V.iloc[-1]), float(limits[0])
                reached = voltage >= limit-.0005 if suffix == '_Chg' else voltage <= limit+.0005
                item['status'] = '末点已达截止' if reached else '末点未达截止'
            rows.append(item)
    assert sum(r['n'] for r in rows if r['id']==file_id) == len(ds.data)
assert len(rows) == 128
print(json.dumps(rows, ensure_ascii=True, allow_nan=False))
