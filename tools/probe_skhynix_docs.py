import re, json
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36'
s=requests.Session(); s.headers.update({'User-Agent':UA})
BASE='https://sustainability.skhynix.com/'
API='https://sustainabilityapi.skhynix.com/esg-ext-backend'

r=s.get(BASE,timeout=(8,30)); soup=BeautifulSoup(r.text,'html.parser')
scripts=[urljoin(r.url,x.get('src')) for x in soup.find_all('script',src=True)]
print('===== BUNDLE CONTEXT =====')
keywords=['/datacenter/unstructured','/datacenter/list/all','/datacenter/selectDcLayout','/datacenter/selectLclasDataList','/datacenter/selectMlsfcDc','/datacenter/detail/']
for src in scripts:
 try:
  js=s.get(src,timeout=(8,30)).text
  print('SCRIPT',src,'LEN',len(js))
  for keyword in keywords:
   positions=[m.start() for m in re.finditer(re.escape(keyword),js)]
   print('KEY',keyword,'COUNT',len(positions))
   for pos in positions[:20]: print('CTX',keyword,js[max(0,pos-1200):min(len(js),pos+2200)].replace('\n',' ')[:3400])
 except Exception as e: print('SCRIPT_ERR',src,repr(e))

print('===== DIRECT PUBLIC ENDPOINT PROBES =====')
probes=[
 ('GET','/datacenter/unstructured',None),('GET','/datacenter/list/all',None),('GET','/datacenter/selectDcLayout',None),
 ('GET','/datacenter/selectLclasDataList',None),('GET','/datacenter/selectMlsfcDc',None),
 ('POST','/datacenter/unstructured',{}),('POST','/datacenter/list/all',{}),('POST','/datacenter/selectDcLayout',{}),
 ('POST','/datacenter/selectLclasDataList',{}),('POST','/datacenter/selectMlsfcDc',{})]
for method,path,payload in probes:
 try:
  headers={'Origin':BASE.rstrip('/'),'Referer':BASE,'Content-Type':'application/json'}
  rr=s.request(method,API+path,json=payload if method=='POST' else None,headers=headers,timeout=(8,25))
  print('PROBE',method,path,'STATUS',rr.status_code,'TYPE',rr.headers.get('content-type'),'LEN',len(rr.content),'BODY',rr.text[:4000].replace('\n',' '))
 except Exception as e: print('PROBE_ERR',method,path,repr(e))

print('===== K-ESG SEMICONDUCTOR GUIDE =====')
url='https://k-esg.org/post/55'
try:
 rr=s.get(url,timeout=(8,30)); sp=BeautifulSoup(rr.text,'html.parser'); print('POST',rr.status_code,len(rr.content))
 for a in sp.find_all('a',href=True):
  title=' '.join(a.stripped_strings); href=str(a.get('href') or '')
  if 'file_download' in href or '.pdf' in title.lower():
   print('GUIDE_LINK',repr(title),href)
   m=re.search(r"file_download\(['\"]([^'\"]+)",href)
   if m:
    download=m.group(1); print('GUIDE_DOWNLOAD',download)
    d=s.get(download,timeout=(8,60),stream=True); print('GUIDE_PROBE',d.status_code,d.headers.get('content-type'),d.headers.get('content-length'),d.headers.get('content-disposition')); d.close()
except Exception as e: print('GUIDE_ERR',repr(e))
