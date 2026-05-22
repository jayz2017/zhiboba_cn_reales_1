import requests
for url in ['http://127.0.0.1:8000/docs','http://127.0.0.1:8000/api/v1/health']:
    try:
        r = requests.get(url, timeout=10)
        print(url, r.status_code)
    except Exception as exc:
        print(url, repr(exc))
