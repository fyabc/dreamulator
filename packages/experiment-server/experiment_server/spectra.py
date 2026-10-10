"""Finite saved-trajectory spectra with explicit sampling/gap limits."""
from pathlib import Path
import numpy as np
from scipy import signal
from .plotting import saved_rows
from .storage import atomic
from .config import AU,YEAR,ENERGY_UNIT


def analyze(root,name,body,metric):
    c,status,rows,sources=saved_rows(root,name,0)
    if len(rows)<16:raise ValueError('频谱至少需要16个实际保存样本。')
    if body not in c['body_names']:raise ValueError('未知body_name。')
    t=np.array([r['time_yr'] for r in rows]);dt=np.median(np.diff(t))
    if not np.allclose(np.diff(t),dt,rtol=0,atol=1e-8):raise ValueError('存在缺段／非均匀采样；此命令不补插缺段。')
    if metric=='heat_flux':
        if c['model']!='coupled_ctl':raise ValueError('point_mass无内热。')
        h=np.array([r['bodies'][body]['heat_code'] for r in rows]);i=c['body_names'].index(body);conv=ENERGY_UNIT/(YEAR*4*np.pi*(c['initial_state']['particles'][i]['r']*AU)**2)
        y=np.diff(h)*conv/dt;t=t[1:]
    else:
        if not all(metric in r['bodies'][body] for r in rows):raise ValueError('所选body指标不可用。')
        y=np.array([r['bodies'][body][metric] for r in rows])
    f,p=signal.periodogram(y,fs=1/dt,window='hann',detrend='linear');keep=f>0;f=f[keep];p=p[keep];order=np.argsort(p)[-5:][::-1]
    duration=t[-1]-t[0];peaks=[{'period_yr':float(1/f[i]),'power':float(p[i]),'observed_cycles':float(duration*f[i]),
                             'classification':'too_few_cycles_or_trend' if duration*f[i]<5 else 'finite_candidate_not_certified'} for i in order]
    report={'name':name,'body':body,'metric':metric,'actual_window_yr':[float(t[0]),float(t[-1])],'dt_yr':float(dt),'Nyquist_period_yr':float(2*dt),
            'peaks':peaks,'sources':sources,'frequency_per_yr':f.tolist(),'power':p.tolist(),
            'limits':'Hann linear-detrended finite periodogram only; no significance, exactperiod, climate event, or lifetime claim. Otherunresolved frequencies may alias.'}
    dest=root/'analysis'/f'{name}-{body}-{metric}-spectrum.json';atomic(dest,report);return {'output':str(dest),'peaks':peaks}
