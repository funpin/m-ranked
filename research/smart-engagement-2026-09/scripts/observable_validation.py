"""Retrospective counter experiments. No production writes or fraud labels.

Requires numpy/scipy and the production checkout for the code counterexamples.
Run with --panel <jsonl.gz> --repo <checkout> --output <json>.
Optional --figure <png> requires matplotlib and renders the saved aggregates.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID

import numpy as np
from scipy.stats import chi2, poisson, nbinom

SEED = 20260928
PLATFORMS = ('max', 'rutube', 'telegram', 'vk')
HORIZONS = {6: .5, 24: 3, 72: 6, 168: 12}


def describe(x):
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    return {'n': len(a), 'p10': float(np.quantile(a, .1)),
            'median': float(np.median(a)), 'p90': float(np.quantile(a, .9))} if len(a) else {'n': 0}


def rate_ci(hits, n):
    if not n:
        return {'n': 0, 'hits': int(hits), 'rate': None, 'wilson95': None}
    p, z = hits / n, 1.959963984540054
    c = (p + z*z/(2*n)) / (1+z*z/n)
    d = z*np.sqrt(p*(1-p)/n + z*z/(4*n*n))/(1+z*z/n)
    return {'n': int(n), 'hits': int(hits), 'rate': float(p), 'wilson95': [float(c-d), float(c+d)]}


def observed_rate(events, groups, rng):
    """Real posts are clustered. Do not attach an independent-binomial CI."""
    events=np.asarray(events,dtype=float)
    if not len(events):return {'n':0,'hits':0,'rate':None}
    return {'n':len(events),'hits':int(events.sum()),'rate':float(events.mean()),
            'account_bootstrap':cluster_delta(events,groups,rng)}


def cluster_delta(values, groups, rng):
    unique = sorted(set(groups))
    chunks = [np.asarray(values)[np.asarray(groups) == k] for k in unique]
    if len(chunks) < 2:
        return {'clusters': len(chunks), 'ci95': None}
    sums = np.array([v.sum() for v in chunks]); ns = np.array([len(v) for v in chunks])
    draws = rng.integers(0, len(chunks), (2000, len(chunks)))
    boot = sums[draws].sum(axis=1)/ns[draws].sum(axis=1)
    return {'clusters': len(chunks), 'mean': float(np.mean(values)),
            'ci95': list(map(float, np.quantile(boot, [.025, .975])))}


def endpoint(points, hours):
    chosen = [p for p in points if (hours-HORIZONS[hours])*3600 <= p['age_seconds'] <= hours*3600]
    return max(chosen, key=lambda p: p['age_seconds']) if chosen else None


def valid(p, metric, exact=False):
    return (p is not None and p[metric] is not None and not p['uncertain']
            and p[metric+'q'] in (('exact',) if exact else ('exact', 'rounded')))


def load_panel(path):
    raw = gzip.decompress(path.read_bytes())
    posts = [json.loads(line) for line in raw.splitlines() if line]
    account_posts = defaultdict(list)
    for p in posts:
        p['published'] = datetime.fromisoformat(p['published_at'])
        p['points'] = sorted(p['points'] or [], key=lambda z: z['age_seconds'])
        p['endpoints'] = {h: endpoint(p['points'], h) for h in HORIZONS}
        if 'refreshed_points' in p:
            for h in (24,72,168):
                p['endpoints'][h]=endpoint(p['refreshed_points'],h)
        account_posts[p['primary_account_id']].append(p['published'])
    for p in posts:
        p['prior_posts_24h'] = sum(0 < (p['published']-t).total_seconds() <= 86400
                                   for t in account_posts[p['primary_account_id']])
    return posts, hashlib.sha256(raw).hexdigest()


def data_audit(posts):
    out = {}
    for platform in PLATFORMS:
        ps = [p for p in posts if p['platform'] == platform]
        pairs = [(a,b) for p in ps for a,b in zip(p['points'],p['points'][1:])]
        exact_pairs = [(a,b) for a,b in pairs if valid(a,'v',True) and valid(b,'v',True)]
        allp = [z for p in ps for z in p['points']]
        endpoints = {}
        for h in HORIZONS:
            ep = [p['endpoints'][h] for p in ps]
            good = [q for q in ep if valid(q,'v') and valid(q,'r') and q['v'] > 0]
            endpoints[str(h)] = {'views_available':sum(valid(q,'v') for q in ep),
                'views_exact':sum(valid(q,'v',True) for q in ep), 'vr_pairs':len(good),
                'zero_reactions':sum(q['r']==0 for q in good),
                'rv_ratio':describe([q['r']/q['v'] for q in good]),
                'staleness_h':describe([(h*3600-q['age_seconds'])/3600 for q in ep if q])}
        mature = [p for p in ps if valid(p['endpoints'][24],'v') and valid(p['endpoints'][168],'v')
                  and p['endpoints'][168]['v']>0 and p['endpoints'][168]['v']>=p['endpoints'][24]['v']]
        out[platform] = {'posts':len(ps),'accounts':len({p['primary_account_id'] for p in ps}),
            'snapshots':len(allp),'no_snapshots':sum(not p['points'] for p in ps),
            'endpoint_refreshed_posts':sum('refreshed_points' in p for p in ps),
            'quality_views':dict(Counter(q['vq'] for q in allp)),
            'uncertain':sum(q['uncertain'] for q in allp),
            'text_length_known':sum(p['text_length'] is not None for p in ps),
            'types':dict(Counter(p['publication_type'] for p in ps)),
            'endpoints':endpoints,'saved_exact_intervals':len(exact_pairs),
            'negative_view_deltas':sum(b['v']<a['v'] for a,b in exact_pairs),
            'zero_view_deltas':sum(b['v']==a['v'] for a,b in exact_pairs),
            'interval_hours':describe([(b['age_seconds']-a['age_seconds'])/3600 for a,b in pairs]),
            'fraction_views_after_24h_of_7d':describe([1-p['endpoints'][24]['v']/p['endpoints'][168]['v'] for p in mature])}
    return out


def split(p):
    day = p['published_at'][:10]
    if '2026-09-06' <= day < '2026-09-10': return 'fit'
    if '2026-09-13' <= day < '2026-09-17': return 'cal'
    if '2026-09-20' <= day < '2026-09-25' and p['published']+timedelta(hours=72) <= datetime(2026,9,27,16,30,tzinfo=timezone.utc): return 'test'
    return 'embargo'


def design(rows, train, mode):
    early = np.log1p([p['endpoints'][24]['v'] for p in rows])
    cols = [np.ones(len(rows)), early]
    if mode != 'pooled':
        for plat in PLATFORMS[1:]:
            indicator = np.array([p['platform']==plat for p in rows],float)
            cols.extend([indicator,indicator*early])
    if mode in ('context','prior_frequency'):
        accounts = sorted({rows[i]['primary_account_id'] for i in train})
        types = sorted({rows[i]['publication_type'] for i in train})
        cols.extend(np.array([p['primary_account_id']==v for p in rows],float) for v in accounts)
        cols.extend(np.array([p['publication_type']==v for p in rows],float) for v in types[1:])
        cols.extend([np.log1p([p['text_length'] or 0 for p in rows]),
                     np.array([p['text_length'] is None for p in rows],float)])
        for period, clock in ((24,[p['published'].hour for p in rows]),(7,[p['published'].weekday() for p in rows])):
            phase=2*np.pi*np.asarray(clock)/period;cols.extend([np.sin(phase),np.cos(phase)])
        for h in (24,72):cols.append(np.array([p['endpoints'][h]['age_seconds']/3600-h for p in rows]))
    if mode == 'prior_frequency': cols.append(np.log1p([p['prior_posts_24h'] for p in rows]))
    x = np.column_stack(cols)
    # Standardize only continuous columns; one-hot effects share a fixed ridge prior.
    continuous = [j for j in range(1,x.shape[1]) if len(np.unique(x[train,j]))>2]
    for j in continuous:
        mu,sd=x[train,j].mean(),x[train,j].std();x[:,j]=(x[:,j]-mu)/max(sd,1e-8)
    return x


def predictive(posts, exact=False):
    rng=np.random.default_rng(SEED)
    rows=[p for p in posts if split(p)!='embargo' and valid(p['endpoints'][24],'v',exact)
          and valid(p['endpoints'][72],'v',exact) and p['endpoints'][72]['v']>=p['endpoints'][24]['v']]
    ix={s:np.array([i for i,p in enumerate(rows) if split(p)==s],int) for s in ('fit','cal','test')}
    for left,right in (('fit','cal'),('cal','test')):
        assert len(ix[left]) and len(ix[right]), 'empty temporal split'
        assert max(rows[i]['published']+timedelta(hours=72) for i in ix[left]) < min(rows[i]['published'] for i in ix[right])
    y=np.log1p([p['endpoints'][72]['v'] for p in rows])
    result={'eligible':len(rows),'counts':{s:len(v) for s,v in ix.items()},'models':{}}
    predictions={}
    for mode in ('pooled','platform','context','prior_frequency'):
        x=design(rows,ix['fit'],mode); penalty=np.eye(x.shape[1])*10;penalty[0,0]=0
        beta=np.linalg.solve(x[ix['fit']].T@x[ix['fit']]+penalty,x[ix['fit']].T@y[ix['fit']])
        prediction=x@beta; predictions[mode]=prediction
        err=np.abs(y[ix['test']]-prediction[ix['test']])
        report={'mae_log1p':float(err.mean()),'by_platform':{}}
        for plat in PLATFORMS:
            cal=np.array([i for i in ix['cal'] if rows[i]['platform']==plat],int)
            test=np.array([i for i in ix['test'] if rows[i]['platform']==plat],int)
            if not len(cal) or not len(test):continue
            c=y[cal]-prediction[cal];s=y[test]-prediction[test]
            groups=[rows[i]['primary_account_id'] for i in test]
            # Conservative discrete upper-tail ranks. Not certified p-values on this archive.
            ranks=(1+(c[:,None]>=s).sum(axis=0))/(len(c)+1)
            b={'cal':len(cal),'test':len(test),'mae_log1p':float(np.abs(s).mean()),
               'minimum_attainable_rank':1/(len(cal)+1),
               'inference_status':'insufficient_calibration_resolution' if len(cal)<19 else 'exploratory_only',
               'upper_rank_le_05':observed_rate(ranks<=.05,groups,rng)}
            if mode=='platform':
                b['paired_mae_delta_vs_pooled']=cluster_delta(np.abs(s)-np.abs(y[test]-predictions['pooled'][test]),groups,rng)
            if mode=='context':
                b['paired_mae_delta_vs_platform']=cluster_delta(
                    np.abs(s)-np.abs(y[test]-predictions['platform'][test]),
                    [rows[i]['primary_account_id'] for i in test],rng)
                b['injections']={}
                for fraction in (.1,.3,1.):
                    original=np.rint(np.expm1(y[test]))
                    injected=np.log1p(original+np.rint(original*fraction))-prediction[test]
                    irank=(1+(c[:,None]>=injected).sum(axis=0))/(len(c)+1)
                    base_clear=ranks>.05
                    b['injections'][str(fraction)]={'flagged':observed_rate(irank<=.05,groups,rng),
                        'newly_flagged_among_base_clear':observed_rate((irank<=.05)[base_clear],np.asarray(groups)[base_clear],rng)}
            report['by_platform'][plat]=b
        result['models'][mode]=report
    # Endpoint ratio detector is exactly invariant to proportional view+reaction scaling.
    ratio_rows=[p for p in rows if split(p)=='test' and valid(p['endpoints'][72],'r') and p['endpoints'][72]['v']>0]
    result['ratio_invariance']={'test_posts':len(ratio_rows),'max_abs_difference':max((abs(
        (1.3*p['endpoints'][72]['r'])/(1.3*p['endpoints'][72]['v'])-p['endpoints'][72]['r']/p['endpoints'][72]['v'])
        for p in ratio_rows),default=0)}
    return result


def simulations(repo):
    sys.path.insert(0,str(repo))
    from anomaly_analysis.v2.detectors.reactions_catch_up import _segment, detect
    from anomaly_analysis.v2.detectors.base import DetectorContext
    from anomaly_analysis.v2.detectors.base import SiblingActivity
    from anomaly_analysis.v2.detectors import synchronous_rise
    from anomaly_analysis.v2.detectors import reactions_exceed_views
    from collector_runtime.public_web import parse_public_page
    from anomaly_analysis.v2.domain import Metric, PostSeries
    from anomaly_analysis.v2.series import CollectionCadence, prepare, confirm_unchanged
    rng=np.random.default_rng(SEED); n=10000; windows=40
    raw=rng.poisson(40,size=(n,windows+1))
    cases={'poisson_raw':(raw[:,1:].astype(float),np.full((n,windows),500.)),
           'poisson_half_cell_interpolation':((raw[:,1:]+raw[:,:-1])/2,np.full((n,windows),500.)),
           'finite_audience_binomial_q06':(rng.binomial(100,.6,size=(n,windows)).astype(float),np.full((n,windows),100.)),
           'proportional_low_noise':((40+rng.integers(-2,3,size=(n,windows))).astype(float),np.full((n,windows),500.))}
    out={}
    for name,(dr,dv) in cases.items():
        dispersion=((dr-dr.mean(axis=1,keepdims=True))**2/dr.mean(axis=1,keepdims=True)).sum(axis=1)/(windows-1)
        hits=sum(_segment(a,b) is not None for a,b in zip(dr,dv))
        out[name]={'median_D':float(np.median(dispersion)), 'current_suffix_detector':rate_ci(hits,n)}
    # Calibrate the entire suffix scan after the exact same interpolation operator.
    def scan_score(a):
        count=np.arange(a.shape[1],0,-1)
        sums=np.cumsum(a[:,::-1],axis=1)[:,::-1]
        sq=np.cumsum(a[:,::-1]**2,axis=1)[:,::-1]
        statistic=sq/np.maximum(sums/count,1e-12)-sums
        p=chi2.cdf(np.maximum(statistic,0),np.maximum(count-1,1))
        p[:,count<8]=1
        p[sums<30]=1
        return -np.log10(np.maximum(p.min(axis=1),1e-300))
    cal_score=scan_score(cases['poisson_half_cell_interpolation'][0])
    threshold=float(np.sort(cal_score)[int(np.ceil((n+1)*.99))-1])
    independent=rng.poisson(40,size=(10000,windows+1))
    test_score=scan_score((independent[:,1:]+independent[:,:-1])/2)
    corrected={'nominal_alpha':.01,'calibration_replicates':n,'score_threshold':threshold,
               'independent_null':rate_ci((test_score>threshold).sum(),len(test_score)),
               'low_noise_injection':rate_ci((scan_score(cases['proportional_low_noise'][0])>threshold).sum(),n),
               'scope':'known stationary Poisson mean=40 plus specified half-cell interpolation only'}
    # Full production preparation + detector, equal 6h observations shifted 3h from the grid.
    full={}; start=datetime(2026,8,1,tzinfo=timezone.utc)
    for shifted in (False,True):
        hits=0;usable=[]
        for j in range(500):
            ages=72+np.arange(windows+1)*6+(3 if shifted else 0)
            reactions=np.r_[1000,1000+np.cumsum(raw[j,:windows])]
            views=np.arange(windows+1)*500+12500
            dates=tuple(start+timedelta(hours=float(h)) for h in ages)
            series=PostSeries(UUID(int=1),UUID(int=2),'rutube',start,False,dates,
                {Metric.VIEWS:tuple(map(int,views)),Metric.REACTIONS:tuple(map(int,reactions))})
            prepared=prepare(series,dates[-1],CollectionCadence())
            hits+=bool(detect(prepared,DetectorContext('rutube')))
            usable.append(int(prepared.metrics[Metric.REACTIONS].grids[timedelta(hours=6)].usable.sum()))
        full['shift_3h' if shifted else 'aligned']=rate_ci(hits,500)|{'usable_cells':describe(usable)}
    # Archive selection: success with no counter change is absent unless checkpoint saved it.
    z=rng.poisson(.2,size=100000)
    selected=z[z>0]
    observation={'underlying_mean':float(z.mean()),'positive_only_mean':float(selected.mean()),
        'true_zero_fraction':float((z==0).mean()),'selected_zero_fraction':0.,
        'analytic_positive_only_mean':float(.2/(1-np.exp(-.2)))}
    # Current account log can produce a short apparent burst from an unresolved long interval.
    ages,rows,covered=confirm_unchanged(np.array([72.,96.])*3600,
        np.arange(72.5,96.1,.5)*3600,CollectionCadence(),'max')
    carry={'raw_interval_h':24,'growth_interval_after_carry_h':float((ages[-1]-ages[-2])/3600),
           'inserted_points':len(ages)-2,'hypothetical_speed_multiplier':float(24/((ages[-1]-ages[-2])/3600))}
    # NHPP integral comparison, lambda=A/(t+1)^1.5. Independent counts per true interval.
    boundaries=np.array([0,.25,1,3,6,12,24,48,72,168.])
    a,b=boundaries[:-1],boundaries[1:]; exact=2000*(1/np.sqrt(a+1)-1/np.sqrt(b+1))
    endpoint_rate=1000*(b-a)/(b+1)**1.5
    midpoint_rate=1000*(b-a)/((a+b)/2+1)**1.5
    integral={'endpoint_relative_error':list(map(float,endpoint_rate/exact-1)),
              'midpoint_relative_error':list(map(float,midpoint_rate/exact-1))}
    looks=rng.uniform(size=(10000,100))
    repeated={'uncorrected_any_005':rate_ci((looks.min(axis=1)<=.05).sum(),len(looks)),
              'bonferroni_any_00005':rate_ci((looks.min(axis=1)<=.05/100).sum(),len(looks)),
              'analytic_uncorrected':1-.95**100}
    mixed=rng.negative_binomial(2,2/102,size=10000)
    heterogeneity={'mean':100,'variance':5100,
        'poisson_nominal_05':rate_ci((mixed>poisson.ppf(.95,100)).sum(),len(mixed)),
        'negative_binomial_nominal_05':rate_ci((mixed>nbinom.ppf(.95,2,2/102)).sum(),len(mixed)),
        'poisson_z_ge_6':rate_ci(((mixed-100)/10>=6).sum(),len(mixed))}
    # Shared legitimate exposure event, reaction-only behavior need not add subscribers.
    days=tuple(start+timedelta(hours=h) for h in range(73))
    rv=np.ones(72,dtype=int);rv[50]=60
    vv=rv*30
    series=[PostSeries(UUID(int=i+10),UUID(int=2),'max',start,False,days,
        {Metric.VIEWS:tuple(map(int,np.r_[5000,5000+np.cumsum(vv)])),
         Metric.REACTIONS:tuple(map(int,np.r_[100,100+np.cumsum(rv)]))}) for i in range(3)]
    siblings=SiblingActivity.from_series(series[1:],start.timestamp(),days[-1].timestamp())
    sync=synchronous_rise.detect(prepare(series[0],days[-1],CollectionCadence()),
                                 DetectorContext('max',siblings=siblings))
    sync_result={'shared_exogenous_event_posts':3,'subscriber_data':'absent',
        'signs':len(sync),'strengths':[s.strength for s in sync],
        'scope':'constructed known common cause, no claim about real posts'}
    html='''<div class="tgme_widget_message" data-post="example/42">
      <div class="tgme_widget_message_reactions">
        <span class="tgme_reaction tgme_reaction_paid"><i></i>200</span></div>
      <span class="tgme_widget_message_views">100</span>
      <time datetime="2026-08-01T00:00:00+00:00"></time></div>'''
    parsed=parse_public_page(html,'example')[0]
    paid_series=PostSeries(UUID(int=99),UUID(int=2),'telegram',start,False,
        (start+timedelta(hours=1),start+timedelta(hours=2)),
        {Metric.VIEWS:(parsed.views_count,)*2,Metric.REACTIONS:(parsed.reactions.total,)*2})
    paid_signs=reactions_exceed_views.detect(prepare(paid_series,start+timedelta(hours=2),CollectionCadence()),
                                           DetectorContext('telegram'))
    paid={'parsed_breakdown':dict(parsed.reactions.reactions),'parsed_total':parsed.reactions.total,
          'views':parsed.views_count,'exceed_pattern_signs':len(paid_signs),
          'strengths':[s.strength for s in paid_signs],
          'scope':'constructed paid-star donation supported by Telegram semantics, not an observed incident'}
    # Same observed realization under a different unobserved provenance decomposition.
    counts=rng.poisson(10,size=(100,48)); hidden_paid=rng.binomial(counts,.3)
    identical=bool(np.array_equal(counts,(counts-hidden_paid)+hidden_paid))
    return {'dispersion':out,'observation_aware_scan':corrected,
            'full_production_detector':full,'observation_selection':observation,
            'account_log_counterexample':carry,'interval_integration':integral,'repeated_looks':repeated,
            'count_heterogeneity':heterogeneity,'shared_event_counterexample':sync_result,
            'paid_reaction_semantics':paid,
            'identifiability':{'paired_trajectories':100,'observable_equality':identical,
                               'hidden_paid_fraction_realized':float(hidden_paid.sum()/counts.sum())}}


def render_figure(result, path):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(1, 3, figsize=(16, 6.4), gridspec_kw={'width_ratios': [1, 1.3, 1]})
    fig.subplots_adjust(left=.065, right=.98, bottom=.27, top=.73, wspace=.4)
    fig.suptitle('Нетипичный отклик: что подтвердили проверки', x=.065, y=.96,
                 ha='left', fontsize=19, fontweight='bold')
    fig.text(.065, .885, '8730 публикаций · 96 аккаунтов · 2,03 млн исходных снимков · срез 28.09.2026', color='#506075')
    models = result['predictive']['models']
    modes = ['pooled', 'platform', 'context', 'prior_frequency']
    errors = [models[m]['mae_log1p'] for m in modes]
    ax = axes[0]
    ax.barh(range(4), errors, color=['#9daebe', '#087f8c', '#9daebe', '#9daebe'], height=.6)
    ax.set_yticks(range(4), ['Общая', 'Платформа', '+ Контекст', '+ Частота'])
    ax.invert_yaxis(); ax.set_xlim(0, max(errors)*1.32)
    for i, value in enumerate(errors): ax.text(value+.003, i, f'{value:.4f}', va='center', fontsize=10)
    ax.set_xlabel('MAE log(1 + V72), меньше — лучше')
    ax.set_title('1. Прогноз на 1015 постах', loc='left', pad=19, fontweight='bold')
    ax = axes[1]
    for offset, (plat, label, color) in enumerate([('max','MAX','#087f8c'), ('telegram','Telegram','#377ad0'), ('vk','VK','#c06b2e')]):
        records = [models['context']['by_platform'][plat]['injections'][str(f)]['newly_flagged_among_base_clear'] for f in (.1,.3,1.)]
        rates = np.array([r['rate'] for r in records])*100
        ci = np.array([r['account_bootstrap']['ci95'] for r in records])*100
        ax.errorbar(np.arange(3)+(offset-1)*.045, rates, yerr=np.stack([rates-ci[:,0],ci[:,1]-rates]),
                    marker='o', capsize=3, color=color, label=label, linewidth=1.8)
    ax.set_xticks(range(3), ['+10%', '+30%', '+100%']); ax.set_ylim(-4, 108)
    ax.set_yticks([0,25,50,75,100]); ax.set_ylabel('Новые сигналы, % исходно без сигнала')
    ax.set_xlabel('Добавка к V72 при фиксированном V24')
    ax.set_title('2. Чувствительность к добавкам', loc='left', pad=19, fontweight='bold')
    ax.grid(axis='y', alpha=.18); ax.legend(frameon=False, loc='lower right', fontsize=9)
    ax = axes[2]
    sim = result['simulations']['full_production_detector']
    rates = [sim[s]['rate']*100 for s in ('aligned', 'shift_3h')]
    ci = np.array([sim[s]['wilson95'] for s in ('aligned', 'shift_3h')])*100
    ax.bar([0,1], rates, color=['#9daebe','#b94948'], width=.55)
    ax.errorbar([0,1], rates, yerr=np.stack([np.maximum(0,np.array(rates)-ci[:,0]), ci[:,1]-rates]),
                fmt='none', color='#293647', capsize=4)
    for i, rate in enumerate(rates): ax.text(i, ci[i,1]+1.5, f'{rate:.1f}%', ha='center', fontweight='bold')
    ax.set_xticks([0,1], ['Сетка совпала', 'Сдвиг на 3 ч']); ax.set_ylim(0, 35)
    ax.set_ylabel('Найден паттерн недодисперсии, %')
    ax.set_xlabel('Реальные интервалы по 6 ч; n = 500')
    ax.set_title('3. Артефакт интерполяции', loc='left', pad=19, fontweight='bold')
    ax.grid(axis='y', alpha=.18); ax.set_axisbelow(True)
    fig.text(.065, .12, '1 — ретроспективный прогноз; независимых меток накрутки нет.  2 — синтетическое изменение конечной точки;\n'
             '95%-интервалы: bootstrap аккаунтов.  3 — пуассоновский модельный контроль с production prepare + detect;\n'
             'Wilson 95%, наличие паттерна до ограничения публичного уровня. Эти доли не оценивают реальный FPR или recall.',
             fontsize=9, color='#506075', linespacing=1.65)
    fig.savefig(path, dpi=150, facecolor='white')
    plt.close(fig)


def main():
    p=argparse.ArgumentParser();p.add_argument('--panel',type=Path,required=True)
    p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--figure',type=Path);a=p.parse_args()
    posts,sha=load_panel(a.panel)
    result={'seed':SEED,'panel_uncompressed_sha256':sha,'numpy':np.__version__,
            'design':'retrospective, no verified fraud/organic labels; no production changes',
            'data_audit':data_audit(posts),'predictive':predictive(posts),
            'predictive_exact_only':predictive(posts,True),'simulations':simulations(a.repo)}
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    if a.figure: render_figure(result, a.figure)
    print(json.dumps({'output':str(a.output),'posts':len(posts),'predictive_counts':result['predictive']['counts']}))


if __name__=='__main__': main()
