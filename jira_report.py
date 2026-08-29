import argparse
import os
import smtplib
import sys
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from html import escape

import requests
from dotenv import load_dotenv


load_dotenv()

URL = os.getenv("JIRA_URL", "").rstrip("/")
EMAIL = os.getenv("JIRA_EMAIL")
TOKEN = os.getenv("JIRA_API_TOKEN")
PROJECT = os.getenv("JIRA_PROJECT_KEY")

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = os.getenv("SMTP_PORT") or "587"
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
RECIPIENT = os.getenv("REPORT_RECIPIENT")


def die(code, message):
    print(f"[FAIL] {code}: {message}")
    sys.exit(1)


if not all([URL, EMAIL, TOKEN, PROJECT]):
    die("CONFIG_MISSING", "Check Jira configuration.")


session = requests.Session()
session.auth = (EMAIL, TOKEN)
session.headers["Accept"] = "application/json"


def jira_get(path, **params):
    try:
        response = session.get(
            f"{URL}/rest/api/3{path}",
            params=params,
            timeout=15,
        )
    except requests.RequestException as error:
        die("JIRA_CONNECTION_FAILED", str(error))

    if response.status_code == 401:
        die("JIRA_AUTH_FAILED", "Check Jira email/API token.")

    if response.status_code == 403:
        die("JIRA_ACCESS_DENIED", "Jira permission denied.")

    if not response.ok:
        die(
            f"JIRA_HTTP_{response.status_code}",
            response.text[:200] or "Request failed.",
        )

    return response.json()


def search(jql, sample=False):
    issues = []
    token = None

    while True:
        params = {
            "jql": jql,
            "maxResults": 1 if sample else 100,
            "fields": "summary,status,priority",
        }

        if token:
            params["nextPageToken"] = token

        data = jira_get("/search/jql", **params)
        issues.extend(data.get("issues", []))
        token = data.get("nextPageToken")

        if sample or not token:
            return issues


def smoke_test():
    user = jira_get("/myself")
    project = jira_get(f"/project/{PROJECT}")

    permissions = jira_get(
        "/mypermissions",
        projectKey=PROJECT,
        permissions="BROWSE_PROJECTS",
    )

    allowed = (
        permissions.get("permissions", {})
        .get("BROWSE_PROJECTS", {})
        .get("havePermission", False)
    )

    if not allowed:
        die(
            "BROWSE_PROJECTS_DENIED",
            f"No Browse Projects permission for {PROJECT}.",
        )

    search(
        f'project = "{PROJECT}" ORDER BY created DESC',
        sample=True,
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


def reporting_period(period, start=None, end=None):
    today = date.today()
    monday = today - timedelta(days=today.weekday())

    if period == "custom":
        if not start or not end or end < start:
            die(
                "INVALID_DATE_RANGE",
                "Provide a valid custom start and end date.",
            )

        # Custom end date is inclusive for the operator.
        return start, end + timedelta(days=1)

    if start or end:
        die(
            "INVALID_DATE_RANGE",
            "Dates may only be used with --period custom.",
        )

    periods = {
        "previous-week": (
            monday - timedelta(days=7),
            monday,
        ),
        "previous-2-weeks": (
            monday - timedelta(days=14),
            monday,
        ),
        "previous-30-days": (
            today - timedelta(days=30),
            today,
        ),
    }

    return periods[period]


def get_report(start, end):
    base = f'project = "{PROJECT}"'

    created = search(
        f'{base} AND created >= "{start}" AND created < "{end}"'
    )

    resolved = search(
        f'{base} AND resolutiondate >= "{start}" '
        f'AND resolutiondate < "{end}"'
    )

    open_issues = search(
        f'{base} AND created >= "{start}" '
        f'AND created < "{end}" '
        f'AND resolution IS EMPTY'
    )

    return created, resolved, open_issues


def print_report(start, end, created, resolved, open_issues):
    display_end = end - timedelta(days=1)

    print("\n" + "=" * 55)
    print("JIRA MONDAY BRIEF")
    print("=" * 55)
    print(f"Project:          {PROJECT}")
    print(f"Reporting period: {start} to {display_end}")
    print("-" * 55)
    print(f"Created:          {len(created)}")
    print(f"Resolved:         {len(resolved)}")
    print(f"Still open:       {len(open_issues)}")
    print("=" * 55)


def send_email(start, end, created, resolved, open_issues):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, RECIPIENT]):
        die("EMAIL_CONFIG_MISSING", "Check SMTP configuration.")

    try:
        smtp_port = int(SMTP_PORT)
    except ValueError:
        die("EMAIL_CONFIG_INVALID", "SMTP_PORT must be numeric.")

    display_end = end - timedelta(days=1)

    rows = ""

    for issue in open_issues:
        fields = issue.get("fields", {})

        key = escape(issue.get("key", ""))
        summary = escape(fields.get("summary", "") or "")
        status = escape(
            (fields.get("status") or {}).get("name", "")
        )
        priority = escape(
            (fields.get("priority") or {}).get("name", "Not set")
        )

        rows += f"""
        <tr>
            <td><a href="{URL}/browse/{key}">{key}</a></td>
            <td>{summary}</td>
            <td>{priority}</td>
            <td>{status}</td>
        </tr>
        """

    if not rows:
        rows = """
        <tr>
            <td colspan="4">No open issues from this period.</td>
        </tr>
        """

    html = f"""
    <h2>Jira Monday Brief</h2>

    <p>
        <strong>Project:</strong> {PROJECT}<br>
        <strong>Reporting period:</strong> {start} to {display_end}
    </p>

    <h3>
        Created: {len(created)} |
        Resolved: {len(resolved)} |
        Still Open: {len(open_issues)}
    </h3>

    <h3>Open Issues</h3>

    <table border="1" cellpadding="8" cellspacing="0">
        <tr>
            <th>Issue</th>
            <th>Summary</th>
            <th>Priority</th>
            <th>Status</th>
        </tr>
        {rows}
    </table>

    <p>
        <small>Generated automatically using the Jira REST API.</small>
    </p>
    """

    message = EmailMessage()
    message["Subject"] = f"Jira Monday Brief - {PROJECT}"
    message["From"] = SMTP_USER
    message["To"] = RECIPIENT

    message.set_content(
        f"Project: {PROJECT}\n"
        f"Period: {start} to {display_end}\n"
        f"Created: {len(created)}\n"
        f"Resolved: {len(resolved)}\n"
        f"Still Open: {len(open_issues)}"
    )

    message.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(
            SMTP_HOST,
            smtp_port,
            timeout=20,
        ) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(message)

    except Exception as error:
        die("EMAIL_FAILED", str(error))

    print(f"[PASS] Email sent to {RECIPIENT}")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--send-email", action="store_true")

    parser.add_argument(
        "--period",
        choices=[
            "previous-week",
            "previous-2-weeks",
            "previous-30-days",
            "custom",
        ],
        default="previous-week",
    )

    parser.add_argument("--start", type=parse_date)
    parser.add_argument("--end", type=parse_date)

    args = parser.parse_args()

    if args.smoke_test:
        smoke_test()
        return

    start, end = reporting_period(
        args.period,
        args.start,
        args.end,
    )

    created, resolved, open_issues = get_report(
        start,
        end,
    )

    print_report(
        start,
        end,
        created,
        resolved,
        open_issues,
    )

    if args.send_email:
        send_email(
            start,
            end,
            created,
            resolved,
            open_issues,
        )


if __name__ == "__main__":
    main()