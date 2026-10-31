"""Create local .env with random passwords; never overwrite existing secrets."""
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / ".env"
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    keys = {"POSTGRES_PASSWORD", "APP_DB_PASSWORD", "API_DB_PASSWORD", "AGENT_DB_PASSWORD",
            "BOT_DB_PASSWORD", "AGENT_API_KEY", "MCP_AUTH_TOKEN"}
    lines = []
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in keys:
            line = key + "=" + secrets.token_hex(24)
        elif separator and key in {"MAX_BOT_TOKEN", "GIGACHAT_CREDENTIALS"}:
            line = key + "=placeholder"
        lines.append(line)
    try:
        with target.open("x", encoding="utf-8") as out:
            out.write("\n".join(lines) + "\n")
        target.chmod(0o600)
    except FileExistsError:
        raise SystemExit(".env already exists; no values were changed")
    print("Created .env. Replace MAX_BOT_TOKEN and GIGACHAT_CREDENTIALS for live calls.")


if __name__ == "__main__":
    main()
