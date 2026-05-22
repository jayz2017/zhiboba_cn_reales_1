import requests
url = 'http://127.0.0.1:8000/api/v1/live-text/zhiboba/auto-tune/next?sample_limit=10&max_attempts=3'
try:
    resp = requests.post(url, timeout=600)
    print(resp.status_code)
    print(resp.text[:8000])
except Exception as exc:
    print(repr(exc))
