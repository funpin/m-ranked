"""H65–H67: bounded source-time audit, window resolution and blind review preparation."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import timedelta, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
import uuid

import numpy as np

import window_reference as W
I=W.I
G=W.G
P=W.P
T=W.T
SEED=20269528
PROTOCOL_SHA='136118dd4e8f2e4d3b1a1e133d1faa2a5aa8c944e08bdad96e2b515f9bcbbeb5'
LENGTHS=(7,10,14)
CLASSES=('missing','ambiguous','changed_values','exact_before_fit_cutoff','exact_late','exact_after_panel_cutoff','unknown_time')


def rng(*keys):return np.random.default_rng(np.random.SeedSequence([SEED,*keys]))


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def provenance(root):
    folder=root/'research/smart-engagement-2026-09'
    doc=(folder/'READINESS_AUDIT.md').read_text()
    protocol=doc.split('## Протокол H65–H67 до исходов\n',1)[1].split('## Результаты\n',1)[0]
    sha=hashlib.sha256(protocol.encode()).hexdigest()
    if sha!=PROTOCOL_SHA:raise ValueError('Registered protocol changed')
    return {'protocol_sha256':sha,'script_sha256':P.sha(__file__),'window_script_sha256':P.sha(W.__file__),
            'interval_script_sha256':P.sha(I.__file__),'generator_sha256':P.sha(P.__file__),
            'test_sha256':P.sha(root/'tests/test_readiness_audit_research.py'),'seed':SEED,
            'production_changed':False,'storage_changed':False}


def load_panel(root):
    W.source_contract(root)
    folder=root/'research/smart-engagement-2026-09/local_data'
    posts,_,sha=T.load(folder/'max_tail_panel_2026-09-28.jsonl.gz')
    if sha!=P.PANEL_SHA:raise ValueError('Frozen panel changed')
    cohort=json.loads((folder/'max_tail_cohort_2026-09-28.json').read_text())
    return posts,cohort


def endpoint_inputs(posts):
    prepared,_=I.prepare(posts)
    windows=W.extract(prepared,I.START,I.SPLIT,source_verified=True)
    post_by_id={p['id']:p for p in prepared}
    points={p['id']:{x['at']:x['point'] for x in p['points']} for p in prepared}
    result={}
    for account,w in sorted(windows.items()):
        keys=sorted({(r['post'],t) for r in w['rows'] for t in (r['start'],r['end'])})
        rows=[]
        for post,at in keys:
            p=points[post][at];published=post_by_id[post]['published'].astimezone(timezone.utc)
            rows.append({'publication_id':str(uuid.UUID(post)), 'published_month':published.date().replace(day=1).isoformat(),
                'observed_at':at.isoformat(),'revision':p['correction_sequence'],'v':p['v'],'r':p['r']})
        result[account]=rows
    return result


def select_cards(posts,cohort):
    key=lambda kind,value:hashlib.sha256(f'{SEED}:{kind}:{value}'.encode()).digest()
    chosen=sorted((c['id'] for c in cohort),key=lambda a:key('account',a))[:12]
    start=T.dt('2026-09-07T00:00:00+03:00');end=I.SPLIT
    cards=[]
    for account in chosen:
        eligible=[p['post'] for p in posts if p['post']['primary_account_id']==account and not p['post']['is_repost']
                  and start<=T.dt(p['post']['published_at'])<end]
        for post in sorted(eligible,key=lambda p:key('post',p['id']))[:2]:
            cards.append({'post':post['id'],'account':account,'published_at':post['published_at'],
                          'type':post['publication_type']})
    cards.sort(key=lambda p:key('order',p['post']))
    return {'accounts':chosen,'cards':[{'card_id':f'B02-{i+1:02d}',**p} for i,p in enumerate(cards)],
            'selection_uses_outcomes':False,'retrospective_panel_not_independent_holdout':True}


def classify(matches):
    if not matches:return 'missing'
    if len(matches)>1:return 'ambiguous'
    m=matches[0]
    if not m['same_values']:return 'changed_values'
    if m.get('created_at') is None:return 'unknown_time'
    at=T.dt(m['created_at'])
    if at<I.SPLIT:return 'exact_before_fit_cutoff'
    if at<T.dt('2026-09-28T00:00:00+00:00'):return 'exact_late'
    return 'exact_after_panel_cutoff'


def query_batch(account,rows,batch_id):
    if not 1<=len(rows)<=500:raise ValueError('Audit batch must contain 1..500 endpoints')
    for r in rows:uuid.UUID(r['publication_id'])
    account=str(uuid.UUID(account));input_hash=digest(rows)
    literal=json.dumps(rows,separators=(',',':')).replace("'","''")
    sql=f"""BEGIN READ ONLY;
