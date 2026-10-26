# MAX Mini App
чтобы интерфейс посмотреть не скачивая файл есть сайт https://htmlpreview.github.io/ на него зайдете и вставите ссылку ->
-> https://raw.githubusercontent.com/Lefiper/gorky-code/refs/heads/main/mini-app/max-mini-app.html
вариант тестовый посмотрите и скажите какие еще функции добавить если нужно, какие может поменять или убрать.
в FastAPI нужно будет добавить middleware:
import hmac, hashlib, urllib.parse, os

def verify_init_data(init_data: str) -> int:
    params = dict(urllib.parse.parse_qsl(init_data))
    received_hash = params.pop("hash", "")
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["MAX_BOT_TOKEN"].encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise HTTPException(403, "Invalid initData signature")
    user = json.loads(params["user"])
    return user["id"]
    
