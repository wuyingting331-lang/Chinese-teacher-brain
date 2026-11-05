"""Reference-based presentation shared by screen and export; no generated summaries here."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import re


REPORT_ORDER=('overview','structure','paragraphs','language','expressions','checklist')


def example_paragraphs(review):
    if review.example_paragraphs:
        return list(review.example_paragraphs)
    # Adapt only explicit historical line breaks; never invent split positions.
    return [s.strip() for s in re.split(r'\r\n|\r|\n',review.example) if s.strip()]


def example_text(review):
    return '\n\n'.join(example_paragraphs(review))


def paragraph_notices(review):
    if review.teaching and review.teaching.example_scope=='拆成2—3段的完整示范' and len(example_paragraphs(review)) not in (2,3):
        return ['历史记录标注“拆成2—3段”，但没有保存对应分段；现有示范原样展示，分段仍待核对。']
    return []


def first_sentence(text):
    return re.split(r'(?<=[。！？])|[\r\n]+',text.strip(),maxsplit=1)[0]


@dataclass(frozen=True)
class TaskView:
    number: int
    title: str
    paragraph_ids: tuple[str,...]


def tasks_view(tasks,numbers=None):
    numbers=numbers or list(range(1,len(tasks)+1))
    return [TaskView(n,t.title or first_sentence(t.action) or first_sentence(t.problem),
                     tuple(t.paragraph_ids or ([t.location.paragraph_id] if t.location else [])))
            for n,t in zip(numbers,tasks)]


def structure_row(item):
    ids=item.paragraph_ids or list(dict.fromkeys(e.paragraph_id for e in item.evidence))
    return ('、'.join(ids)+' · '+item.role,
            item.problem or ('原有评语：'+item.effect if item.effect else '旧记录未单列结构问题'),
            '、'.join(item.adjustments) or '旧记录未分类',
            item.arrangement or item.action or '旧记录未提供具体安排')


def _edits_key(edit,paragraph):
    quote=edit.evidence.quote
    start=edit.start
    if start is None or start<0 or paragraph[start:start+len(quote)]!=quote:
        matches=[m.start() for m in re.finditer(re.escape(quote),paragraph)]
        if len(matches)!=1:
            return None
        start=matches[0]
    atoms=tuple((start+a,start+b,quote[a:b],edit.replacement[c:d])
        for tag,a,b,c,d in SequenceMatcher(None,quote,edit.replacement,autojunk=False).get_opcodes() if tag!='equal')
    return (edit.evidence.paragraph_id,atoms) if atoms else None


def language_view(edits,paragraphs,numbers=None):
    """Same exact character correction -> shortest evidence; no semantic similarity deletion."""
    numbers=numbers or list(range(1,len(edits)+1))
    groups={}
    classifications={}
    order=[]
    for number,edit in zip(numbers,edits):
        key=_edits_key(edit,paragraphs.get(edit.evidence.paragraph_id,''))
        if key is None:
            key=('unlocated',edit.evidence.paragraph_id,edit.evidence.quote,edit.replacement,edit.kind,edit.category)
        if key not in groups:
            groups[key]=(number,edit)
            classifications[key]=set()
            order.append(key)
        elif len(edit.evidence.quote)<len(groups[key][1].evidence.quote):
            groups[key]=(number,edit)
        classifications[key].add(edit.kind+'／'+edit.category)
    result=[]
    for key in order:
        number,edit=groups[key]
        if len(classifications[key])>1:
            edit=edit.model_copy(update={'reason':'历史分类不一致，待核对（'+'；'.join(sorted(classifications[key]))+'）。'+edit.reason})
        result.append((number,edit))
    return result


def expression_reference(tip,reviews):
    if tip.used_in_paragraph_id:
        return tip.used_in_paragraph_id
    p=reviews.get(tip.location.paragraph_id)
    if p and (tip.expression in example_text(p) or tip.example in example_paragraphs(p)):
        return p.paragraph_id
    return None


def draft_display_blocks(record,reviews):
    """An optional full draft reuses exact whole paragraphs by reference, not similarity."""
    if not record.second_draft:
        return []
    anchors={}
    for pid,text in record.essay.paragraphs.items():
        anchors.setdefault(text,[]).append(pid+'原段')
    for review in reviews:
        for i,text in enumerate(example_paragraphs(review),1):
            if text!=record.essay.paragraphs.get(review.paragraph_id):
                anchors.setdefault(text,[]).append(review.paragraph_id+f'提升示范第{i}段')
    result=[]
    for text in re.split(r'\r\n|\r|\n',record.second_draft.body):
        if not text.strip():
            continue
        refs=anchors.get(text,[])
        result.append('沿用'+refs[0]+'，见逐段修改指导。' if len(refs)==1 else text)
    return result


def implementation_reference(record,item,reviews):
    for review in reviews:
        for i,text in enumerate(example_paragraphs(review),1):
            if item.draft_quote==text:
                return review.paragraph_id+f'提升示范第{i}段'
    if record.second_draft:
        blocks=[p for p in re.split(r'\r\n|\r|\n',record.second_draft.body) if p.strip()]
        for i,text in enumerate(blocks,1):
            if item.draft_quote==text:
                return f'示范二稿第{i}段'
    return None