SET LOCAL statement_timeout='15s'; SET LOCAL lock_timeout='1s'; SET LOCAL TIME ZONE 'UTC';
WITH input AS (
 SELECT * FROM jsonb_to_recordset('{literal}'::jsonb)
 AS x(publication_id uuid,published_month date,observed_at timestamptz,revision bigint,v bigint,r bigint)
), matched AS (
 SELECT x.*,m.n,m.same_values,m.created_at FROM input x
 CROSS JOIN LATERAL (
   SELECT count(*) AS n,bool_and(s.views_count IS NOT DISTINCT FROM x.v
     AND s.reactions_count IS NOT DISTINCT FROM x.r AND s.views_quality::text='exact'
     AND s.reactions_quality::text='exact' AND NOT s.interval_uncertain AND NOT s.synthetic) AS same_values,
     min(s.created_at) AS created_at
   FROM (SELECT s.views_count,s.reactions_count,s.views_quality,s.reactions_quality,s.interval_uncertain,
           s.synthetic,s.created_at FROM ingest.publication_metric_snapshot s
     WHERE s.published_month=x.published_month AND s.publication_id=x.publication_id
       AND s.observed_at=x.observed_at AND s.correction_sequence=x.revision LIMIT 3) s
 ) m
), classified AS (
 SELECT *,CASE WHEN n=0 THEN 'missing' WHEN n>1 THEN 'ambiguous'
   WHEN same_values IS DISTINCT FROM true THEN 'changed_values' WHEN created_at IS NULL THEN 'unknown_time'
   WHEN created_at<'2026-09-20 21:00+00' THEN 'exact_before_fit_cutoff'
   WHEN created_at<'2026-09-28 00:00+00' THEN 'exact_late'
   ELSE 'exact_after_panel_cutoff' END AS category FROM matched
), counts AS (SELECT category,count(*) AS n FROM classified GROUP BY category)
SELECT jsonb_build_object('batch_id',{batch_id},'account','{account}','input_sha256','{input_hash}',
 'requested',(SELECT count(*) FROM input),'query_time',clock_timestamp(),
 'counts',(SELECT jsonb_object_agg(category,n) FROM counts),
 'min_exact_created_at',(SELECT min(created_at) FROM classified WHERE n=1 AND same_values),
 'max_exact_created_at',(SELECT max(created_at) FROM classified WHERE n=1 AND same_values));
COMMIT;
"""
    return sql,{'batch_id':batch_id,'account':account,'requested':len(rows),'input_sha256':input_hash}


def context_sql(cards):
    if not 1<=len(cards)<=24:raise ValueError('Context sample must contain 1..24 posts')
    values=','.join(f"('{uuid.UUID(c['post'])}'::uuid)" for c in cards)
    return f"""BEGIN READ ONLY;
SET LOCAL statement_timeout='15s'; SET LOCAL lock_timeout='1s';
WITH sample(id) AS (VALUES {values})
SELECT jsonb_build_object('requested_post',t.id,'post',p.id,'account',p.primary_account_id,
 'published_at',p.published_at,'type',p.publication_type,'public_url',i.public_url,'query_time',clock_timestamp())
