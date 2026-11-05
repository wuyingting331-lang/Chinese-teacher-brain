"""Human-written synthetic story and guidance, not the student's confirmed original or API output."""
from teacher.config import load_scoring
from teacher.models import Essay,Record,Report,Overview,Judgment,Evidence,ParagraphReview,ParagraphTeaching,Task,LanguageEdit,ExpressionTip
from teaching_sample import sibling_structure,p004_review


def hierarchy_record():
    essay=Essay(title='信息层次人工验收样例（原稿为合成文本）',body='\n'.join([
        '我平时大大咧咧，做事马马虎虎。别人劝我，我总找借口不听。这次我得到了教训。',
        '妈妈让我照顾妹妹，我随口答应。妈妈离开后，我玩起了游戏。',
        '妹妹来找我，我嫌她烦，就推了他一下。她哭了，我把耳机带上，继续玩游。',
        '有人敲门，我喊真烦我买东西。我开门看见警察。警察提醒我去找妹妹。我找到妹妹后警察离开了。我替她换尿布时发现大腿有红疹，我顿时自责极了。我关掉电脑陪着她。',
        '妈妈回家后夸我照顾好了妹妹。我没有告诉妈妈发生的事。',
        '我明白了，我要改掉不负责任的习惯，以后做一个。']))
    def j(text,pid,quote):
        return Judgment(text=text,evidence=[Evidence(paragraph_id=pid,quote=quote)])
    overview=Overview(score=28,subscores=[dict(name='内容',score=14),dict(name='表达',score=14)],
        comment='你交代了照顾妹妹的任务，也写出忽略她、受到提醒和采取补救的经过，故事基本完整。不过，主要事件集中在一个长段，担忧与自责产生得较快；开头性格介绍重复，结尾句意未完成。下一稿先理清寻找与照顾的顺序，再让人物变化有具体触发和行动，同时集中处理指代、用字与残句。',
        content=j('基本事件完整，关键转折和人物变化还需发展。','P004','我关掉电脑陪着她'),
        expression=j('叙事能理解，但局部表达与残句影响清晰度。','P003','继续玩游'),
        strengths=[j('责任交代与基本事件完整。','P002','妈妈让我照顾妹妹'),j('已经写出照顾妹妹的补救行动。','P004','我关掉电脑陪着她')])
    specs=[
        ('P001','介绍平时态度并引入教训。','性格铺垫与教训引入可以保留。','性格介绍重复。','详略与衔接',
         '按平时态度、不听劝告、这次教训重组；合并重复的马虎和找借口介绍，让开头尽快进入事件。',
         '我平时做事马虎，别人劝我时，我总找借口敷衍。直到这次照顾妹妹的经历，我才知道这样做会给别人添麻烦。',[]),
        ('P002','交代责任和转向游戏的起因。','已有随口答应，敷衍的态度已经写出。','已有顺序可保留，敷衍可用少量动作具体化。','人物描写',
         '保持妈妈交代、我答应、妈妈离开、我玩游戏的顺序；在答应处用一个动作具体化，不增加环境描写。',
         '妈妈让我照顾妹妹，我头也不抬，随口答应。妈妈刚离开，我就转身玩起了游戏。',['头也不抬是新拟的具体化细节。']),
        ('P003','呈现主动逃避怎样加重。','求助、嫌烦、推开及戴耳机的基本过程值得保留。','推开后妹妹的反应与主动不理会之间缺少连接。','情节与因果',
         '在推开妹妹之后补她哭得更响的反应，再写我不愿理会、索性戴耳机；把明确字词错误另列语言表。',
         '妹妹来找我，我不耐烦地推了她一下。她哭得更响了，我却懒得理会，索性戴上耳机，继续玩游戏。',['哭得更响和懒得理会是新拟的反应与心理细节。']),
        ('P005','写妈妈夸奖与我内心事实的反差。','没有告诉妈妈的原结局应保留。','反差主要靠读者推想，羞愧可更具体。','人物描写',
         '在妈妈夸奖之后补低头、避开目光及想起妹妹哭泣的一点反应；不把主动坦白写入保留原意版。',
         '妈妈夸我照顾好了妹妹，我低下头，不敢看她。刚才妹妹哭泣的样子又浮现在我眼前。我没有告诉妈妈发生的事。',['低头、避开目光和回想哭泣是新拟细节。']),
        ('P006','用此次经历中的认识收束。','有反思意图，但还未表达完整。','句意残缺，性格决心又与开头重复。','语序与表达',
         '补全残句，将泛泛性格决心换为答应别人后应认真履行的认识，回应照顾妹妹这件事。',
         '这次经历让我明白，答应别人的事，就应该认真做好，不能只顾自己。',[])]
    reviews={}
    reasons={
        'P001':'压缩重复性格介绍，让读者更快进入造成教训的事件。',
        'P002':'动作具体化已有的随口答应，既交代责任，也不抢走高潮的篇幅。',
        'P003':'让妹妹的反应接上主动不理会的选择，呈现逃避逐步加重。',
        'P005':'低头和回想使夸奖与羞愧形成可见反差，仍保留未坦白的结局。',
        'P006':'补全句意，并让认识回到答应照顾妹妹却没有认真履行的经历。'}
    for pid,role,strength,problem,category,action,example,details in specs:
        move=dict(location='本段对应事件处',action=action,reason=reasons[pid])
        t=ParagraphTeaching(role=role,issues=[dict(category=category,detail=problem)],
            reorder=[move] if pid in ('P001','P006') else [],develop=[move] if pid not in ('P001','P006') else [],
            expressions=[],example_scope='完整示范段',invented_details=details,
            why_better=reasons[pid])
        reviews[pid]=ParagraphReview(paragraph_id=pid,strength=strength,teaching=t,example_paragraphs=[example])
    reviews['P004']=p004_review()
    reviews['P004'].problem=''
    reviews['P004'].advice=''
    reviews['P004'].teaching.uncertainties=['原稿喊话“真烦我买东西”含混，具体意思待确认；示范避开该句，没有改成购买询问。']
    layout,structure=sibling_structure()
    tasks=[Task(title=title,paragraph_ids=ids,focus=focus) for title,ids,focus in [
        ('理清转折顺序，发展担忧、自责和照顾',['P004'],'内容发展'),
        ('补出妹妹反应与主动不理会的连接',['P003'],'内容发展'),
        ('强化妈妈夸奖与内心羞愧的反差',['P005'],'人物变化'),
        ('压缩开头，补全并收紧结尾认识',['P001','P006'],'结构与衔接'),
        ('集中核对指代、用字、残句和标点',['P003','P006'],'语言规范')]]
    language=[LanguageEdit(evidence=dict(paragraph_id='P003',quote=q),kind='明确错误',category=c,
        replacement=r,reason=reason,start=None) for q,r,c,reason in [
            ('推了他一下','推了她一下','指代错误','此处指妹妹，用“她”。'),
            ('把耳机带上','把耳机戴上','错别字','佩戴耳机用“戴”。'),
            ('玩游','玩游戏','表达残缺','补全词语，不把明确残缺标作可选优化。')]]
    expressions=[ExpressionTip(expression=x,location=dict(paragraph_id=pid,quote=q),reason=reason,
        example='',source='教学建议（新拟示例）',example_source='教学新拟',used_in_paragraph_id=pid)
        for x,pid,q,reason in [('索性','P003','我把耳机带上','明确主动不理会的选择。'),
            ('心里一紧','P004','我找到妹妹','让看到妹妹接上担心与照顾。')]]
    report=Report(essay_version=essay.version,overview=overview,structure_overview=layout,structure=structure,
        paragraphs=[reviews[pid] for pid in essay.paragraphs],language=language,expressions=expressions,tasks=tasks)
    return Record(essay=essay,config=load_scoring(),report=report,demo=True,
        model_name='人工合成样例；28分仅用于布局测试，不是学生评分',target_score=36)
