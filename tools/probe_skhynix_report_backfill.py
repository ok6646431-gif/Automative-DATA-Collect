import requests

URLS={
  '2021':'https://ksaesg.or.kr/pop_file_download.php?img_type=img_list&no=45&target=display',
  '2022':'https://ksaesg.or.kr/pop_file_download.php?img_type=img_list&no=270&target=display',
  '2023':'https://ksaesg.or.kr/pop_file_download.php?img_type=img_list&no=478&target=display',
}
SOURCES={
  '2021':'https://ksaesg.or.kr/p_base.php?1=1&action=h_report_04_detail&no=45&page=15&s_category=&s_text=',
  '2022':'https://ksaesg.or.kr/p_base.php?1=1&action=h_report_04_detail&no=270&page=4&s_category=&s_text=',
  '2023':'https://ksaesg.or.kr/p_base.php?1=1&action=h_report_04_detail&no=478&page=7&s_category=&s_text=',
}
s=requests.Session(); s.headers['User-Agent']='Mozilla/5.0 Chrome/151 Safari/537.36'
for year,url in URLS.items():
 print('\nYEAR',year)
 try:
  p=s.get(SOURCES[year],timeout=(8,30)); print('SOURCE',p.status_code,p.url,len(p.content),p.headers.get('content-type'))
  r=s.get(url,headers={'Referer':p.url},timeout=(8,60),allow_redirects=True)
  print('DOWNLOAD',r.status_code,r.url,r.headers.get('content-type'),len(r.content),r.headers.get('content-disposition'),repr(r.content[:12]))
 except Exception as e: print('ERROR',type(e).__name__,e)
