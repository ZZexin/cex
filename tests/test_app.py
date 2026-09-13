import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from cex_tool import build_cex, cycle_summary, normalize_table, parse_cex, to_dataframe


def test_adjustment_widgets_export_updated_measurements():
    script = '''
import streamlit as st
import pandas as pd
from cex_tool import build_cex, cycle_summary, normalize_table, parse_cex, to_dataframe
from cex_tool.ui import render_dataset
raw = pd.DataFrame({"Time/s": [0., 60., 120., 180., 240., 300.],
                    "Voltage/V": [1.] * 6,
                    "Current/mA": [-.08] * 3 + [.1] * 3})
df = to_dataframe(parse_cex(build_cex(normalize_table(raw), start_ts=1800000000)))
st.session_state["exports"] = render_dataset(
    "test", df, cycle_summary(df), "test", allow_cycle_adjustments=True)
'''
    app = AppTest.from_string(script).run(timeout=30)
    assert not app.exception
    original_csv = app.session_state["exports"][0]
    app.number_input(key="cap-offset-test").set_value(.01)
    app.number_input(key="ce-offset-test").set_value(2.)
    app.run(timeout=30)
    assert not app.exception
    data_csv, summary_csv = app.session_state["exports"]
    assert data_csv != original_csv
    df = pd.read_csv(io.BytesIO(data_csv))
    summary = pd.read_csv(io.BytesIO(summary_csv))
    back = to_dataframe(parse_cex(build_cex(normalize_table(df), start_ts=1800000000)))
    cols = ["DischargeCapacity_mAh", "ChargeCapacity_mAh", "CoulombicEfficiency_pct"]
    np.testing.assert_allclose(cycle_summary(df)[cols], summary[cols], rtol=1e-9)
    np.testing.assert_allclose(cycle_summary(back)[cols], summary[cols], rtol=1e-6)
    app.number_input(key="cap-offset-test").set_value(-1.).run(timeout=30)
    assert not app.exception
    assert app.error
    assert app.session_state["exports"] == (b"", b"")


def test_cex_to_ndax_page_navigation():
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    app = AppTest.from_file(app_path).run(timeout=30)
    assert not app.exception
    app.switch_page("pages/1_NDAX.py").run(timeout=30)
    assert not app.exception
    assert app.title[0].value == "新威 NDAX 数据解码"
    assert app.selectbox(key="ndax-cycle-rule").value == "文件循环号"


def test_ndax_uploads_adjustments_and_batch_download(monkeypatch):
    from test_ndax import make_ndax

    class Upload(io.BytesIO):
        name = "test.ndax"

    actual_uploader = st.file_uploader
    payloads = [make_ndax(), make_ndax(count=6)]  # Stable ZIP bytes across reruns.

    def uploader(*args, **kwargs):
        if kwargs.get("key") == "ndax-uploads":
            return [Upload(raw) for raw in payloads]
        return actual_uploader(*args, **kwargs)

    monkeypatch.setattr(st, "file_uploader", uploader)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=30)
    app.switch_page("pages/1_NDAX.py").run(timeout=30)
    assert not app.exception
    assert len(app.get("download_button")) == 5  # two exports each, plus ZIP
    area_input = next(n for n in app.number_input if n.key.startswith("ndax-area-0-"))
    assert area_input.value == .18
    measurements = [frame.value for frame in app.dataframe if "SpecificCapacity_mAh_cm2" in frame.value]
    np.testing.assert_allclose(measurements[0].SpecificCapacity_mAh_cm2, measurements[0].Capacity_mAh / .18)
    first_capacity = measurements[0].Capacity_mAh.copy()
    area_input.set_value(.36).run(timeout=30)
    assert not app.exception
    measurements = [frame.value for frame in app.dataframe if "SpecificCapacity_mAh_cm2" in frame.value]
    np.testing.assert_allclose(measurements[0].SpecificCapacity_mAh_cm2, first_capacity / .36)
    np.testing.assert_allclose(measurements[0].Capacity_mAh, first_capacity)
    assert measurements[1].ElectrodeArea_cm2.iloc[0] == .18
    offset_input = next(n for n in app.number_input if n.key.startswith("cap-offset-ndax-0-"))
    offset_input.set_value(.01).run(timeout=30)
    assert not app.exception
    summaries = [frame.value for frame in app.dataframe if "CoulombicEfficiency_pct" in frame.value]
    assert len(summaries) == 2
    assert summaries[0].ChargeCapacity_mAh.iloc[0] == pytest.approx(40 / 3600 + .01)
    assert summaries[1].ChargeCapacity_mAh.iloc[0] == pytest.approx(40 / 3600)
    measurements = [frame.value for frame in app.dataframe if "SpecificCapacity_mAh_cm2" in frame.value]
    np.testing.assert_allclose(measurements[0].SpecificCapacity_mAh_cm2, measurements[0].Capacity_mAh / .36)
    # Invalid adjustments remove only that file's exports, retaining the other file.
    app.number_input(key=offset_input.key).set_value(-1.).run(timeout=30)
    assert not app.exception
    assert len(app.get("download_button")) == 3


