import math
from .i18n import st


def upload_control(state,settings,key):
    file = st.file_uploader('上传本地 PDF',type=['pdf'],max_upload_size=max(1,math.ceil(settings.pdf_max_bytes/1024/1024)),key=key+'_'+state['uploads'].session_id,
        disabled=state['job'] is not None)
    if file is None:
        return None
    try:
        record = state['uploads'].save(file.name,file.getvalue(),settings)
    except ValueError as exc:
        st.error(str(exc))
        return None
    st.caption(f'{record.name} · {record.pages} 页 · {record.size/1024/1024:.2f} MiB')
    return record
