import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36'
s=requests.Session(); s.headers.update({'User-Agent':UA})
TARGETS=[
 ('SRS','https://sustainability.skhynix.com/'),
 ('SRS_REPORT','https://sustainability.skhynix.com/datacenter?section=sustainReport'),
 ('SK_REPORTS','https://www.skhynix.com/sustainability/UI-FR-SA1601/'),
 ('NEWS2023','https://news.skhynix.co.kr/2023-sustainability-report/'),
 ('KIND2024','https://kind.krx.co.kr/external/2024/07/23/000345/20240618001016/61979.htm'),
 ('KIND2023','https://kind.krx.co.kr/external/2023/07/21/000113/20230707000320/61979.htm'),
 ('KESG2024','https://k-esg.org/post/3551'),
]

def interesting(u,t=''):
 x=(u+' '+t).lower()
 return any(k in x for k in ['.pdf','download','attach','file','sustain','report','tcfd','policy'])

def inspect(label,url,deep_js=False):
 print('\n===== TARGET',label,url)
 try:
  r=s.get(url,timeout=(8,30),allow_redirects=True)
  print('STATUS',r.status_code,'FINAL',r.url,'TYPE',r.headers.get('content-type'),'BYTES',len(r.content))
  text=r.text; soup=BeautifulSoup(text,'html.parser')
  for a in soup.find_all('a',href=True):
   href=urljoin(r.url,a.get('href')); title=' '.join(a.stripped_strings)
   if interesting(href,title): print('LINK',repr(title[:160]),href)
  scripts=[]
  for sc in soup.find_all('script',src=True):
   src=urljoin(r.url,sc.get('src')); scripts.append(src); print('SCRIPT',src)
  for f in soup.find_all('form')[:50]: print('FORM',f.get('action'),f.get('method'))
  for pat in [r'https?://[^\"\'<> ]+\.pdf[^\"\'<> ]*',r'[^\"\']+\.pdf[^\"\']*',r'[^\"\']*(?:download|attach|file)[^\"\']*']:
   vals=[]
   for x in re.findall(pat,text,re.I):
    if x not in vals: vals.append(x)
   for x in vals[:100]: print('REGEX',x[:500])
  if deep_js:
   for src in scripts[:20]:
    try:
     js=s.get(src,timeout=(8,30)).text; print('JS',src,'LEN',len(js)); matches=[]
     for pat in [r'https?://[^\"\' ]+',r'[/A-Za-z0-9_.?=&-]*(?:api|report|download|file|pdf)[/A-Za-z0-9_.?=&-]*']:
      for x in re.findall(pat,js,re.I):
       if len(x)>4 and x not in matches: matches.append(x)
     for x in matches[:300]: print('JS_MATCH',x[:700])
    except Exception as e: print('JS_ERR',src,repr(e))
  return soup
 except Exception as e:
  print('ERROR',repr(e)); return None

for label,url in TARGETS:
 inspect(label,url,label.startswith('SRS'))

print('\n===== K-ESG FULL ARCHIVE SCAN =====')
post_urls=[]
for page in range(1,13):
 url='https://k-esg.org/board/esg_report' + (f'?page={page}' if page>1 else '')
 try:
  r=s.get(url,timeout=(8,30)); print('BOARD',page,r.status_code,len(r.content))
  soup=BeautifulSoup(r.text,'html.parser')
  for a in soup.find_all('a',href=True):
   title=' '.join(a.stripped_strings); href=urljoin(r.url,a.get('href'))
   if ('하이닉스' in title or 'hynix' in title.lower()) and '/post/' in href:
    if href not in post_urls: post_urls.append(href); print('HYNIX_POST',repr(title),href)
 except Exception as e: print('BOARD_ERR',page,repr(e))

for i,url in enumerate(post_urls,1):
 print('\n--- HYNIX DETAIL',i,url)
 try:
  r=s.get(url,timeout=(8,30)); soup=BeautifulSoup(r.text,'html.parser'); text=' '.join(soup.stripped_strings)
  print('DETAIL_STATUS',r.status_code,'TEXT',text[:600])
  for a in soup.find_all('a',href=True):
   title=' '.join(a.stripped_strings); href=str(a.get('href') or '')
   if 'file_download' in href or '.pdf' in title.lower() or 'hynix' in title.lower() or 'skhynix' in href.lower():
    print('DETAIL_LINK',repr(title[:200]),href)
    m=re.search(r"file_download\(['\"]([^'\"]+)",href)
    if m:
     download=m.group(1); print('DOWNLOAD_ENDPOINT',download)
     try:
      rr=s.get(download,timeout=(8,60),allow_redirects=True,stream=True)
      print('DOWNLOAD_PROBE',rr.status_code,rr.url,rr.headers.get('content-type'),rr.headers.get('content-length'),rr.headers.get('content-disposition'))
      rr.close()
     except Exception as e: print('DOWNLOAD_ERR',repr(e))
 except Exception as e: print('DETAIL_ERR',repr(e))