def test_voltage_specific_capacity_profile_axes():
    from cex_tool.ui import fig_profiles

    df = pd.DataFrame({"Cycle": [1, 1], "Mode": ["CC_Chg", "CC_Chg"],
                       "Capacity_mAh": [0., .18], "Voltage_V": [1., 1.8]})
    fig = fig_profiles(df, [1], area_cm2=.18)
    np.testing.assert_allclose(fig.data[0].x, [0., 1.])
    np.testing.assert_allclose(fig.data[0].y, df.Voltage_V)
    assert "mAh/cm²" in fig.layout.xaxis.title.text
    assert "mAh/cm²" in fig.data[0].hovertemplate
    np.testing.assert_allclose(fig_profiles(df, [1]).data[0].x, df.Capacity_mAh)


def test_ndax_profile_simulation_exports_reset_and_scope():
    script = '''
import streamlit as st
import pandas as pd
from cex_tool.ndax import parse_ndax
from cex_tool.reader import cycle_summary
from cex_tool.ui import render_dataset
from test_ndax import make_ndax
df=parse_ndax(make_ndax()).data
st.session_state['exports']=render_dataset('profile',df,cycle_summary(df),'profile',
    allow_cycle_adjustments=True,area_cm2=.18,allow_profile_adjustments=True)
'''
    app=AppTest.from_string(script).run(timeout=30)
    assert not app.exception
    original=app.session_state['exports'][0]
    app.multiselect(key='cyc-profile').set_value([1])
    app.checkbox(key='profile-enabled-profile').set_value(True).run(timeout=30)
    assert not app.exception
    app.number_input(key='profile-stretch-profile').set_value(150)
    app.number_input(key='profile-voltage-profile').set_value(.1)
    app.number_input(key='profile-x-profile').set_value(-.01)
    app.run(timeout=30)
    assert not app.exception
    data_csv,summary_csv=app.session_state['exports']
    d=pd.read_csv(io.BytesIO(data_csv))
    source=pd.read_csv(io.BytesIO(original))
    s=pd.read_csv(io.BytesIO(summary_csv))
    chosen=(d.Cycle==1)&(d.Mode=='CC_DChg')
    np.testing.assert_allclose(d.loc[chosen,'Capacity_mAh'],source.loc[chosen,'Capacity_mAh']*1.5)
    np.testing.assert_allclose(d.loc[~chosen,'Capacity_mAh'],source.loc[~chosen,'Capacity_mAh'])
    np.testing.assert_allclose(d.Original_Capacity_mAh,source.Capacity_mAh)
    np.testing.assert_allclose(d.loc[chosen,'PlotSpecificCapacity_mAh_cm2'],d.loc[chosen,'Capacity_mAh']/.18-.01)
    np.testing.assert_allclose(cycle_summary(d).DischargeCapacity_mAh,s.DischargeCapacity_mAh)
    assert set(d.DataKind)=={'profile_simulation'}
    np.testing.assert_allclose(d.Delta_Capacity_mAh,d.Capacity_mAh-source.Capacity_mAh,atol=1e-12)
    np.testing.assert_allclose(d.Delta_Voltage_V,d.Voltage_V-source.Voltage_V,atol=1e-12)
    np.testing.assert_allclose(d.loc[chosen,'Delta_PlotSpecificCapacity_mAh_cm2'],
                               d.loc[chosen,'Delta_SpecificCapacity_mAh_cm2']-.01,atol=1e-12)
    assert d.loc[source.Capacity_mAh==0,'ChangePct_Capacity_mAh'].isna().all()
    assert any('原始值' in frame.value for frame in app.dataframe)
    assert any('模拟数据' in b.label for b in app.get('download_button'))
    # Area changes recompute both physical and display coordinates, not accumulate.
    app.button(key='profile-reset-profile').click().run(timeout=30)
    assert not app.exception
    assert app.session_state['exports'][0]==original
    app.number_input(key='profile-start-profile').set_value(2.).run(timeout=30)
    assert app.error
    assert app.session_state['exports']==(b'',b'')


def test_profile_plot_uses_independent_shift_coordinate():
    from cex_tool.ui import fig_profiles
    d=pd.DataFrame({'Cycle':[1,1],'Mode':['CC_DChg']*2,'Capacity_mAh':[0,.18],
                    'Voltage_V':[1.8,.8],'PlotSpecificCapacity_mAh_cm2':[-.2,.8]})
    fig=fig_profiles(d,[1],.18)
    np.testing.assert_allclose(fig.data[0].x,[-.2,.8])
