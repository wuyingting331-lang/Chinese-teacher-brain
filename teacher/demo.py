from teacher.models import Essay, Record, Report, ParagraphTeaching, ExpressionTip


def demo_record():
    essay = Essay(title='一次合作', body='放学后，我和小明留下来布置课室。\n我扶着椅子，小明把彩纸贴在墙上。纸掉了下来，我们重新贴好。\n看着整齐的课室，我们笑了。我明白了合作的重要。')
    ids = list(essay.paragraphs)
    def ev(i):
        return dict(paragraph_id=ids[i], quote=essay.paragraphs[ids[i]])
    def j(text, i=0):
        return dict(text=text, evidence=[ev(i)])
    strength = j('人物和任务交代清楚。')
    problem = j('彩纸掉落后的合作过程较简略。', 1)
    overview = dict(level=j('叙事基本清楚，关键过程尚可发展。', 1), score=27, subscores=[],
                    content=j('任务、困难与结果完整，但解决困难的过程简略。', 1),
                    expression=j('动作表达自然，结尾感悟较概括。', 2),
                    comment='任务、合作动作与结果交代清楚。彩纸掉落后怎样调整配合写得简略，结尾感悟仍较笼统。下一稿先写清解决困难的过程，再让结尾回应实际行动。',
                    strengths=[strength, j('有具体合作动作。', 1),j('用看到成果后的笑容收束故事。',2)], problems=[problem, j('感悟比较笼统。', 2)],
                    higher_level_gap=problem)
    data = dict(essay_version=essay.version, overview=overview,
                structure=[dict(role='起因', evidence=[ev(0)], effect='任务清楚。', action='保留简洁开头。'),
                           dict(role='事件困难与合作关键', evidence=[ev(1)], effect='掉落是事件高点，配合的变化尚未展开。', action='补写两人如何调整配合。'),
                           dict(role='结果与感悟', evidence=[ev(2)], effect='有结果，感悟概括。', action='联系扶椅子和贴纸的动作写体会。')],
                paragraphs=[dict(paragraph_id=pid, strength=['开头清楚。','动作具体。','结局完整。'][i],
                                 problem=['没有明显错误，可保留。','重新贴好的过程较简略。','感悟未联系行动。'][i],
                                 advice=['保持简洁。','在重新贴好前交代两人怎样配合。','联系这次配合写一句具体体会。'][i],
                                 example=['放学后，我和小明留下来布置课室。','我稳稳地扶住椅子，小明把彩纸重新贴好。','看着整齐的课室，我想：有了彼此配合，事情就顺利多了。'][i])
                            for i, pid in enumerate(ids)],
                language=[dict(evidence=dict(paragraph_id=ids[2], quote='我明白了合作的重要。'), kind='可选优化',
                               category='可优化但并非错误', replacement='我体会到，两个人互相配合，事情就顺利多了。',
                               reason='联系具体经历，原句没有语法错误。', start=None)],
                expressions=[dict(expression=x, location=ev(1), reason='让配合动作更清楚，按实际经过选用。',
                                  example=y, source='教学建议（新拟示例）') for x, y in [
                                      ('稳稳地','我稳稳地扶住椅子。'), ('重新','我们把彩纸重新贴好。'),
                                      ('一边……一边……','我一边扶着椅子，一边留意小明的动作。'),
                                      ('互相配合','我们互相配合，把彩纸贴好。'), ('终于','彩纸终于贴好了，我们笑了。')]],
                content_summary=dict(strength=strength, weakness=problem),
                expression_summary=dict(strength=j('动作词清楚。',1), weakness=j('结尾表达可更具体。',2)),
                tasks=[dict(location=ev(i), problem=p, action=a, done=d) for i,p,a,d in [
                    (1,'过程简略','在重新贴好前补写两人怎样调整动作。','读者能看懂两人的配合。'),
                    (2,'感悟概括','联系扶椅子、贴纸的行动改写感悟。','感悟能找到前文依据。'),
                    (1,'转折衔接短','在掉落与贴好之间写清动作次序。','困难和解决之间没有跳跃。')]])
    report=Report.model_validate(data)
    report.structure_overview='开头的任务交代可以保留简洁，篇幅应集中在彩纸掉落后的合作过程。结尾已有结果与感悟，但应让感悟回应具体的配合动作，不另加新事件。'
    for s,pid,problem,actions,arrangement in zip(report.structure,ids,
        ['任务交代清楚，无需增加环境或背景。','困难与解决之间一笔带过，两人怎样调整配合尚不清楚。','感悟较概括，与实际合作动作衔接不足。'],
        [['保留'],['扩写','补过渡'],['保留','补过渡']],
        ['保留放学后留下布置课室的任务交代，让开头尽快进入合作过程。',
         '在纸掉落与重新贴好之间补两人调整配合的过程，突出困难如何解决，不扩写无关背景。',
         '保留成果与笑容，将最后的感悟联系扶稳椅子和调整彩纸的配合，不添加未来事件。']):
        s.paragraph_ids=[pid]
        s.problem=problem
        s.adjustments=actions
        s.arrangement=arrangement
    report.expressions.append(ExpressionTip(expression='看着整齐的课室，我们笑了。',location=ev(2),
        reason='把劳动成果与两人的反应连在一起，自然表达合作后的喜悦，值得保留。',
        example='看着整齐的课室，我们笑了。',source='原文已有',example_source='原文引用'))
    for tip in report.expressions[:-1]:
        tip.example_source='教学新拟'
    teaching=[
        dict(role='交代时间、人物与合作任务。',issues=[],reorder=[],develop=[],expressions=[],
             example_scope='保留原段',invented_details=[],why_better='任务交代已经清楚，保留简洁开头，把篇幅留给合作过程。'),
        dict(role='呈现困难及两人怎样配合解决，是本文应展开的重点。',
             issues=[dict(category='情节与因果',detail='“重新贴好”跳过调整动作的过程，读者看不清配合怎样奏效。')],reorder=[],
             develop=[dict(location='“纸掉了下来”之后、“我们重新贴好”之前',
                           action='补写我扶稳椅子、小明调整彩纸位置并按住边角的动作，再写贴好；这些是可调整的新拟局部细节。',
                           reason='让读者看清两人的分工与问题解决的联系。')],
             expressions=[dict(expression='稳稳地',placement='“我扶着椅子”处',sentence='我稳稳地扶住椅子，让小明重新调整彩纸的位置。',effect='具体说明我怎样帮助同伴。')],
             example_scope='完整示范段',invented_details=['调整彩纸位置、按住边角为人工新拟的具体化细节。'],
             why_better='困难后有调整动作，合作就有了可见的过程，结尾的体会也有依据。'),
        dict(role='收束合作结果并点出体会。',
             issues=[dict(category='详略与衔接',detail='已有反思意图，但“合作的重要”没有联系刚才的具体配合。')],reorder=[],
             develop=[dict(location='“我明白了合作的重要”处',action='把笼统感悟换成两人分工、互相配合才把彩纸贴好的体会，不添加新的未来事件。',reason='使感悟回应故事中的实际行动。')],
             expressions=[],example_scope='几句过渡示范',invented_details=[],why_better='感悟与前文配合照应，读者能理解这次经历带来的认识。')]
    for p,t in zip(report.paragraphs,teaching):
        p.teaching=ParagraphTeaching.model_validate(t)
    report.paragraphs[1].example='纸掉了下来。我稳稳地扶住椅子，小明重新调整彩纸的位置，再把边角按紧。这一次，彩纸贴牢了，我们才松了一口气。'
    report.paragraphs[1].example_kind='保留原意的完整示范（含新拟细节）'
    report.paragraphs[1].teaching.is_key=True
    for task,example,focus in zip(report.tasks,
            ['我扶稳椅子，小明重新调整彩纸的位置。','有了彼此配合，我们才把彩纸贴好。','纸掉下来后，我们先调整位置，再按紧边角。'],
            ['内容发展','结构与衔接','内容发展']):
        task.example=example
        task.focus=focus
    titles=['补清重新贴彩纸的配合过程','让结尾感悟回应合作动作','通读人物动作，检查主语和指代是否清楚']
    for task,title in zip(report.tasks,titles):
        task.title=title
        task.paragraph_ids=[task.location.paragraph_id]
        review=next(p for p in report.paragraphs if p.paragraph_id==task.location.paragraph_id)
        review.teaching.success_checks.append(task.done)
    report.tasks[2].focus='语言规范'
    for p in report.paragraphs:
        p.example_paragraphs=[p.example]
        p.example=''
    return Record(essay=essay, report=report, demo=True, model_name='离线固定演示')
