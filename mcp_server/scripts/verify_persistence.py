"""Вымышленная контрольная запись для проверки сохранения после restart Docker-БД."""

import argparse

from app.config import Settings
from app.events import EventService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("write", "read"))
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    user = "test:persistence:" + args.token
    service = EventService(Settings.load())
    if args.phase == "write":
        result = service.create_event(user, "task", "Контрольная запись перезапуска", "2034-01-02T10:00:00Z", idempotency_key=args.token)
        print("Control event saved:", result["event"]["id"])
    else:
        result = service.get_event(user, "2034-01-02T00:00:00Z", "2034-01-03T00:00:00Z")
        if len(result["items"]) != 1:
            raise RuntimeError("Контрольная запись не найдена или продублирована")
        print("Control event persisted:", result["items"][0]["id"])


if __name__ == "__main__":
    main()
