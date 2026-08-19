import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36'
s=requests.Session(); s.headers.update({'User-Agent':UA})
TARGETS=[
 ('KIND2022','https://kind.krx.co.kr/external/2022/07/28/000117/20220725000126/61979.htm'),
 ('KIND2023','https://kind.krx.co.kr/external/2023/07/21/000113/20230707000320/61979.htm'),
 ('KIND2024','https://kind.krx.co.kr/external/2024/07/23/000345/20240618001016/61979.htm'),
 ('KIND2025','https://kind.krx.co.kr/external/2025/06/19/000512/20250616000286/61979.htm'),
 ('KESG2022','https://k-esg.org/post/76'),
 ('KESG2024','https://k-esg.org/post/3551'),
 ('KESG2025','https://k-esg.org/post/4392'),
 ('KESG_GUIDE','https://k-esg.org/post/55'),
]

for label,url in TARGETS:
 print('\n====',label,url)
 try:
  r=s.get(url,timeout=(8,30),allow_redirects=True)
  print('STATUS',r.status_code,'TYPE',r.headers.get('content-type'),'LEN',len(r.content),'FINAL',r.url)
  text=r.text; soup=BeautifulSoup(text,'html.parser')
  print('TITLE',soup.title.string.strip() if soup.title and soup.title.string else '')
  for tag in soup.find_all(['a','button','input']):
   attrs=' '.join(f'{k}={v}' for k,v in tag.attrs.items())
   title=' '.join(tag.stripped_strings)
   combined=(attrs+' '+title).lower()
   if any(k in combined for k in ['attach','download','file','pdf','첨부','다운로드','report']):
    print('TAG',tag.name,repr(title[:200]),attrs[:1200])
  patterns=[
   r'https?://[^\"\'<>\s]+',
   r'[^\"\'<>\s]*(?:download|attach|file)[^\"\'<>\s]*',
   r'[^\"\'<>\s]+\.pdf[^\"\'<>\s]*'
  ]
  found=[]
  for pat in patterns:
   for x in re.findall(pat,text,re.I):
    if x not in found: found.append(x)
  for x in found[:300]: print('MATCH',x[:1500])
  # Probe directly exposed K-ESG JS download endpoints.
  for a in soup.find_all('a',href=True):
   href=str(a.get('href') or '')
   m=re.search(r"file_download\(['\"]([^'\"]+)",href)
   if m:
    u=m.group(1); print('FILE_DOWNLOAD',u)
    try:
     rr=s.get(u,timeout=(8,60),allow_redirects=True,stream=True)
     print('FILE_PROBE',rr.status_code,rr.url,rr.headers.get('content-type'),rr.headers.get('content-length'),rr.headers.get('content-disposition'))
     rr.close()
    except Exception as e: print('FILE_ERR',repr(e))
 except Exception as e:
  print('ERROR',repr(e))
