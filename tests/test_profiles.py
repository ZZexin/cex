import numpy as np
import pandas as pd
import pytest

from cex_tool.profiles import simulate_profile, with_original_deltas


def records():
    rows = []
    for cycle in [1, 2]:
        for phase, sign in [('CC_Chg', 1), ('CC_DChg', -1)]:
            for k in range(5):
                rows.append(dict(Cycle=cycle, StepSeq=2*(cycle-1)+(1 if sign>0 else 2),
                                 Mode=phase, StepTime_s=k*3600., TestTime_s=len(rows)*3600.,
                                 Capacity_mAh=k*.018, Voltage_V=1.5, Current_mA=sign*.018,
                                 Energy_mWh=k*.018*1.5))
    return pd.DataFrame(rows)


def simulate(df, **kwargs):
    return simulate_profile(df, cycles=[1], phase='discharge', area_cm2=.18,
                            **dict(start=.1, end=.3, **kwargs))


@pytest.mark.parametrize('scale,expected', [(200,[0,.1,.3,.5,.6]), (50,[0,.1,.15,.2,.3])])
def test_platform_capacity_warp_and_equivalent_current(scale, expected):
    df=records()
    before=df.copy(deep=True)
    out=simulate(df, stretch_pct=scale)
    selected=out[(out.Cycle==1)&(out.Mode=='CC_DChg')]
    np.testing.assert_allclose(selected.SpecificCapacity_mAh_cm2, expected)
    dq=np.diff(selected.Capacity_mAh)
    np.testing.assert_allclose(abs(selected.Current_mA.iloc[1:])*np.diff(selected.StepTime_s)/3600,dq)
    np.testing.assert_allclose(selected.Energy_mWh,selected.Capacity_mAh*1.5)
    untouched=(df.Cycle==2)|(df.Mode=='CC_Chg')
    pd.testing.assert_frame_equal(out.loc[untouched,df.columns],df.loc[untouched])
    pd.testing.assert_frame_equal(df,before)
    np.testing.assert_allclose(out.Original_Capacity_mAh,df.Capacity_mAh)


def test_horizontal_shift_does_not_change_measurements():
    df=records()
    out=simulate(df,x_offset=-.2)
    pd.testing.assert_frame_equal(out[df.columns],df)
    selected=(df.Cycle==1)&(df.Mode=='CC_DChg')
    np.testing.assert_allclose(out.loc[selected,'PlotSpecificCapacity_mAh_cm2'],
                               df.loc[selected,'Capacity_mAh']/.18-.2)
    assert out.PlotSpecificCapacity_mAh_cm2.min()==pytest.approx(-.2)
    compared=with_original_deltas(out,df,.18)
    np.testing.assert_allclose(compared.Delta_SpecificCapacity_mAh_cm2,0)
    np.testing.assert_allclose(compared.loc[selected,'Delta_PlotSpecificCapacity_mAh_cm2'],-.2)
    assert compared.loc[selected,'ChangePct_PlotSpecificCapacity_mAh_cm2'].iloc[0]!=compared.loc[selected,'ChangePct_PlotSpecificCapacity_mAh_cm2'].iloc[0]


def test_deltas_compare_raw_source_not_previously_adjusted_baseline():
    raw=records()
    baseline=raw.copy()
    baseline['Capacity_mAh']*=2
    out=simulate(baseline,stretch_pct=150)
    compared=with_original_deltas(out,raw,.18)
    np.testing.assert_allclose(compared.Delta_Capacity_mAh,out.Capacity_mAh-raw.Capacity_mAh)
    np.testing.assert_allclose(compared.Original_Capacity_mAh,raw.Capacity_mAh)


def test_voltage_offset_smooth_edges_and_energy():
    df=records()
    out=simulate(df,voltage_offset_v=.2)
    step=out[(out.Cycle==1)&(out.Mode=='CC_DChg')]
    np.testing.assert_allclose(step.Voltage_V,[1.5,1.5,1.7,1.5,1.5],atol=1e-12)
    np.testing.assert_allclose(out.Capacity_mAh,df.Capacity_mAh)
    np.testing.assert_allclose(out.Current_mA,df.Current_mA)
    np.testing.assert_allclose(step.Energy_mWh,[0,.027,.0558,.0846,.1116])


def test_identity_duplicate_indices_and_no_accumulation():
    df=records()
    df.index=[0]*len(df)
    pd.testing.assert_frame_equal(simulate(df),df)
    one=simulate(df,stretch_pct=150)
    pd.testing.assert_frame_equal(one,simulate(df,stretch_pct=150))
    assert list(one.index)==list(df.index)


@pytest.mark.parametrize('param,value', [('stretch_pct',0),('stretch_pct',float('nan')),
                                        ('x_offset',float('inf')),('edge_pct',51)])
def test_invalid_parameters(param,value):
    with pytest.raises(ValueError):
        simulate(records(),**{param:value})


def test_invalid_interval_and_time_rejected():
    with pytest.raises(ValueError,match='区间'):
        simulate_profile(records(),cycles=[1],phase='discharge',area_cm2=.18,start=1,end=2,stretch_pct=150)
    df=records()
    df.loc[7,'StepTime_s']=3600
    with pytest.raises(ValueError,match='时间|时长'):
        simulate(df,stretch_pct=150)
