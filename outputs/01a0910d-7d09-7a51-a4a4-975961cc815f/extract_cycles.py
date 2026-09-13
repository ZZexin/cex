import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cex_tool.ndax import parse_ndax

sources = json.loads(Path(__file__).with_name('discharge_data.json').read_text(encoding='utf-8'))
results = []
for file_id, source in enumerate(sources, 1):
    ds = parse_ndax(Path(source['path']).read_bytes())
    limits = ds.recipe.loc[ds.recipe['类型'].str.endswith('_DChg'), '截止电压 V'].dropna().unique()
    assert len(limits) == 1, (source['filename'], limits)
    limit = float(limits[0])
    cycles = []
    for cycle, data in ds.data.groupby('Cycle', sort=True):
        discharge = data[data['Mode'].str.endswith('_DChg')]
        ends = discharge.groupby('StepSeq', sort=False).tail(1)
        assert len(ends) <= 1, (source['filename'], cycle, 'multiple discharge segments; aggregation needs review')
        condition = source['condition']
        if '1st dark' in source['filename']:
            condition = 'DARK' if cycle == 1 else '8 cm / 1 sun' if cycle == 2 else '未标注（文件名只说明首、第二圈）'
        if discharge.empty:
            cycles.append(dict(cycle=int(cycle), condition=condition, limit=limit, voltage=None, capacity=None, reached=None, time=None, record=None, step=None))
        else:
            last = discharge.iloc[-1]
            cycles.append(dict(cycle=int(cycle), condition=condition, limit=limit, voltage=float(last.Voltage_V), capacity=float(last.Capacity_mAh), reached=bool(last.Voltage_V <= limit + .0005), time=str(last.DateTime), record=int(last.Index), step=int(last.StepSeq)))
    assert len(cycles) == ds.data['Cycle'].nunique()
    results.append(dict(id=file_id, source=source, cycles=cycles))
print(json.dumps(results, ensure_ascii=True, allow_nan=False))
