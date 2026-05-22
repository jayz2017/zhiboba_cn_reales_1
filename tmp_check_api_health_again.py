import requests
for url in ['http://127.0.0.1:8000/api/v1/health','http://127.0.0.1:8000/docs']:
    try:
        r = requests.get(url, timeout=15)
        print(url, r.status_code)
    except Exception as exc:
        print(url, repr(exc))
