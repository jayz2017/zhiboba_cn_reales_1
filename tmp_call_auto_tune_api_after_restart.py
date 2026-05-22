import requests
url = 'http://127.0.0.1:8000/api/v1/live-text/zhiboba/auto-tune/next'
resp = requests.post(url, params={'sample_limit': 10, 'max_attempts': 3}, timeout=600)
print(resp.status_code)
print(resp.text[:12000])
