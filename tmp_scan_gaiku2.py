import csv
from pathlib import Path
p=Path('data/geocoding/geocode_ref_gaiku_tokyo_2024/13_2024.csv')
with p.open('r',encoding='cp932',newline='') as f:
    r=csv.reader(f)
    h=next(r)
    print('header_len',len(h))
    print('header',h)
    n=0
    for row in r:
      s=','.join(row)
      if '立川市羽衣町' in s:
        print(s[:300])
        n+=1
        if n>=20:
          break
    print('shown',n)
