import numpy as np
from unittest.mock import patch
from experiment_server.spectra import analyze

def test_known_period_and_gaps_are_not_silently_interpolated(tmp_path):
    t=np.arange(0,20000,100.);rows=[{'time_yr':float(x),'bodies':{'moon':{'e':float(.02+.001*np.sin(2*np.pi*x/2000))}}} for x in t]
    c={'body_names':['moon'],'model':'point_mass'}
    with patch('experiment_server.spectra.saved_rows',return_value=(c,{},rows,[])):
        d=analyze(tmp_path,'signal','moon','e');assert abs(d['peaks'][0]['period_yr']-2000)<1
    import pytest
    with patch('experiment_server.spectra.saved_rows',return_value=(c,{},rows[:10]+rows[11:],[])):
        with pytest.raises(ValueError):analyze(tmp_path,'gap','moon','e')
