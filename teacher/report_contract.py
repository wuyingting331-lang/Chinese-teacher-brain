"""Versioned data-flow contract, independent of scoring policy and teaching fields."""
SCHEMA_VERSION='report-v7-flow-recovery'
RETIRED={'content_summary','expression_summary'}
ACTIVE=('overview','structure','structure_overview','paragraphs','language','expressions','tasks','picture_alignment')
REQUIRED=('overview','structure','structure_overview','paragraphs','language','expressions','tasks')


def counts(values,essay):
    present={p.paragraph_id for p in values.get('paragraphs',[]) if hasattr(p,'paragraph_id')}
    if not present:
        present={p.get('paragraph_id') for p in values.get('paragraphs',[]) if isinstance(p,dict)}
    return {'paragraphs':len(present.intersection(essay.paragraphs)),
            'expected_paragraphs':len(essay.paragraphs),
            'missing_paragraph_ids':[p for p in essay.paragraphs if p not in present],
            **{s:len(values.get(s,[])) for s in ('structure','language','expressions','tasks')},
            'structure_overview':bool(values.get('structure_overview'))}


def health(values,unfinished,essay):
    data=counts(values,essay)
    unfinished=set(unfinished)-RETIRED
    labels={'overview':'得分与整体评价','structure':'故事结构建议','structure_overview':'全篇布局判断',
            'language':'语言修改','expressions':'词句提升','tasks':'二稿清单','picture_alignment':'图意核对'}
    messages=[]
    if data['missing_paragraph_ids']:
        messages.append(f'逐段指导：已验证{data["paragraphs"]}/{data["expected_paragraphs"]}段，缺少'+
                        '、'.join(data['missing_paragraph_ids'])+f'（{len(data["missing_paragraph_ids"])}段）。')
    missing={s for s in REQUIRED if s not in values}
    if not values.get('overview'):
        missing.add('overview')
    if not values.get('structure'):
        missing.add('structure')
    if not values.get('structure_overview'):
        missing.add('structure_overview')
    if len(values.get('tasks',[]))<3:
        missing.add('tasks')
    for name in ACTIVE:
        if name=='paragraphs':
            continue
        if name in missing:
            messages.append(labels[name]+'尚无完整有效内容。')
        elif name in unfinished:
            messages.append(labels[name]+'仍有未通过校验的条目；有效内容已保留。')
    return dict(data,complete=not missing and not unfinished and not data['missing_paragraph_ids'],messages=messages)
