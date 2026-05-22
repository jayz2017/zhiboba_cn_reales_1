import requests

for url in [
    'http://127.0.0.1:8000/api/v1/health',
    'http://127.0.0.1:8000/docs',
]:
    try:
        resp = requests.get(url, timeout=10)
        print(url, resp.status_code)
        print(resp.text[:300])
    except Exception as exc:
        print(url, 'ERROR', repr(exc))
