import io
import json
from copy import deepcopy
from unittest.mock import Mock
import pytest
from PIL import Image
from teacher.models import Essay, Evidence, Structure, Report, PictureReading, PictureAlignment
from teacher.demo import demo_record
from teacher.validation import resolve_evidence, evidence_errors, report_errors
from teacher.service import generate_report, GenerationFailure, serialized, payload
from teacher.images import ingest, model_bytes, image_version, confirmed, valid_confirmation, identify
from teacher.storage import save, load_all
from teacher.render import markdown_report


def png(color='white',size=(64,64),format='PNG'):
    out=io.BytesIO()
    Image.new('RGB',size,color).save(out,format=format)
    return out.getvalue()


def test_unique_exact_quote_wrong_paragraph():
    e=Essay(title='题',body='他走了。\n她留下来。\n我们笑了。')
    s=Structure(role='结果',summary='大家高兴',evidence=[Evidence(paragraph_id='P001',quote='我们笑了。')],effect='完整',action='保留')
    notes=resolve_evidence(s,e.paragraphs,'structure[0]')
    assert s.evidence[0].paragraph_id=='P003'
    assert 'P001 → P003' in notes[0]
    assert not evidence_errors(s,e.paragraphs)


def test_rewrite_not_quote_and_ambiguous_match():
    e=Essay(title='题',body='他笑了。\n他笑了。\n她走了。')
    for q in ['他微笑了。','他笑了']:
        ev=Evidence(paragraph_id='P003',quote=q)
        assert not resolve_evidence(ev,e.paragraphs)
        assert evidence_errors(ev,e.paragraphs)
    ev=Evidence(paragraph_id='P003',quote='他笑了。')
    assert not resolve_evidence(ev,e.paragraphs)
    assert ev.paragraph_id=='P003'
    assert evidence_errors(ev,e.paragraphs)


def test_windows_lines_and_multisegment_structure():
    a=Essay(title='题',body='\r\n  第一段。  \r\n\r\n第二段。\r\n   \r\n第三段。\r\n')
    b=Essay(title='题',body='\n  第一段。  \n\n第二段。\n   \n第三段。\n')
    assert a.paragraphs==b.paragraphs=={'P001':'  第一段。  ','P002':'第二段。','P003':'第三段。'}
    s=Structure(role='经过和结果',summary='从行动到结束',evidence=[Evidence(paragraph_id='P001',quote='第一段。'),Evidence(paragraph_id='P003',quote='第三段。')],effect='测试',action='保留')
    assert not evidence_errors(s,a.paragraphs)
    assert a.body.startswith('\r\n')


def test_local_repair_keeps_valid_sections_and_schema():
    r=demo_record()
    bad=deepcopy(r.report)
    bad.structure[0].evidence[0].quote='这不是原文'
    repaired={'essay_version':r.essay.version,'structure':[x.model_dump() for x in r.report.structure]}
    fake=Mock()
    fake.generate.side_effect=[bad,repaired]
    result=generate_report(fake,r.essay,r.config)
    assert result.overview==bad.overview
    schema,system,request=fake.generate.call_args_list[1].args
    data=json.loads(request)
    assert set(schema.model_fields)=={'essay_version','structure__0'}
    assert data['generate_only']==['structure__0']
    assert data['candidate_comparisons'][0]['candidate_quote']=='这不是原文'
    assert data['paragraphs']==r.essay.paragraphs
    assert data['repair_errors'][0]['path']=='structure[0].evidence[0]'


def test_still_failed_partial_save_download_and_retry(tmp_path):
    r=demo_record()
    bad=deepcopy(r.report)
    bad.structure[0].evidence[0].quote='改写句子'
    fake=Mock()
    fake.generate.return_value=bad
    with pytest.raises(GenerationFailure) as error:
        generate_report(fake,r.essay,r.config)
    r.report=None
    r.partial_sections=serialized(error.value.partial)
    r.incomplete_errors=error.value.errors
    assert len(r.partial_sections['structure'])==2 and 'overview' in r.partial_sections
    save(r,tmp_path)
    loaded,warnings=load_all(tmp_path)
    assert not warnings and loaded[0].partial_sections==r.partial_sections
    text=markdown_report(r)
    assert '不完整批改报告' in text and '未完成' in text and '改写句子' not in text
    retry=Mock()
    retry.generate.return_value={'essay_version':r.essay.version,'structure':demo_record().report.model_dump()['structure']}
    from teacher.report_flow import SchemaVersionMismatch
    with pytest.raises(SchemaVersionMismatch):
        generate_report(retry,r.essay,r.config,existing=r.partial_sections)
    assert generate_report(retry,r.essay,r.config,resume=error.value.state).structure
    assert retry.generate.call_count==1


def test_partial_preserved_if_repair_network_fails():
    r=demo_record()
    bad=deepcopy(r.report)
    bad.structure[0].evidence[0].quote='不存在'
    fake=Mock()
    fake.generate.side_effect=[bad,TimeoutError('private text')]
    with pytest.raises(GenerationFailure) as error:
        generate_report(fake,r.essay,r.config)
    assert 'overview' in error.value.partial
    assert 'private text' not in str(error.value)


