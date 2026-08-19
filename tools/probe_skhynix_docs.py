import re, json
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

for label,url in TARGETS:
 print('\n===== TARGET',label,url)
 try:
  r=s.get(url,timeout=(8,30),allow_redirects=True)
  print('STATUS',r.status_code,'FINAL',r.url,'TYPE',r.headers.get('content-type'),'BYTES',len(r.content))
  text=r.text
  soup=BeautifulSoup(text,'html.parser')
  links=[]
  for a in soup.find_all('a',href=True):
   href=urljoin(r.url,a.get('href'))
   title=' '.join(a.stripped_strings)
   if interesting(href,title): links.append((title,href))
  for title,href in links[:200]: print('LINK',repr(title[:120]),href)
  scripts=[]
  for sc in soup.find_all('script',src=True):
   src=urljoin(r.url,sc.get('src'))
   scripts.append(src); print('SCRIPT',src)
  forms=soup.find_all('form')
  for f in forms[:50]: print('FORM',f.get('action'),f.get('method'))
  for pat in [r'https?://[^\"\'<> ]+\.pdf[^\"\'<> ]*',r'[^\"\']+\.pdf[^\"\']*',r'[^\"\']*(?:download|attach|file)[^\"\']*']:
   vals=[]
   for x in re.findall(pat,text,re.I):
    if x not in vals: vals.append(x)
   for x in vals[:100]: print('REGEX',x[:500])
  if label.startswith('SRS'):
   for src in scripts[:20]:
    try:
     js=s.get(src,timeout=(8,30)).text
     print('JS',src,'LEN',len(js))
     matches=[]
     pats=[r'https?://[^\"\' ]+',r'[/A-Za-z0-9_.?=&-]*(?:api|report|download|file|pdf)[/A-Za-z0-9_.?=&-]*']
     for pat in pats:
      for x in re.findall(pat,js,re.I):
       if len(x)>4 and x not in matches: matches.append(x)
     for x in matches[:300]: print('JS_MATCH',x[:700])
    except Exception as e: print('JS_ERR',src,repr(e))
 except Exception as e:
  print('ERROR',repr(e))
