import os
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv


load_dotenv()


def log(level, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} [{level}] {message}")


def fail(code, message, suggestion=None):
    log("FAIL", f"{code}: {message}")

    if suggestion:
        log("HELP", suggestion)

    sys.exit(1)


JIRA_URL = os.getenv("JIRA_URL", "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")


log("INFO", "Starting Jira Monday Brief smoke test")


required_config = {
    "JIRA_URL": JIRA_URL,
    "JIRA_EMAIL": JIRA_EMAIL,
    "JIRA_API_TOKEN": JIRA_API_TOKEN,
    "JIRA_PROJECT_KEY": JIRA_PROJECT_KEY,
}

missing = [
    name
    for name, value in required_config.items()
    if not value
]

if missing:
    fail(
        "CONFIG_MISSING",
        f"Missing configuration: {', '.join(missing)}",
        "Check the local .env file."
    )


log("PASS", "Required configuration is present")


try:
    response = requests.get(
        f"{JIRA_URL}/rest/api/3/myself",
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json"},
        timeout=15,
    )

except requests.exceptions.Timeout:
    fail(
        "JIRA_TIMEOUT",
        "Jira did not respond within 15 seconds.",
        "Check your network connection and Jira URL."
    )

except requests.exceptions.RequestException as error:
    fail(
        "JIRA_CONNECTION_FAILED",
        str(error),
        "Check JIRA_URL and your network connection."
    )


if response.status_code == 401:
    fail(
        "JIRA_AUTH_FAILED",
        "Jira returned HTTP 401.",
        "Verify JIRA_EMAIL and JIRA_API_TOKEN."
    )

if response.status_code == 403:
    fail(
        "JIRA_ACCESS_DENIED",
        "Jira returned HTTP 403.",
        "Check the permissions of your Atlassian account."
    )

if response.status_code != 200:
    fail(
        "JIRA_UNEXPECTED_RESPONSE",
        f"Jira returned HTTP {response.status_code}.",
        response.text[:300]
    )


user = response.json()

log(
    "PASS",
    f"Authenticated with Jira as {user.get('displayName', 'Unknown user')}"
)

print()
print("=" * 55)
print("JIRA MONDAY BRIEF - SMOKE TEST")
print("=" * 55)
print("Configuration       PASS")
print("Jira connectivity   PASS")
print("Authentication      PASS")
print("=" * 55)

log("PASS", "Smoke test completed successfully")