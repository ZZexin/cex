"""Local-only visual verification of the shared NDAX profile panel."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st
from cex_tool.ndax import parse_ndax
from cex_tool.reader import cycle_summary
from cex_tool.ui import render_dataset

st.set_page_config(layout='wide')
source = Path('C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/zmo/selected/zmo, 0.05ma,cm2dcg. 0.18cm2, 1st dark +2nd light 8cm1sun_127.0.0.1-BTS82-45-2-1-2818575312.ndax')
d = parse_ndax(source.read_bytes()).data
for key, value in {'cyc-visual': [2], 'profile-enabled-visual': True,
                   'profile-start-visual': .05, 'profile-end-visual': 1.,
                   'profile-stretch-visual': 120., 'profile-voltage-visual': -.05}.items():
    st.session_state.setdefault(key,value)
st.caption('本地界面验证：原始 NDAX 不修改')
render_dataset(source.stem,d,cycle_summary(d),'visual',True,.18,True)
