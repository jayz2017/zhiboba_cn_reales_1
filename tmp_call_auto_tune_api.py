import requests
for method, url in [
    ('GET', 'http://127.0.0.1:8000/api/v1/health'),
    ('POST', 'http://127.0.0.1:8000/api/v1/live-text/zhiboba/auto-tune/next?sample_limit=10'),
]:
    try:
        if method == 'GET':
            resp = requests.get(url, timeout=30)
        else:
            resp = requests.post(url, timeout=600)
        print('URL=', url)
        print('STATUS=', resp.status_code)
        print(resp.text[:6000])
    except Exception as exc:
        print('URL=', url)
        print('ERROR=', repr(exc))
