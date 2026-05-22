import requests
url = 'http://127.0.0.1:8000/api/v1/live-text/zhiboba/relations/extract'
resp = requests.post(url, params={'saishi_id': '1780736', 'max_rows': 3, 'sample_limit': 3}, timeout=120)
print(resp.status_code)
print(resp.text)
