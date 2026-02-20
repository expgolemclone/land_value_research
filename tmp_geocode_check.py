from src.geocode_tokyo import TokyoGeocoder
print('init', flush=True)
g=TokyoGeocoder(oaza_csv='data/geocoding/geocode_ref_oaza_chome_tokyo_2024/13_2024.csv', gaiku_csv='data/geocoding/geocode_ref_gaiku_tokyo_2024/13_2024.csv')
print('ready', flush=True)
addr='東京都立川市羽衣町2-11-12'
lat,lon,level=g.geocode(addr)
print(level, lat, lon, flush=True)
