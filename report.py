import html
import json
import os
import smtplib
import ssl
import sys
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import requests


REPORT_TIMEZONE = "Europe/Berlin"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_JIRA_ATTEMPTS = 3


class ReportError(Exception):
    """Expected report-generation failure with a reviewer-friendly message."""


def log(level: str, message: str) -> None:
    timestamp = datetime.now(ZoneInfo(REPORT_TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} [{level}] {message}", flush=True)


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name, str(default)).lower()
    return value in {"1", "true", "yes", "on"}


def load_config() -> dict:
    config = {
        "jira_url": env("JIRA_URL").rstrip("/"),
        "jira_email": env("JIRA_EMAIL"),
        "jira_api_token": env("JIRA_API_TOKEN"),
        "project_key": env("JIRA_PROJECT_KEY"),
        "report_recipient": env("REPORT_RECIPIENT"),
        "smtp_host": env("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(env("SMTP_PORT", "587")),
        "smtp_username": env("SMTP_USERNAME"),
        "smtp_password": env("SMTP_PASSWORD"),
    }

    required = {
        "JIRA_URL": config["jira_url"],
        "JIRA_EMAIL": config["jira_email"],
        "JIRA_API_TOKEN": config["jira_api_token"],
        "JIRA_PROJECT_KEY": config["project_key"],
        "REPORT_RECIPIENT": config["report_recipient"],
        "SMTP_USERNAME": config["smtp_username"],
        "SMTP_PASSWORD": config["smtp_password"],
    }

    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ReportError("CONFIG_MISSING: " + ", ".join(missing))

    if not config["jira_url"].startswith(("https://", "http://")):
        raise ReportError("CONFIG_INVALID: JIRA_URL must include https://")

    return config


def create_jira_session(config: dict) -> requests.Session:
    session = requests.Session()
    session.auth = (config["jira_email"], config["jira_api_token"])
    session.headers.update(
        {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    )
    return session


def jira_request(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    """Call Jira with short exponential backoff for transient failures."""
    last_response = None

    for attempt in range(1, MAX_JIRA_ATTEMPTS + 1):
        try:
            response = session.request(method, url, timeout=20, **kwargs)
            last_response = response
        except requests.exceptions.Timeout as exc:
            if attempt == MAX_JIRA_ATTEMPTS:
                raise ReportError("JIRA_TIMEOUT: Jira did not respond within 20 seconds.") from exc
            delay = 2 ** (attempt - 1)
            log("WARN", f"Jira request timed out. Retrying in {delay}s.")
            time.sleep(delay)
            continue
        except requests.exceptions.RequestException as exc:
            raise ReportError(f"JIRA_CONNECTION_FAILED: {exc}") from exc

        if response.status_code not in RETRYABLE_STATUS_CODES:
            return response

        if attempt == MAX_JIRA_ATTEMPTS:
            return response

        retry_after = response.headers.get("Retry-After")
        try:
            delay = int(retry_after) if retry_after else 2 ** (attempt - 1)
        except ValueError:
            delay = 2 ** (attempt - 1)

        delay = max(1, min(delay, 10))
        log("WARN", f"Jira returned HTTP {response.status_code}. Retrying in {delay}s.")
        time.sleep(delay)

    if last_response is not None:
        return last_response

    raise ReportError("JIRA_REQUEST_FAILED: No response received from Jira.")


def validate_jira_authentication(session: requests.Session, config: dict) -> None:
    response = jira_request(session, "GET", f'{config["jira_url"]}/rest/api/3/myself')

    if response.status_code == 401:
        raise ReportError("JIRA_AUTH_FAILED: Verify JIRA_EMAIL and JIRA_API_TOKEN.")
    if response.status_code == 403:
        raise ReportError("JIRA_ACCESS_DENIED: Jira denied access for the authenticated account.")
    if response.status_code != 200:
        raise ReportError(f"JIRA_AUTH_CHECK_FAILED: Jira returned HTTP {response.status_code}.")

    display_name = response.json().get("displayName", "Unknown user")
    log("PASS", f"Authenticated with Jira as {display_name}")


def get_project(session: requests.Session, config: dict) -> dict:
    response = jira_request(
        session,
        "GET",
        f'{config["jira_url"]}/rest/api/3/project/{config["project_key"]}',
    )

    if response.status_code == 404:
        raise ReportError(
            f'PROJECT_NOT_FOUND: Project {config["project_key"]} was not found or is not accessible.'
        )
    if response.status_code == 403:
        raise ReportError("PROJECT_ACCESS_DENIED: Check the Jira Browse Projects permission.")
    if response.status_code != 200:
        raise ReportError(f"PROJECT_CHECK_FAILED: Jira returned HTTP {response.status_code}.")

    project = response.json()
    log("PASS", f'Project validated: {project.get("key")} - {project.get("name")}')
    return project


def get_project_statuses(session: requests.Session, config: dict) -> list[str]:
    """Return unique project workflow status names from Jira."""
    response = jira_request(
        session,
        "GET",
        f'{config["jira_url"]}/rest/api/3/project/{config["project_key"]}/statuses',
    )

    if response.status_code == 403:
        raise ReportError("STATUS_ACCESS_DENIED: Jira denied access to project statuses.")
    if response.status_code == 404:
        raise ReportError("STATUS_LOOKUP_FAILED: Project was not found or is not accessible.")
    if response.status_code != 200:
        raise ReportError(f"STATUS_LOOKUP_FAILED: Jira returned HTTP {response.status_code}.")

    statuses = []
    seen = set()

    for issue_type in response.json():
        for status in issue_type.get("statuses", []):
            name = status.get("name")
            if name and name not in seen:
                seen.add(name)
                statuses.append(name)

    log("PASS", "Project statuses discovered: " + ", ".join(statuses))
    return statuses


def wait_until_scheduled_target() -> None:
    """
    Scheduled GitHub runs are requested at 09:37 Europe/Berlin. Once the
    hosted runner and Python process are already alive, this function holds
    report generation until the local Berlin clock reaches 10:00:00.
    """
    if not env_bool("SCHEDULED_RUN", False):
        return

    timezone = ZoneInfo(REPORT_TIMEZONE)
    now = datetime.now(timezone)
    target = now.replace(hour=10, minute=0, second=0, microsecond=0)

    if now.weekday() != 0:
        log("WARN", f"Expected Monday scheduled run, got {now.strftime('%A')}; continuing.")
        return

    if now >= target:
        late_seconds = (now - target).total_seconds()
        log("WARN", f"Runner became available {late_seconds:.2f}s after 10:00; running immediately.")
        return

    wait_seconds = (target - now).total_seconds()
    log("INFO", f"Runner ready early at {now.strftime('%H:%M:%S')}; waiting {int(wait_seconds)}s until 10:00:00 Europe/Berlin.")

    # Sleep efficiently for most of the wait, then use short sleeps close to
    # the target so the gate releases very near 10:00:00 without busy-waiting.
    if wait_seconds > 2:
        time.sleep(wait_seconds - 1.5)

    while True:
        now = datetime.now(timezone)
        remaining = (target - now).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(0.05, remaining))

    actual = datetime.now(timezone)
    drift = (actual - target).total_seconds()
    log("PASS", f"10:00 scheduling gate released at {actual.strftime('%H:%M:%S.%f')[:-3]} (drift {drift:.3f}s).")


def get_reporting_period(period_type: str, custom_start: str = "", custom_end: str = "") -> dict:
    today = datetime.now(ZoneInfo(REPORT_TIMEZONE)).date()
    current_monday = today - timedelta(days=today.weekday())

    if period_type == "current":
        start = current_monday
        display_end = today
        end_exclusive = today + timedelta(days=1)
        label = "Current Report"

    elif period_type == "previous_week":
        start = current_monday - timedelta(days=7)
        end_exclusive = current_monday
        display_end = current_monday - timedelta(days=1)
        label = "Previous Week"

    elif period_type == "previous_2_weeks":
        start = current_monday - timedelta(days=14)
        end_exclusive = current_monday
        display_end = current_monday - timedelta(days=1)
        label = "Previous 2 Weeks"

    elif period_type == "previous_30_days":
        start = today - timedelta(days=29)
        display_end = today
        end_exclusive = today + timedelta(days=1)
        label = "Previous 30 Days"

    elif period_type == "custom":
        if not custom_start or not custom_end:
            raise ReportError(
                "DATE_RANGE_INCOMPLETE: Custom Range requires CUSTOM_START and CUSTOM_END."
            )

        try:
            start = date.fromisoformat(custom_start)
            display_end = date.fromisoformat(custom_end)
        except ValueError as exc:
            raise ReportError("DATE_RANGE_INVALID: Dates must use YYYY-MM-DD.") from exc

        if display_end < start:
            raise ReportError("DATE_RANGE_INVALID: End date cannot be before start date.")

        end_exclusive = display_end + timedelta(days=1)
        label = "Custom Range"

    else:
        raise ReportError(f"REPORT_PERIOD_INVALID: Unsupported period '{period_type}'.")

    return {
        "label": label,
        "start": start,
        "display_end": display_end,
        "end_exclusive": end_exclusive,
    }


def get_selected_statuses(valid_statuses: list[str]) -> list[str]:
    """Translate GitHub checkbox inputs into Jira status names, then validate them."""
    if env_bool("ALL_STATUSES", True):
        return []

    selected = []
    requested = [
        ("STATUS_TO_DO", "To Do"),
        ("STATUS_IN_PROGRESS", "In Progress"),
        ("STATUS_DONE", "Done"),
    ]

    for env_name, status_name in requested:
        if env_bool(env_name):
            selected.append(status_name)

    if not selected:
        # Friendly fallback: no boxes selected means all statuses.
        return []

    invalid = [status for status in selected if status not in valid_statuses]
    if invalid:
        raise ReportError(
            "STATUS_FILTER_INVALID: "
            + ", ".join(invalid)
            + ". Valid Jira statuses are: "
            + ", ".join(valid_statuses)
        )

    return selected


def jql_quote(value: str) -> str:
    safe = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{safe}"'


def make_status_clause(selected_statuses: list[str]) -> str:
    if not selected_statuses:
        return ""
    values = ", ".join(jql_quote(status) for status in selected_statuses)
    return f" AND status IN ({values})"


def search_issues(session: requests.Session, config: dict, jql: str) -> list[dict]:
    """Search all matching Jira issues using enhanced JQL pagination."""
    url = f'{config["jira_url"]}/rest/api/3/search/jql'
    issues = []
    next_page_token = None

    while True:
        payload = {
            "jql": jql,
            "maxResults": 100,
            "fields": [
                "summary",
                "status",
                "priority",
                "created",
                "resolutiondate",
            ],
        }

        if next_page_token:
            payload["nextPageToken"] = next_page_token

        response = jira_request(session, "POST", url, json=payload)

        if response.status_code == 400:
            raise ReportError("JQL_INVALID: Jira rejected the generated JQL query.")
        if response.status_code == 401:
            raise ReportError("JIRA_AUTH_FAILED: Authentication failed during issue search.")
        if response.status_code == 403:
            raise ReportError("JIRA_SEARCH_ACCESS_DENIED: Jira denied issue-search access.")
        if response.status_code == 429:
            raise ReportError("JIRA_RATE_LIMITED: Jira rate limit persisted after retries.")
        if response.status_code >= 500:
            raise ReportError(
                f"JIRA_TEMPORARY_FAILURE: Jira returned HTTP {response.status_code} after retries."
            )
        if response.status_code != 200:
            raise ReportError(f"JIRA_SEARCH_FAILED: Jira returned HTTP {response.status_code}.")

        data = response.json()
        issues.extend(data.get("issues", []))

        next_page_token = data.get("nextPageToken")
        if data.get("isLast") is True or not next_page_token:
            break

    return issues


def collect_metrics(
    session: requests.Session,
    config: dict,
    period: dict,
    selected_statuses: list[str],
) -> dict:
    start = period["start"].strftime("%Y-%m-%d")
    end = period["end_exclusive"].strftime("%Y-%m-%d")
    project = jql_quote(config["project_key"])
    status_filter = make_status_clause(selected_statuses)

    created_jql = (
        f"project = {project} "
        f'AND created >= "{start}" '
        f'AND created < "{end}"'
        f"{status_filter} "
        "ORDER BY created DESC"
    )

    resolved_jql = (
        f"project = {project} "
        f'AND resolutiondate >= "{start}" '
        f'AND resolutiondate < "{end}"'
        f"{status_filter} "
        "ORDER BY resolutiondate DESC"
    )

    still_open_jql = (
        f"project = {project} "
        f'AND created >= "{start}" '
        f'AND created < "{end}" '
        "AND resolution IS EMPTY"
        f"{status_filter} "
        "ORDER BY priority DESC, created DESC"
    )

    log("INFO", "Querying created issues")
    created = search_issues(session, config, created_jql)

    log("INFO", "Querying resolved issues")
    resolved = search_issues(session, config, resolved_jql)

    log("INFO", "Querying still-open issues")
    still_open = search_issues(session, config, still_open_jql)

    return {
        "created": created,
        "resolved": resolved,
        "open": still_open,
    }


def build_email_html(
    config: dict,
    project: dict,
    period: dict,
    metrics: dict,
    selected_statuses: list[str],
    generated_at: str,
) -> str:
    project_name = html.escape(project.get("name", config["project_key"]))
    status_text = ", ".join(selected_statuses) if selected_statuses else "All Statuses"

    rows = []
    for issue in metrics["open"]:
        fields = issue.get("fields", {})
        key = html.escape(issue.get("key", ""))
        summary = html.escape(fields.get("summary", ""))
        status = html.escape((fields.get("status") or {}).get("name", "Unknown"))
        priority = html.escape((fields.get("priority") or {}).get("name", "Not set"))
        issue_url = f'{config["jira_url"]}/browse/{key}'

        rows.append(
            f"""
            <tr>
              <td style="padding:8px;border-bottom:1px solid #dfe1e6">
                <a href="{issue_url}">{key}</a>
              </td>
              <td style="padding:8px;border-bottom:1px solid #dfe1e6">{summary}</td>
              <td style="padding:8px;border-bottom:1px solid #dfe1e6">{status}</td>
              <td style="padding:8px;border-bottom:1px solid #dfe1e6">{priority}</td>
            </tr>
            """
        )

    if not rows:
        rows.append(
            '<tr><td colspan="4" style="padding:12px">No matching unresolved issues.</td></tr>'
        )

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:760px;margin:auto;color:#172b4d">
      <h2>Jira Monday Brief</h2>
      <p><strong>{project_name}</strong> ({html.escape(config["project_key"])})</p>
      <p>Reporting period: {period["start"]} &rarr; {period["display_end"]}</p>
      <p>Status filter: {html.escape(status_text)}</p>
      <p style="color:#6b778c;font-size:13px">
        Generated: {generated_at} ({REPORT_TIMEZONE})
      </p>

      <table width="100%" cellpadding="14"
             style="background:#f4f5f7;text-align:center;margin:20px 0">
        <tr>
          <td><strong style="font-size:28px">{len(metrics["created"])}</strong><br>Created</td>
          <td><strong style="font-size:28px">{len(metrics["resolved"])}</strong><br>Resolved</td>
          <td><strong style="font-size:28px">{len(metrics["open"])}</strong><br>Still Open</td>
        </tr>
      </table>

      <h3>Still Open</h3>
      <table width="100%" cellspacing="0">
        <tr>
          <th align="left">Issue</th>
          <th align="left">Summary</th>
          <th align="left">Status</th>
          <th align="left">Priority</th>
        </tr>
        {''.join(rows)}
      </table>

      <p style="color:#6b778c;font-size:12px;margin-top:25px">
        Generated by Python using the Jira Cloud REST API.
      </p>
    </div>
    """


def send_email(
    config: dict,
    project: dict,
    period: dict,
    metrics: dict,
    selected_statuses: list[str],
    generated_at: str,
) -> None:
    status_text = ", ".join(selected_statuses) if selected_statuses else "All Statuses"

    message = EmailMessage()
    message["From"] = config["smtp_username"]
    message["To"] = config["report_recipient"]
    message["Subject"] = (
        f'Jira Monday Brief - {config["project_key"]} - '
        f'{period["start"]} to {period["display_end"]}'
    )

    message.set_content(
        "Jira Monday Brief\n\n"
        f'Project: {project.get("name")} ({config["project_key"]})\n'
        f'Period: {period["start"]} to {period["display_end"]}\n'
        f"Status filter: {status_text}\n"
        f'Created: {len(metrics["created"])}\n'
        f'Resolved: {len(metrics["resolved"])}\n'
        f'Still Open: {len(metrics["open"])}\n'
        f"Generated: {generated_at} ({REPORT_TIMEZONE})"
    )

    message.add_alternative(
        build_email_html(
            config,
            project,
            period,
            metrics,
            selected_statuses,
            generated_at,
        ),
        subtype="html",
    )

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(
            config["smtp_host"],
            config["smtp_port"],
            timeout=20,
        ) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(config["smtp_username"], config["smtp_password"])
            smtp.send_message(message)
    except Exception as exc:
        raise ReportError(f"EMAIL_DELIVERY_FAILED: {exc}") from exc

    log("PASS", f'Report email sent to {config["report_recipient"]}')


def write_github_summary(
    config: dict,
    project: dict,
    period: dict,
    metrics: dict,
    selected_statuses: list[str],
    generated_at: str,
) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    status_text = ", ".join(selected_statuses) if selected_statuses else "All Statuses"

    lines = [
        "# Jira Monday Brief",
        "",
        f'**Project:** {project.get("name")} (`{config["project_key"]}`)',
        "",
        f'**Reporting period:** {period["start"]} → {period["display_end"]}',
        "",
        f"**Status filter:** {status_text}",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f'| Created | {len(metrics["created"])} |',
        f'| Resolved | {len(metrics["resolved"])} |',
        f'| Still Open | {len(metrics["open"])} |',
        "",
        f"Generated: {generated_at} ({REPORT_TIMEZONE})",
    ]

    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> int:
    try:
        log("INFO", "Starting Jira Monday Brief")

        config = load_config()
        wait_until_scheduled_target()
        session = create_jira_session(config)

        validate_jira_authentication(session, config)
        project = get_project(session, config)
        valid_statuses = get_project_statuses(session, config)

        period_type = env("REPORT_PERIOD", "previous_week")
        custom_start = env("CUSTOM_START")
        custom_end = env("CUSTOM_END")

        period = get_reporting_period(period_type, custom_start, custom_end)
        selected_statuses = get_selected_statuses(valid_statuses)

        log(
            "INFO",
            f'Report period: {period["start"]} to {period["display_end"]} '
            f'({period["label"]})',
        )
        log(
            "INFO",
            "Status filter: "
            + (", ".join(selected_statuses) if selected_statuses else "All Statuses"),
        )

        metrics = collect_metrics(session, config, period, selected_statuses)

        generated_at = datetime.now(ZoneInfo(REPORT_TIMEZONE)).strftime(
            "%d %b %Y, %H:%M:%S"
        )

        log(
            "PASS",
            f'Report calculated: created={len(metrics["created"])}, '
            f'resolved={len(metrics["resolved"])}, '
            f'still_open={len(metrics["open"])}',
        )

        send_email(
            config,
            project,
            period,
            metrics,
            selected_statuses,
            generated_at,
        )

        write_github_summary(
            config,
            project,
            period,
            metrics,
            selected_statuses,
            generated_at,
        )

        output = {
            "project": config["project_key"],
            "period": {
                "label": period["label"],
                "start": str(period["start"]),
                "end": str(period["display_end"]),
            },
            "status_filter": selected_statuses or ["All Statuses"],
            "created": len(metrics["created"]),
            "resolved": len(metrics["resolved"]),
            "still_open": len(metrics["open"]),
            "generated_at": generated_at,
            "timezone": REPORT_TIMEZONE,
        }

        print(json.dumps(output, indent=2))
        log("PASS", "Jira Monday Brief completed successfully")
        return 0

    except ReportError as exc:
        log("FAIL", str(exc))
        return 1
    except Exception as exc:
        log("FAIL", f"UNEXPECTED_ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
