import argparse
import os
import sys
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv


load_dotenv()

URL = os.getenv("JIRA_URL", "").rstrip("/")
EMAIL = os.getenv("JIRA_EMAIL")
TOKEN = os.getenv("JIRA_API_TOKEN")
PROJECT = os.getenv("JIRA_PROJECT_KEY")


def die(code, message):
    print(f"[FAIL] {code}: {message}")
    sys.exit(1)


if not all([URL, EMAIL, TOKEN, PROJECT]):
    die("CONFIG_MISSING", "Check Jira values in .env")


session = requests.Session()
session.auth = (EMAIL, TOKEN)
session.headers["Accept"] = "application/json"


def jira_get(path, **params):
    try:
        r = session.get(
            f"{URL}/rest/api/3{path}",
            params=params,
            timeout=15,
        )
    except requests.RequestException as error:
        die("JIRA_CONNECTION_FAILED", str(error))

    if r.status_code == 401:
        die("JIRA_AUTH_FAILED", "Check Jira email/API token.")

    if not r.ok:
        die(
            f"JIRA_HTTP_{r.status_code}",
            r.text[:200] or "Request failed."
        )

    return r.json()


def search(jql, all_pages=True):
    issues = []
    token = None

    while True:
        params = {
            "jql": jql,
            "maxResults": 100 if all_pages else 1,
            "fields": "summary",
        }

        if token:
            params["nextPageToken"] = token

        data = jira_get("/search/jql", **params)
        issues.extend(data.get("issues", []))
        token = data.get("nextPageToken")

        if not all_pages or not token:
            return issues


def smoke_test():
    user = jira_get("/myself")

    try:
        project = jira_get(f"/project/{PROJECT}")
    except SystemExit:
        die(
            "PROJECT_NOT_FOUND",
            f"{PROJECT} does not exist or is not accessible."
        )

    permissions = jira_get(
        "/mypermissions",
        projectKey=PROJECT,
        permissions="BROWSE_PROJECTS",
    )

    allowed = (
        permissions
        .get("permissions", {})
        .get("BROWSE_PROJECTS", {})
        .get("havePermission", False)
    )

    if not allowed:
        die(
            "BROWSE_PROJECTS_DENIED",
            f"No Browse Projects permission for {PROJECT}."
        )

    search(
        f'project = "{PROJECT}" ORDER BY created DESC',
        all_pages=False,
    )

    print("JIRA SMOKE TEST")
    print(f"User:        {user.get('displayName')}")
    print(f"Project:     {project.get('name')} ({PROJECT})")
    print("Permission:  Browse Projects PASS")
    print("JQL search:  PASS")


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD.")


def reporting_period(start=None, end=None):
    if start or end:
        if not start or not end or end <= start:
            die(
                "INVALID_DATE_RANGE",
                "Use --start and --end with end later than start."
            )

        return start, end

    today = date.today()
    this_monday = today - timedelta(days=today.weekday())

    return (
        this_monday - timedelta(days=7),
        this_monday,
    )


def report(start, end):
    base = f'project = "{PROJECT}"'

    queries = {
        "Created": (
            f'{base} AND created >= "{start}" '
            f'AND created < "{end}"'
        ),
        "Resolved": (
            f'{base} AND resolutiondate >= "{start}" '
            f'AND resolutiondate < "{end}"'
        ),
        "Still open": (
            f'{base} AND created >= "{start}" '
            f'AND created < "{end}" '
            f'AND resolution IS EMPTY'
        ),
    }

    counts = {
        name: len(search(jql))
        for name, jql in queries.items()
    }

    sunday = end - timedelta(days=1)

    print()
    print("=" * 55)
    print("JIRA MONDAY BRIEF")
    print("=" * 55)
    print(f"Project:          {PROJECT}")
    print(
        f"Reporting period: "
        f"{start} 00:00 to {sunday} 23:59"
    )
    print("-" * 55)
    print(f"Created:          {counts['Created']}")
    print(f"Resolved:         {counts['Resolved']}")
    print(f"Still open:       {counts['Still open']}")
    print("=" * 55)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--smoke-test",
        action="store_true"
    )

    parser.add_argument(
        "--start",
        type=parse_date
    )

    parser.add_argument(
        "--end",
        type=parse_date
    )

    args = parser.parse_args()

    if args.smoke_test:
        smoke_test()
        return

    start, end = reporting_period(
        args.start,
        args.end
    )

    report(start, end)


if __name__ == "__main__":
    main()