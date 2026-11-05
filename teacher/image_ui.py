import os
from teacher.client import ModelClient, friendly_error
from teacher.images import ingest, MAX_FILES, model_bytes, identify, image_version, confirmed
from teacher.private_media import private_image


def picture_editor(st, key, model, busy):
    st.subheader('看图作文题目图片与图意')
    st.caption('题目图片，不是学生手写作文。最多8张，每张10 MB、2000万像素，每边至少32像素。支持一张多幅图或多张图。')
    pictures = list(st.session_state.get('edit_pictures',()))
    files = st.file_uploader('选择题目图片（选择后点击添加）',type=['png','jpg','jpeg','webp'],
                             accept_multiple_files=True,max_upload_size=10,
                             key='topic_upload_'+str(st.session_state.get('upload_epoch',0)),disabled=busy)
    if st.button('添加已选题目图片',disabled=busy or not files):
        try:
            if len(files)+len(pictures)>MAX_FILES:
                raise ValueError('每道题最多8张图片，请先删除不需要的图片。')
            additions=[ingest(f.getvalue(),f.name) for f in files]
            seen={p.digest for p in pictures}
            for p in additions:
                if p.digest not in seen:
                    pictures.append(p)
                    seen.add(p.digest)
            st.session_state.edit_pictures=tuple(pictures)
            st.session_state.upload_epoch=st.session_state.get('upload_epoch',0)+1
            st.rerun()
        except (ValueError,OSError) as e:
            st.error(str(e) if isinstance(e,ValueError) else friendly_error(e))
    for i,p in enumerate(pictures):
        st.markdown(f'**图片 {i+1}**')
        try:
            private_image(st,model_bytes(p),alt=f'第{i+1}张题目图片',key=f'private-picture-{i}-{p.digest}')
        except (OSError,ValueError):
            st.warning(f'图片{i+1}缺失或损坏；现有报告仍可阅读，可重新上传图片。')
        a,b,c=st.columns(3)
        def change(action,index=i):
            items=list(st.session_state.get('edit_pictures',()))
            if action=='delete':
                items.pop(index)
            else:
                other=index+(-1 if action=='up' else 1)
                items[index],items[other]=items[other],items[index]
            st.session_state.edit_pictures=tuple(items)
        a.button('上移',key='pic_up_'+str(i),disabled=busy or i==0,on_click=change,args=('up',))
        b.button('下移',key='pic_down_'+str(i),disabled=busy or i==len(pictures)-1,on_click=change,args=('down',))
        c.button('删除',key='pic_delete_'+str(i),disabled=busy,on_click=change,args=('delete',))
    version=image_version(pictures)
    recognition=st.session_state.get('recognition_version')
    def request_reading():
        if not st.session_state.get('busy'):
            st.session_state.pending_vision=version
            st.session_state.busy=True
    st.button('识别题目与图意',disabled=busy or not pictures or not key or not model,on_click=request_reading)
    pending=st.session_state.pop('pending_vision',None)
    if pending and pending==version and pictures:
        try:
            with st.spinner('正在按图片顺序识别题目与图意……'):
                vision_model=os.getenv('OPENAI_VISION_MODEL') or st.session_state.get('vision_model') or model
                reading=identify(ModelClient(key,vision_model),pictures)
            st.session_state.topic_text=reading.text_requirements
            for i,scene in enumerate(reading.scenes):
                st.session_state['topic_scene_'+str(i)]=scene
            st.session_state.topic_facts='\n'.join(reading.facts)
            st.session_state.topic_uncertainties='\n'.join(reading.uncertainties)
            st.session_state.recognition_version=version
            st.session_state.edit_picture_confirmation=None
            st.session_state.pop('vision_error',None)
        except Exception as e:
            st.session_state.vision_error=friendly_error(e)
        finally:
            st.session_state.busy=False
        st.rerun()
    elif pending:
        st.session_state.busy=False
        st.rerun()
    if st.session_state.get('vision_error'):
        st.error(st.session_state.vision_error)
    if not key or not model:
        st.info('没有模型配置时可手动填写并确认图意；不会模拟识别成功。')
    old=st.session_state.get('edit_picture_confirmation')
    if old and old.image_version!=version:
        st.warning('图片或顺序已改变，原图意确认及对应报告属于旧版本，请重新核对并确认。')
    if recognition and recognition!=version:
        st.warning('编辑区可能保留旧顺序的识别文字；请按当前图片逐项调整后重新确认。')
    text=st.text_area('图片上可辨认的题目文字与写作要求',key='topic_text',disabled=busy)
    count=len(pictures) or 1
    scenes=[st.text_area(f'图片{i+1}：按图中顺序描述人物、动作、物品和事件' if pictures else '手动图意说明',
                         key='topic_scene_'+str(i),disabled=busy) for i in range(count)]
    facts=st.text_area('图片明确显示的事实（每行一项）',key='topic_facts',disabled=busy)
    uncertain=st.text_area('无法确定的细节与待确认问题（每行一项）',key='topic_uncertainties',disabled=busy)
    effective=None
    try:
        proposed=confirmed(pictures,text,scenes,facts.splitlines(),uncertain.splitlines(),
                           '模型识别后人工确认' if st.session_state.get('recognition_version')==version else '手动填写')
        if old==proposed:
            effective=old
    except ValueError:
        proposed=None
    if old and not effective:
        st.warning('图意或图片已修改，尚未重新确认；当前评分不会采用旧图意。')
    if st.button('确认题目与图意',disabled=busy or proposed is None):
        st.session_state.edit_picture_confirmation=proposed
        st.rerun()
    if effective:
        st.success('题目与图意已确认：'+effective.method+'。修改作文前请再确认原文版本。')
    st.session_state.edit_pictures=tuple(pictures)
    # Queue callback must see precisely the effective confirmation, not a stale one.
    st.session_state.effective_picture_confirmation=effective
    return tuple(pictures),effective


def restore_picture_editor(st,essay):
    st.session_state.upload_epoch=st.session_state.get('upload_epoch',0)+1
    st.session_state.edit_pictures=essay.pictures
    st.session_state.edit_picture_confirmation=essay.picture_confirmation
    st.session_state.pop('pending_vision',None)
    st.session_state.pop('vision_error',None)
    for k in list(st.session_state):
        if k.startswith('topic_scene_'):
            del st.session_state[k]
    c=essay.picture_confirmation
    st.session_state.topic_text=c.text_requirements if c else ''
    st.session_state.topic_facts='\n'.join(c.facts) if c else ''
    st.session_state.topic_uncertainties='\n'.join(c.uncertainties) if c else ''
    st.session_state.recognition_version=c.image_version if c and c.method=='模型识别后人工确认' else None
    for i,scene in enumerate(c.scenes if c else []):
        st.session_state['topic_scene_'+str(i)]=scene
