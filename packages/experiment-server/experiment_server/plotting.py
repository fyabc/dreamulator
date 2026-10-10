"""Dynamic body/pair dashboard; saved trajectories only, no network or force calls."""
import gzip,hashlib,json,math
from pathlib import Path
import numpy as np
from .manager import get_case
from .storage import registry,read,atomic,within,sha
from .config import AU,YEAR,ENERGY_UNIT


def installed_font(explicit=None):
    from matplotlib import font_manager
    paths=[explicit] if explicit else [Path(f.fname) for f in font_manager.fontManager.ttflist
            if any(x in f.name for x in ['Noto Sans CJK','Source Han','Microsoft YaHei','SimHei','WenQuanYi','PingFang'])]
    if not explicit:
        import subprocess
        try:
            r=subprocess.run(['fc-list',':lang=zh','--format=%{file}\n'],capture_output=True,text=True,timeout=5)
            if r.returncode==0:paths+=[Path(p) for p in r.stdout.splitlines() if p]
        except (OSError,subprocess.TimeoutExpired):pass
    for p in paths:
        if p and Path(p).is_file():
            try:
                cmap=font_manager.get_font(str(p)).get_charmap()
                if all(ord(x) in cmap for x in '轨道自转季节内部热流距离误差保存'):return font_manager.FontProperties(fname=str(p))
            except (OSError,RuntimeError):pass
    if explicit:raise ValueError('提供字体缺少所需中文字形。')
    return None


def saved_rows(root,name,last_years):
    _,config=get_case(root,name);run=root/'runs'/name;status=read(run/'status.json') if (run/'status.json').exists() else None
    if not status:return config,None,[],[]
    cutoff=status['epoch_yr']-last_years if last_years>0 else config['initial_state']['epoch_yr'];rows={};sources=[]
    blocks=sorted((p for p in run.glob('checkpoint-*') if not p.name.endswith('.writing')),key=lambda p:float(p.name.split('checkpoint-')[1]))
    for block in blocks:
        epoch=float(block.name.split('checkpoint-')[1])
        if epoch>status['epoch_yr'] or epoch<cutoff:continue
        receipt=read(block/'receipt.json');p=block/'samples.json.gz'
        if sha(p)!=receipt['files']['samples.json.gz']['sha256']:raise ValueError('绘图样本SHA不符。')
        with gzip.open(p,'rt',encoding='utf-8') as f:d=json.load(f)
        rows.update({r['time_yr']:r for r in d['samples'] if r['time_yr']>=cutoff})
        sources.append({'checkpoint':block.name,'samples_sha256':receipt['files']['samples.json.gz']['sha256']})
    return config,status,[rows[t] for t in sorted(rows)],sources


