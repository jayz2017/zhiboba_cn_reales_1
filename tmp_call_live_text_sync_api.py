import requests

url = 'http://127.0.0.1:8000/api/v1/live-text/zhiboba/sync'
params = {'saishi_id': '1780738', 'start_cursor': 1, 'page_size': 10}
resp = requests.post(url, params=params, timeout=600)
print(resp.status_code)
print(resp.text[:4000])
