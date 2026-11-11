import requests, pandas as pd
r = requests.get('https://api.energidataservice.dk/dataset/PowerSystemRightNow', params={'limit': 60}).json()['records']
df = pd.DataFrame(r); df['WIND'] = df.OnshoreWindPower + df.OffshoreWindPower
print(df[['Minutes1UTC', 'WIND', 'CO2Emission', 'Exchange_Sum']].head())
