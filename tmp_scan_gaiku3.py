import csv
from pathlib import Path
p=Path('data/geocoding/geocode_ref_gaiku_tokyo_2024/13_2024.csv')
with p.open('r',encoding='cp932',newline='') as f:
    r=csv.DictReader(f)
    n=0
    for row in r:
      if row['市区町村名']=='立川市' and '羽衣町' in row['大字・丁目名']:
        print(row['市区町村名'], row['大字・丁目名'], row['街区符号・地番'], row['緯度'], row['経度'])
        n+=1
        if n>=40:
          break
    print('shown',n)
