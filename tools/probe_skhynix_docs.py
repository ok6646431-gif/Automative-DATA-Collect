import re, json
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36'
s=requests.Session(); s.headers.update({'User-Agent':UA})
BASE='https://sustainability.skhynix.com/'
API='https://sustainabilityapi.skhynix.com/esg-ext-backend'

print('===== SRS API DISCOVERY =====')
r=s.get(BASE,timeout=(8,30)); soup=BeautifulSoup(r.text,'html.parser')
scripts=[urljoin(r.url,x.get('src')) for x in soup.find_all('script',src=True)]
for src in scripts:
 try:
  js=s.get(src,timeout=(8,30)).text
  print('SCRIPT',src,'LEN',len(js))
  for keyword in ['sustainReport','datacenter_download','globalReport','fileUrl','selectReport','report/select','reports']:
   starts=[m.start() for m in re.finditer(re.escape(keyword),js,re.I)]
   print('KEYWORD',keyword,'COUNT',len(starts))
   for pos in starts[:40]:
    print('CTX',keyword,js[max(0,pos-700):min(len(js),pos+1200)].replace('\n',' ')[:1900])
  endpoints=[]
  for pat in [r'"(/[A-Za-z0-9_./?=&-]{3,})"',r"'(/[A-Za-z0-9_./?=&-]{3,})'"]:
   for x in re.findall(pat,js):
    xl=x.lower()
    if any(k in xl for k in ['report','data','file','policy']) and x not in endpoints: endpoints.append(x)
  for x in endpoints[:300]: print('ENDPOINT_CANDIDATE',x)
 except Exception as e: print('SCRIPT_ERR',src,repr(e))

# Probe conservative GET candidates found/expected from bundle naming. Only reads public endpoints.
candidates=[
 '/datacenter/report', '/datacenter/reports', '/datacenter/sustainReport', '/datacenter/sustain-report',
 '/report', '/reports', '/report/list', '/reports/list', '/datacenter/report/list',
 '/common/file/list', '/file/list'
]
print('===== CONSERVATIVE API GET PROBES =====')
for path in candidates:
 try:
  rr=s.get(API+path,timeout=(8,20),headers={'Origin':'https://sustainability.skhynix.com','Referer':BASE})
  print('API_PROBE',path,rr.status_code,rr.headers.get('content-type'),'LEN',len(rr.content),'BODY',rr.text[:1000].replace('\n',' '))
 except Exception as e: print('API_ERR',path,repr(e))
