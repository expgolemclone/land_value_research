import csv
from pathlib import Path
p=Path('data/geocoding/geocode_ref_gaiku_tokyo_2024/13_2024.csv')
encodings=['utf-8-sig','cp932','shift_jis','utf-8']
for enc in encodings:
    try:
        with p.open('r',encoding=enc,newline='') as f:
            reader=csv.reader(f)
            header=next(reader)
            idx=None
            for i,h in enumerate(header):
                if '所在地' in h or '住所' in h or '町' in h:
                    pass
            cnt=0
            for row in reader:
                s=','.join(row)
                if '立川市' in s and '羽衣町' in s and ('2-11-12' in s or '2丁目11' in s):
                    print(enc, s[:220])
                    cnt+=1
                    if cnt>=5:
                        break
            print('encoding',enc,'matches',cnt)
        break
    except Exception as e:
        print('fail',enc,e)
