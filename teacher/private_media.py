"""Send private media only over the authenticated app's UI stream, never /media URLs."""
import base64
from streamlit.components.v2 import component

JS='''export default function({data, parentElement}) {
  const button=parentElement.querySelector('button');
  const image=parentElement.querySelector('img');
  button.hidden=data.kind!=='download';
  image.hidden=data.kind!=='image';
  if (data.kind==='image') {
    image.alt=data.label;
    image.src='data:image/jpeg;base64,'+data.payload;
    return () => { image.removeAttribute('src'); };
  }
  button.textContent=data.label;
  button.disabled=data.disabled;
  let url=null;
  button.onclick=() => {
    if (data.disabled) return;
    const bytes=Uint8Array.from(atob(data.payload), ch => ch.charCodeAt(0));
    url=URL.createObjectURL(new Blob([bytes], {type:data.mime}));
    const anchor=document.createElement('a');
    anchor.href=url; anchor.download=data.filename;
    parentElement.appendChild(anchor);
    anchor.click();
    anchor.remove();
    const previous=url;
    setTimeout(() => URL.revokeObjectURL(previous), 1000);
  };
  return () => { button.onclick=null; if (url) URL.revokeObjectURL(url); };
}'''

_MEDIA=component('family_private_media',
    html='<button type="button"></button><img hidden style="max-width:100%;height:auto" />',js=JS)


def private_download(st,label,data,file_name,mime='text/plain',disabled=False,key=None):
    payload=data.encode('utf-8') if isinstance(data,str) else bytes(data)
    return _MEDIA(data=dict(kind='download',label=label,payload=base64.b64encode(payload).decode('ascii'),
        filename=file_name,mime=mime,disabled=disabled),key=key or 'private-download-'+file_name)


def private_image(st,data,alt,key):
    return _MEDIA(data=dict(kind='image',label=alt,payload=base64.b64encode(data).decode('ascii')),key=key)