def test_safe_log_has_path_id_request_not_essay(caplog):
    r=demo_record()
    bad=deepcopy(r.report)
    bad.structure[0].evidence[0].quote='不存在的隐私句子'
    fake=Mock(last_request_id='api-test')
    fake.generate.return_value=bad
    with caplog.at_level('WARNING'),pytest.raises(GenerationFailure):
        generate_report(fake,r.essay,r.config)
    assert 'structure[0].evidence[0]' in caplog.text and 'P001' in caplog.text and 'request_id=' in caplog.text
    assert '不存在的隐私句子' not in caplog.text and r.essay.body not in caplog.text


@pytest.mark.parametrize('data,name',[ (b'not an image','x.png'),(png(),'x.jpg'),(png(),'x.gif'),(b'x'*(10*1024*1024+1),'x.png'),(png(size=(10,64)),'x.png'),(png(size=(5000,4100)),'x.png')])
def test_invalid_images(data,name,tmp_path):
    with pytest.raises(ValueError):
        ingest(data,name,tmp_path)


@pytest.mark.parametrize('format,extension',[('PNG','png'),('JPEG','jpeg'),('WEBP','webp')])
def test_original_image_and_derivative(format,extension,tmp_path):
    data=png(format=format)
    p=ingest(data,'x.'+extension,tmp_path)
    assert (tmp_path/f'{p.digest}.{p.extension}').read_bytes()==data
    assert Image.open(io.BytesIO(model_bytes(p,tmp_path))).format=='JPEG'


def test_orientation(tmp_path):
    image=Image.new('RGB',(100,50))
    exif=image.getexif()
    exif[274]=6
    out=io.BytesIO()
    image.save(out,format='JPEG',exif=exif)
    p=ingest(out.getvalue(),'x.jpg',tmp_path)
    assert Image.open(io.BytesIO(model_bytes(p,tmp_path))).size==(50,100)


def test_image_order_and_replacement_invalidate(tmp_path):
    a=ingest(png('red'),'a.png',tmp_path)
    b=ingest(png('blue'),'b.png',tmp_path)
    c=confirmed([a,b],'写完整故事',['第一图','第二图'],['有人'],['关系未知'],'手动填写')
    e=Essay(title='题',body='原文',kind='看图作文',pictures=(a,b),picture_confirmation=c)
    assert valid_confirmation(e)
    for changed in [(b,a),(a,),(b,)]:
        updated=e.model_copy(update={'pictures':changed})
        assert updated.version!=e.version and not valid_confirmation(updated)
    updated=e.model_copy(update={'picture_confirmation':c.model_copy(update={'scenes':('修改图意','第二图')})})
    assert updated.version!=e.version


def test_confirmed_information_in_score_request(tmp_path):
    r=demo_record()
    p=ingest(png(),'q.png',tmp_path)
    c=confirmed([p],'围绕合作写作',['两人布置课室'],['彩纸在墙上'],['关系不能确定'],'手动填写')
    r.essay=r.essay.model_copy(update={'kind':'看图作文','pictures':(p,),'picture_confirmation':c})
    data=json.loads(payload(r.essay,r.config))
    assert data['picture_checked'] is True
    assert data['essay']['picture_confirmation']['scenes']==['两人布置课室']
    assert data['essay']['pictures'][0]['digest']==p.digest
    report=r.report.model_copy(update={'essay_version':r.essay.version},deep=True)
    assert report_errors(report,r.essay,r.config)
    report.picture_alignment=PictureAlignment(relevance='符合合作',reasonable_additions='可写配合过程',deviations='暂未发现',confirmed_quotes=['两人布置课室'])
    assert not report_errors(report,r.essay,r.config)
    report.picture_alignment.confirmed_quotes=['编造图片事实']
    assert report_errors(report,r.essay,r.config)


def test_actual_multimodal_request_is_ordered(monkeypatch,tmp_path):
    import teacher.images as images
    monkeypatch.setattr(images,'ROOT',tmp_path)
    a=ingest(png('red'),'a.png')
    b=ingest(png('blue'),'b.png')
    fake=Mock()
    fake.generate.return_value=PictureReading(text_requirements='题',scenes=['蓝','红'],facts=['颜色'],uncertainties=[])
    identify(fake,[b,a])
    content=fake.generate.call_args.args[2]
    assert [x['type'] for x in content]==['input_text','input_text','input_image','input_text','input_image']
    import base64
    assert content[2]['image_url']=='data:image/jpeg;base64,'+base64.b64encode(model_bytes(b)).decode()


def test_image_record_reopen_missing_image_still_readable(tmp_path):
    r=demo_record()
    p=ingest(png(),'x.png',tmp_path/'images')
    r.report=None
    r.essay=r.essay.model_copy(update={'pictures':(p,),'kind':'看图作文'})
    save(r,tmp_path/'records')
    loaded,warnings=load_all(tmp_path/'records')
    assert not warnings and loaded[0].essay.pictures==(p,)
    assert '不含原图' in loaded[0].backup_images
    assert markdown_report(loaded[0])
