import io
from pathlib import Path

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from cex_tool import build_cex, cycle_summary, normalize_table, parse_cex, to_dataframe


def test_adjustment_widgets_export_updated_measurements():
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    script = f'''
import runpy
import streamlit as st
import pandas as pd
from cex_tool import build_cex, cycle_summary, normalize_table, parse_cex, to_dataframe
ui = runpy.run_path({app_path!r})
raw = pd.DataFrame({{"Time/s": [0., 60., 120., 180., 240., 300.],
                    "Voltage/V": [1.] * 6,
                    "Current/mA": [-.08] * 3 + [.1] * 3}})
df = to_dataframe(parse_cex(build_cex(normalize_table(raw), start_ts=1800000000)))
st.session_state["exports"] = ui["render_dataset"](
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