FROM sample t LEFT JOIN ingest.publication p ON p.id=t.id
LEFT JOIN LATERAL (SELECT public_url FROM ingest.publication_identity i
 WHERE i.publication_id=p.id AND i.role='primary' ORDER BY i.id LIMIT 1) i ON true
ORDER BY t.id;
COMMIT;
"""


def prepare_queries(root,folder):
    posts,cohort=load_panel(root);inputs=endpoint_inputs(posts)
    sql=[];batches=[]
    for account,rows in inputs.items():
        for start in range(0,len(rows),500):
            statement,batch=query_batch(account,rows[start:start+500],len(batches))
            sql.append(statement);batches.append(batch)
    if len(batches)>256:raise ValueError('Total query batch cap exceeded')
    selection=select_cards(posts,cohort)
    folder.mkdir(exist_ok=True,parents=True)
    (folder/'temporal.sql').write_text('\n'.join(sql))
    (folder/'context.sql').write_text(context_sql(selection['cards']))
    manifest={'panel_sha256':P.PANEL_SHA,'batches':batches,'requested':sum(b['requested'] for b in batches),
        'accounts':len(inputs),'selection':selection,'temporal_sql_sha256':P.sha(folder/'temporal.sql'),
        'context_sql_sha256':P.sha(folder/'context.sql')}
    G.dump(manifest,folder/'manifest.json')
    return {'batches':len(batches),'endpoints':manifest['requested'],'cards':len(selection['cards']),
            'manifest_sha256':P.sha(folder/'manifest.json'),'temporal_sql_bytes':(folder/'temporal.sql').stat().st_size}


def temporal_report(manifest,rows):
    expected={b['batch_id']:b for b in manifest['batches']};seen=set();counts=Counter();accounts=defaultdict(Counter)
    times=[];created=[]
    for r in rows:
        bid=r['batch_id']
        if bid in seen or bid not in expected:raise ValueError('Duplicate/unexpected audit batch')
        b=expected[bid]
        if any(r[k]!=b[k] for k in ('account','requested','input_sha256')):raise ValueError('Audit inputs do not match manifest')
        if set(r['counts'])-set(CLASSES) or sum(r['counts'].values())!=b['requested']:raise ValueError('Invalid audit partition')
        if any(not isinstance(v,int) or v<0 for v in r['counts'].values()):raise ValueError('Invalid audit counts')
        seen.add(bid);counts.update(r['counts']);accounts[r['account']].update(r['counts']);times.append(r['query_time'])
        created.extend(r[k] for k in ('min_exact_created_at','max_exact_created_at') if r.get(k))
    missing=sorted(set(expected)-seen)
    all_before=bool(manifest['requested'] and not missing and counts['exact_before_fit_cutoff']==manifest['requested'])
    return {'requested':manifest['requested'],'audited':sum(counts.values()),'accounts_in_manifest':manifest['accounts'],
        'completed_batches':len(seen),'missing_batches':missing,'counts':dict(counts),
        'accounts':{a:dict(c) for a,c in accounts.items()},'selected_rows_before_cutoff_gate':all_before,
        'full_historical_replay_verified':False,'analyzer_commit_visibility_verified':False,
        'query_time_range':[min(times,key=T.dt),max(times,key=T.dt)] if times else None,
        'exact_created_at_range':[min(created,key=T.dt),max(created,key=T.dt)] if created else None}


def compact_window(w):return {k:v for k,v in w.items() if k!='rows'}


def window_cycle(root,worlds=600):
    posts,cohort=load_panel(root);prepared,_=I.prepare(posts);real={}
    accounts=[c['id'] for c in cohort]
    for length in LENGTHS:
        values=W.extract(prepared,I.END-timedelta(days=length),I.END,accounts,source_verified=True)
        real[str(length)]={'accounts':{a:compact_window(w)|{'case_name':T.CASES.get(a)} for a,w in values.items()},
            'eligible':sum(w['eligible'] for w in values.values()),
            'repeated_and_eligible':sum(w['eligible'] and w['minimum_growth_days']>=2 for w in values.values()),
            'support_classes':dict(Counter(w['support'] if w['eligible'] else 'ineligible' for w in values.values()))}
    origin=T.dt('2026-08-31T00:00:00+03:00');end=origin+timedelta(days=30)
    collected=defaultdict(list);violations=Counter()
    for w in range(worlds):
        base=P.ordinary_world(rng(66,w,1))
        uniform=rng(66,w,3).random((31,P.NPOSTS));phase=rng(66,w,4).integers(0,3,P.NPOSTS)
        for family in ('baseline','small_daily30'):
            one=G.alter(base,0,family,rng(66,w,2))
            for mask in W.MASKS:
                p,truth=I.paths(one,origin,mask,uniform,phase)
                prepared,_=I.prepare(p);previous=None
                for length in LENGTHS:
                    start=end-timedelta(days=length)
                    v=W.extract(prepared,start,end,source_verified=True)['target']
                    actual=[t for t in truth if start<=t['at']<end]
                    true_days=len({t['at'].date() for t in actual});true_r=sum(t['dr'] for t in actual)
                    if v['minimum_growth_days']>true_days:violations['days_above_truth']+=1
                    if v['net_r']>true_r:violations['net_r_above_truth']+=1
                    if previous and (v['net_r']<previous['net_r'] or v['minimum_growth_days']<previous['minimum_growth_days']):
                        violations['larger_window_reduces_bound']+=1
                    previous=v
                    collected[family,mask,length].append({'eligible':v['eligible'],'repeated':v['minimum_growth_days']>=2,
                        'days':v['minimum_growth_days'],'net_r':v['net_r'],'true_days':true_days,'true_r':true_r,
                        'unknown':v['intervals']==0,'coverage':v['coverage']})
        if (w+1)%100==0:print(json.dumps({'H66_worlds':w+1}),flush=True)
    records=[];paired=[]
    for (family,mask,length),rows in collected.items():
        sums={k:sum(r[k] for r in rows) for k in ('eligible','days','net_r','true_days','true_r','unknown')}
        records.append({'family':family,'mask':mask,'length':length,'worlds':worlds,**sums,
            'repeated_and_eligible':sum(r['eligible'] and r['repeated'] for r in rows),
            'net_retention_vs_truth':sums['net_r']/sums['true_r'] if sums['true_r'] else None,
            'day_retention_vs_truth':sums['days']/sums['true_days'] if sums['true_days'] else None})
    for family in ('baseline','small_daily30'):
        for mask in W.MASKS:
            a=collected[family,mask,7];b=collected[family,mask,14]
            pairs=[(x,y) for x,y in zip(a,b) if x['eligible'] and y['eligible']]
            paired.append({'family':family,'mask':mask,'common_eligible':len(pairs),
                'repeated7':sum(x['repeated'] for x,y in pairs),'repeated14':sum(y['repeated'] for x,y in pairs)})
    return {'real':real,'simulation':{'worlds':worlds,'records':records,'paired_common_support':paired,
        'invariant_violations':dict(violations),'measurement_gate_pass':not violations},
        'two_window_calendar_days':{str(n):2*n for n in LENGTHS},'new_detector_validated':False}


def prepare_review(selection,raw):
    by_post={}
    selected={c['post'] for c in selection['cards']}
    for r in raw:
        k=r['requested_post']
        if k in by_post or k not in selected:raise ValueError('Duplicate/unexpected context row')
        by_post[k]=r
    cards=[]
    for c in selection['cards']:
        r=by_post.get(c['post']);url=None;status='missing_metadata'
        if r:
            if r.get('post')!=c['post'] or r.get('account')!=c['account']:status='identity_mismatch'
            elif not r.get('public_url'):status='missing_url'
            else:
                parsed=urlparse(r['public_url'])
                if parsed.scheme!='https' or parsed.hostname not in ('max.ru','web.max.ru') or parsed.username or parsed.password:
                    status='unverified_url'
                else:url=r['public_url'];status='catalog_url_not_fetched'
        cards.append({'card_id':c['card_id'],'published_at':c['published_at'],'type':c['type'],'public_url':url,
            'status':status,'reviewer1':None,'reviewer2':None,'adjudication':None})
    return {'cards':cards,'status_counts':dict(Counter(c['status'] for c in cards)),
        'independent_reviews_completed':0,'reviewers_contacted':False,'campaigns_confirmed':None,
        'retrospective_not_accuracy_validation':True}


def render_packet(review):
    text=['# B02: независимый разбор внешнего контекста MAX','',
        'Передавайте ревьюерам только этот файл. Оценки алгоритма и ключ отбора находятся у организатора.',
        'URL и содержание могут раскрывать вуз; пакет скрывает только алгоритмический исход.',
        'Ссылки взяты из каталога, доступность и содержание ещё не проверены. Это ретроспективный пакет, не контроль точности.','',
        'Два ревьюера заполняют отдельные копии независимо; третий разбирает разногласия. Поля ниже пока пустые.',
        'Сначала проверьте страницу и дату. Затем ищите прямые свидетельства рассылки, рекламы, репоста, инфоповода или призыва реагировать.',
        'Для каждого подтверждения укажите ссылку, дату источника/проверки и связь с постом. Недоступность страницы или отсутствие найденного источника означает unknown.',
        'Подтверждённая кампания не доказывает происхождение всех реакций; тема поста сама по себе не подтверждает кампанию.','',
        'Псевдоним ревьюера: ______. Дата проверки: ______.','']
    for c in review['cards']:
        url=f"[Публичная публикация]({c['public_url']})" if c['public_url'] else 'URL не подтверждён — unknown'
        text.extend([f"## {c['card_id']}",'',f"{url}. Дата по архивному каталогу: {c['published_at']}. Тип: {c['type']}.",'',
            '- Доступность страницы и соответствие посту: ______',
            '- Наблюдаемый контекст/кампания: confirmed / possible / unknown — ______',
            '- Тип: рассылка / реклама / репост / инфоповод / призыв реагировать / неизвестно — ______',
            '- Источник, дата публикации и дата проверки: ______',
            '- Связь источника с этим постом и ограничения: ______',''])
    return '\n'.join(text)


def read_jsonl(path):return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[3])
    ap.add_argument('--mode',choices=('prepare','audit','windows','review'),required=True)
    ap.add_argument('--folder',type=Path)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.mode!='windows' and not args.folder:ap.error('--folder required')
    if args.folder and args.output.resolve() in {(args.folder/n).resolve() for n in ('manifest.json','temporal.sql','context.sql','temporal.jsonl','context.jsonl')}:
        ap.error('Derived output must not overwrite an input')
    out={'provenance':provenance(args.root),'mode':args.mode}
    if args.mode=='prepare':out['prepare']=prepare_queries(args.root,args.folder)
    elif args.mode=='windows':out['windows']=window_cycle(args.root)
    else:
        manifest=json.loads((args.folder/'manifest.json').read_text())
        if args.mode=='audit':out['audit']=temporal_report(manifest,read_jsonl(args.folder/'temporal.jsonl'))
        else:
            out['review']=prepare_review(manifest['selection'],read_jsonl(args.folder/'context.jsonl'))
            args.output.with_suffix('.md').write_text(render_packet(out['review']))
        out['input_sha256']={n:P.sha(args.folder/n) for n in ('manifest.json','temporal.jsonl') if (args.folder/n).exists()}
        if args.mode=='review':out['input_sha256']['context.jsonl']=P.sha(args.folder/'context.jsonl')
    G.dump(out,args.output);print(json.dumps({'mode':args.mode,'output':str(args.output),'sha256':P.sha(args.output)}),flush=True)


if __name__=='__main__':main()
