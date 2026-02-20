import csv
from pathlib import Path
p=Path('data/geocoding/geocode_ref_gaiku_tokyo_2024/13_2024.csv')
with p.open('r',encoding='cp932',newline='') as f:
    r=csv.DictReader(f)
    rows=[]
    for row in r:
      if row['市区町村名']=='立川市' and row['大字・丁目名']=='羽衣町二丁目' and row['街区符号・地番'].startswith('11'):
        rows.append(row)
    print('count',len(rows))
    for row in rows[:20]:
      print(row['大字・丁目名'], row['街区符号・地番'], row['緯度'], row['経度'])