def render(root,names,last_years,active_only,font):
    if not math.isfinite(last_years) or last_years<0:raise ValueError('last-years须为非负有限值。')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.text import Text
    prop=installed_font(font);zh=bool(prop);allnames=[c['name'] for c in registry(root)['cases']]
    if names and any(n not in allnames for n in names):raise ValueError('未知绘图实验名。')
    datasets=[];panels=[]
    for name in names or allnames:
        c,status,rows,sources=saved_rows(root,name,last_years)
        if len(rows)<2 or active_only and status['status']!='running':continue
        datasets.append((name,c,status,rows,sources))
        for body in c['body_names']:
            fields=set().union(*(r['bodies'][body] for r in rows))
            for key in ['a_au','e','i_ref_deg','psi_deg','stellar_season_deg','rotation_days','spin_fixed_z_deg','heat_code']:
                if key in fields and (body,key) not in panels:panels.append((body,key))
        for pair in rows[0]['pairs']:
            for key in ['distance_km','relative_speed_km_s','radial_gap_km']:
                if (pair,key) not in panels:panels.append((pair,key))
    if not datasets:return {'plotted':False,'reason':'暂无完整保存区间；不补画未来。'}
    panels += [('system','energy_heat_error'),('system','angular_momentum_error')]
    titles={'a_au':'半长轴 (千km)' if zh else 'a (1000 km)','e':'偏心率' if zh else 'eccentricity','i_ref_deg':'参考面倾角 (°)' if zh else 'inclination (deg)',
            'psi_deg':'自转–轨道 ψ (°)' if zh else 'spin-orbit psi (deg)','stellar_season_deg':'恒星季节角 (°)' if zh else 'stellar season (deg)',
            'rotation_days':'恒星自转日 (地球日)' if zh else 'sidereal spin (Earth days)','spin_fixed_z_deg':'自转对固定z倾角 (°)' if zh else 'spin to fixed z (deg)',
            'heat_code':'内部热流 20/100/500yr (W/m²)' if zh else 'internal heat 20/100/500yr (W/m2)',
            'distance_km':'实际保存最小距离 (千km)' if zh else 'saved closest distance (1000 km)',
            'relative_speed_km_s':'最小距离样本相对速度 (km/s)' if zh else 'speed at closest sample (km/s)',
            'radial_gap_km':'径向包络最小间隙 (千km)' if zh else 'radial envelope gap (1000 km)',
            'energy_heat_error':'能量加热误差' if zh else 'energy + heat error','angular_momentum_error':'角动量误差' if zh else 'angular momentum error'}
    cols=3;nr=math.ceil(len(panels)/cols);fig,axes=plt.subplots(nr,cols,figsize=(22,max(8,nr*2.8)));axes=np.asarray(axes).ravel();records=[]
    for index,(name,c,status,rows,sources) in enumerate(datasets):
        t=np.array([r['time_yr'] for r in rows]);diff=np.diff(t);gap=np.flatnonzero(diff>c['integration']['interval_yr']*1.001)
        spans=np.split(np.arange(len(t)),gap+1);color=plt.get_cmap('tab10')(allnames.index(name)%10)
        label=name
        if c['model']=='coupled_ctl':
            s=c['initial_state']['settings'];i=c['diagnostics'].get('heat_body',2);ref=c.get('provenance',{}).get('reference_k2tau_yr')
            label+=f' J2={s["j2_array"][i]:g}'+(f' CTLx{s["k2tau_yr"][i]/ref:g}' if ref else '')
        label+=' ('+status['status']+')'
        rec={'name':name,'config_sha256':get_case(root,name)[0]['config_sha256'],'actual_window_yr':[float(t[0]),float(t[-1])],
             'missing_intervals_yr':[[float(t[i]),float(t[i+1])] for i in gap],'checkpoints':sources,'panel_statistics':{}}
        for ax,(body,key) in zip(axes,panels):
            if key=='heat_code':
                if body not in rows[0]['bodies'] or key not in rows[0]['bodies'][body]:continue
                bi=c['body_names'].index(body);radius=c['initial_state']['particles'][bi]['r'];conv=ENERGY_UNIT/(YEAR*4*np.pi*(radius*AU)**2)
                h=np.array([r['bodies'][body][key] for r in rows]);rec['panel_statistics'][body+'.heat']={}
                for width,lw in [(20,.5),(100,.9),(500,1.5)]:
                    xx=[];yy=[]
                    for span in spans:
                        tt=t[span];hh=h[span];grid=tt[tt>=tt[0]+width]
                        flux=(np.interp(grid,tt,hh)-np.interp(grid-width,tt,hh))*conv/width
                        xx.extend([np.nan,*list(grid/1000)]);yy.extend([np.nan,*list(flux)])
                    ax.plot(xx,yy,color=color,lw=lw,label=label if width==500 else None)
                    finite=[v for v in yy if np.isfinite(v)]
                    rec['panel_statistics'][body+'.heat'][str(width)]={'min':min(finite),'max':max(finite)} if finite else None
                ax.axhline(2.24,color='#777',ls=':',lw=.7);ax.set_ylim(bottom=0);continue
            raw=[];speed_values=[];chosen=[]
            for r in rows:
                if body=='system':value=abs(r[key])
                elif body in r['bodies']:value=r['bodies'][body].get(key,np.nan)
                elif body in r['pairs']:
                    pair=r['pairs'][body]
                    if key=='radial_gap_km':
                        a,b=body.split('__');p,q=r['bodies'][a],r['bodies'][b]
                        value=(q['a_au']*(1-q['e'])-p['a_au']*(1+p['e']))*AU/1000 if 'a_au' in p and 'a_au' in q else np.nan
                    else:value=pair.get(key,np.nan)
                else:value=np.nan
                raw.append(value)
            raw=np.asarray(raw);xx=[];yy=[];lo=[];hi=[]
            scale=AU/1e6 if key=='a_au' else .001 if key in ['distance_km','radial_gap_km'] else 1.
            for span in spans:
                tt=t[span]
                if len(tt)<2:continue
                xx.append(np.nan);yy.append(np.nan);lo.append(np.nan);hi.append(np.nan)
                for a in np.arange(tt[0],tt[-1],500):
                    b=min(a+500,tt[-1]);inds=span[(tt>=a)&(tt<=b if b==tt[-1] else tt<b)];v=raw[inds];v=v[np.isfinite(v)]
                    if not len(v):continue
                    value=float(np.sqrt(np.mean(v*v))) if key=='psi_deg' else float(v.min()) if key in ['distance_km','radial_gap_km'] else float(v.max()) if body=='system' else float(np.median(v))
                    if key=='relative_speed_km_s':
                        distances=np.array([rows[i]['pairs'][body]['distance_km'] for i in inds]);j=inds[np.argmin(distances)]
                        value=rows[j]['pairs'][body]['relative_speed_km_s'];chosen.append({'epoch_yr':float(t[j]),**rows[j]['pairs'][body]})
                    xx.append((a+b)/2000);yy.append(value*scale);lo.append(float(v.min())*scale);hi.append(float(v.max())*scale)
            ax.plot(xx,yy,color=color,lw=1.1,label=label)
            if key!='relative_speed_km_s':ax.fill_between(xx,lo,hi,color=color,alpha=.08)
            rec['panel_statistics'][body+'.'+key]={'saved_min':float(np.nanmin(raw)),'saved_max':float(np.nanmax(raw)),'closest_samples':chosen} if np.any(np.isfinite(raw)) else None
            if body=='system':ax.set_yscale('symlog',linthresh=1e-15)
            if key=='radial_gap_km':ax.axhline(0,color='#888',ls=':',lw=.6)
        records.append(rec)
    for ax,(body,key) in zip(axes,panels):ax.set_title(body+' '+titles[key],fontsize=10);ax.set_xlabel('绝对历元 (kyr)' if zh else 'Absolute epoch (kyr)');ax.grid(alpha=.18)
    for ax in axes[len(panels):]:ax.set_visible(False)
    handles,labels=next((ax.get_legend_handles_labels() for ax in axes if ax.get_legend_handles_labels()[0]),([],[]))
    fig.legend(handles,labels,loc='upper center',ncol=3,fontsize=9);fig.suptitle('实验系统完整保存状态' if zh else 'Complete saved experiment dashboard',y=.999,fontsize=18)
    fig.text(.03,.003,'500yr分箱；ψ RMS，其余中位数／范围；指定pair距离最小与配对速度。缺段断线，采样不认证连续安全。' if zh else '500yr bins; psi RMS; closest specified-pair distance and paired speed. Gaps are not bridged; sampling is not continuous safety.',fontsize=9)
    if prop:
        for text in fig.findobj(match=Text):size=text.get_fontsize();text.set_fontproperties(prop);text.set_fontsize(size)
    fig.tight_layout(rect=[0,.02,1,.955]);dest=root/'plots';dest.mkdir(exist_ok=True)
    for ext in ['png','svg']:
        temporary=dest/('latest.tmp.'+ext);fig.savefig(temporary,format=ext,dpi=130);temporary.replace(dest/('latest.'+ext))
    plt.close(fig)
    atomic(dest/'latest-sources.json',{'cases':records,'panel_count':len(panels),'only_actual_saved_rows':True,'no_low_heat_inset':True,'language':'Chinese' if zh else 'English'})
    return {'plotted':True,'outputs':[str(dest/'latest.png'),str(dest/'latest.svg')],'panel_count':len(panels)}
