"""Human-written anonymous regression fixture, not a model result or real student text."""
from teacher.models import ParagraphReview


def sibling_structure():
    """Human layout example based on the user's directions, not a universal template."""
    from teacher.models import Structure
    overview='开头的性格介绍有重复，主要事件却集中在P004，详略重心需要调整。压缩开头与起因，把寻找妹妹、发现红疹后的自责和照顾写具体；结尾让夸奖反差与事件认识各有作用，避免重复决心。'
    rows=[
        dict(paragraph_ids=['P001'],role='开头与性格铺垫',problem='大大咧咧、马马虎虎、不听劝告、找借口的介绍意思重叠。',adjustments=['压缩'],
             arrangement='合并重复介绍，只留性格、敷衍习惯和教训引入，尽快进入照顾妹妹的事件。'),
        dict(paragraph_ids=['P002'],role='起因与责任交代',problem='交代任务已经清楚，无需另加无关背景。',adjustments=['保留'],
             arrangement='略写妈妈交代、我随口答应、妈妈离开后转向游戏，给冲突与高潮留出篇幅。'),
        dict(paragraph_ids=['P003'],role='冲突发展',problem='从推开妹妹到戴耳机的反应和选择过快。',adjustments=['扩写','补过渡'],
             arrangement='在推开妹妹与戴耳机之间，补一个妹妹的反应及我主动不理会的选择，让逃避如何逐步加重变得清楚。'),
        dict(paragraph_ids=['P004'],role='转折与高潮',problem='警察提醒、寻找、照顾和自责挤在一个长段，事件多而人物变化展开不足。',adjustments=['拆段','扩写'],
             arrangement='推荐分三段：敲门至警察提醒后担心；从呼喊寻找至找到妹妹、警察离开；从换尿布时发现大腿红疹至自责、关电脑陪伴。分别在开始寻找前、换尿布前断段。警察上门与交代来意略写，寻找时的担忧、照顾时的回想详写；让烦躁、担心、自责的变化有清楚层次，避免事件挤在一段，不增加事故。'),
        dict(paragraph_ids=['P005','P006'],role='结果与认识',problem='夸奖后的反差不够具体，感悟残缺且容易重复性格决心。',adjustments=['保留','压缩'],
             arrangement='推荐保留两段：P005写妈妈夸奖与我羞愧的反差；P006补全句意，用联系本次经历的一句认识收束，删去重复决心，让结果与认识各有作用。若两段仍在重复同一感悟，可合成先反差后认识的一段；不强制坦白，不改变原结局。')]
    return overview,[Structure.model_validate(x) for x in rows]


def p004_review():
    return ParagraphReview(
        paragraph_id='P004',
        strength='敲门、发现警察、寻找妹妹及照顾妹妹构成了完整转折；换尿布、关电脑和陪伴都是已经写出的补救，应保留。',
        problem='事件集中在一个长段，寻找前的联想及照顾时的自责跳得较快。',
        advice='按敲门、寻找、照顾拆成三段，略写警察交代，具体化担忧与自责。',
        example_kind='保留原意的完整示范（含新拟细节）',
        example_paragraphs=['敲门声打断了游戏。我摘下耳机，有些烦躁地走去开门。看见门外的警察，我一下子慌了。警察问起妹妹，我才发觉，好一会儿没有听见她的哭声了。妹妹在哪里？我顿时担心起来。',
                 '我连忙回头喊：“妹妹！”没有听见回答，我加快脚步去找她。看到她脸上的泪痕，我心里一紧，赶紧走过去抱起她。刚才我只顾着游戏，竟把她的哭声挡在耳机外。找到妹妹后，警察离开了。',
                 '我替妹妹换尿布时，才看见她大腿上有红疹，手上的动作不由得放轻了。我想起自己先前嫌她烦，还把她推开，心里很不是滋味。我关掉电脑，留在妹妹身边陪着她。妈妈交给我的事，我答应了，就应该认真做好。'],
        teaching=dict(
            role='承担转折与高潮，呈现“我”从烦躁到慌张、担忧，再到自责和补救的变化。',
            issues=[dict(category='详略与衔接',detail='敲门、警察、寻找和照顾挤在一起，几个转折缺少连接。'),
                    dict(category='人物描写',detail='已有补救行动，但还可写清看到妹妹后，什么使“我”回想先前的逃避。')],
            reorder=[dict(location='从敲门到关电脑陪伴的整个长段',
                          action='拆成三段：A敲门到看见警察、因提醒而担心；B找到妹妹、警察离开；C换尿布时才看到大腿红疹、自责并关电脑陪伴。警察交代略写，把寻找与照顾留作重点。',
                          reason='先交代外部打断，再写对妹妹的担心，最后写补救，读者才能跟上人物变化。')],
            develop=[dict(location='警察简短交代之后、寻找妹妹之前',
                          action='警察提醒后，补写注意到哭声停了、担心妹妹，呼喊并加快脚步寻找。摘耳机与呼喊属于新拟衔接细节；找到妹妹后再交代警察离开。',
                          reason='让警察上门自然引出对妹妹的担忧，而不是突然跳到换尿布。'),
                     dict(location='看到妹妹、替她换尿布时',
                          action='用脸上泪痕引发对先前推开她、隔绝哭声的回想；警察离开后换尿布，这时才发现大腿红疹、动作放轻，再接原文已有的关电脑、陪伴。不判断红疹病因。',
                          reason='让自责从眼前所见产生，并落实到原文已有的行动。')],
            expressions=[dict(expression='心里一紧',placement='找到妹妹、看到泪痕后',
                              sentence='看到她脸上的泪痕，我心里一紧，赶紧走过去抱起她。',effect='把担忧与接下来的照顾动作接起来，不堆砌成语。')],
            example_scope='拆成2—3段的完整示范',
            is_key=True,
            invented_details=['摘耳机、呼喊、加快脚步、抱起妹妹及动作放轻是人工新拟的具体化细节。',
                              '脸上泪痕与相应内心话是新拟示范；若实际原文或图意不支持，应调整或删去。'],
            why_better='三段分别承接外部打断、担忧与补救，使情绪变化有原因。警察部分简洁，重点落在寻找和照顾，保留了原故事的补救行动。'))
