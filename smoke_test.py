import os
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv


# ---------------------------------------------------------
# LOAD LOCAL CONFIGURATION
# ---------------------------------------------------------

load_dotenv()


# ---------------------------------------------------------
# LOGGING / DIAGNOSTICS
# ---------------------------------------------------------

def log(level, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} [{level}] {message}")


def fail(code, message, suggestion=None):
    log("FAIL", f"{code}: {message}")

    if suggestion:
        log("HELP", suggestion)

    sys.exit(1)


# ---------------------------------------------------------
# 1. CONFIGURATION VALIDATION
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# SHARED JIRA CONNECTION SETTINGS
# ---------------------------------------------------------

auth = (
    JIRA_EMAIL,
    JIRA_API_TOKEN
)

headers = {
    "Accept": "application/json"
}


# ---------------------------------------------------------
# 2. JIRA CONNECTIVITY / AUTHENTICATION TEST
# ---------------------------------------------------------

try:
    response = requests.get(
        f"{JIRA_URL}/rest/api/3/myself",
        auth=auth,
        headers=headers,
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


try:
    user = response.json()

except ValueError:
    fail(
        "JIRA_INVALID_RESPONSE",
        "Jira returned a response that could not be parsed as JSON."
    )


log(
    "PASS",
    f"Authenticated with Jira as "
    f"{user.get('displayName', 'Unknown user')}"
)


# ---------------------------------------------------------
# 3. PROJECT ACCESS VALIDATION
# ---------------------------------------------------------

log(
    "INFO",
    f"Checking access to Jira project {JIRA_PROJECT_KEY}"
)

project_url = (
    f"{JIRA_URL}/rest/api/3/project/{JIRA_PROJECT_KEY}"
)


try:
    response = requests.get(
        project_url,
        auth=auth,
        headers=headers,
        timeout=15,
    )

except requests.exceptions.Timeout:
    fail(
        "PROJECT_CHECK_TIMEOUT",
        "Jira project validation did not respond within 15 seconds.",
        "Check Jira availability and network connectivity."
    )

except requests.exceptions.RequestException as error:
    fail(
        "PROJECT_CHECK_FAILED",
        str(error),
        "Check Jira connectivity."
    )


if response.status_code == 401:
    fail(
        "JIRA_AUTH_FAILED",
        "Authentication failed while validating the Jira project.",
        "Verify JIRA_EMAIL and JIRA_API_TOKEN."
    )


if response.status_code == 404:
    fail(
        "PROJECT_NOT_FOUND",
        f"Project {JIRA_PROJECT_KEY} was not found or is not accessible.",
        "Verify JIRA_PROJECT_KEY and Browse Projects permission."
    )


if response.status_code == 403:
    fail(
        "PROJECT_ACCESS_DENIED",
        f"Access denied to Jira project {JIRA_PROJECT_KEY}.",
        "Verify that the Jira account has Browse Projects permission."
    )


if response.status_code != 200:
    fail(
        "PROJECT_CHECK_ERROR",
        f"Jira returned HTTP {response.status_code}.",
        response.text[:300]
    )


try:
    project = response.json()

except ValueError:
    fail(
        "PROJECT_INVALID_RESPONSE",
        "Jira returned project data that could not be parsed as JSON."
    )


project_name = project.get("name", "Unknown project")
project_key = project.get("key", JIRA_PROJECT_KEY)


log(
    "PASS",
    f"Project {project_key} is accessible: {project_name}"
)


# ---------------------------------------------------------
# 4. PROJECT PERMISSION VALIDATION
# ---------------------------------------------------------

log(
    "INFO",
    f"Checking Browse Projects permission for {project_key}"
)

permissions_url = f"{JIRA_URL}/rest/api/3/mypermissions"

permission_params = {
    "projectKey": project_key,
    "permissions": "BROWSE_PROJECTS",
}


try:
    response = requests.get(
        permissions_url,
        auth=auth,
        headers=headers,
        params=permission_params,
        timeout=15,
    )

except requests.exceptions.Timeout:
    fail(
        "PERMISSION_CHECK_TIMEOUT",
        "Jira permission check did not respond within 15 seconds.",
        "Check Jira availability and network connectivity."
    )

except requests.exceptions.RequestException as error:
    fail(
        "PERMISSION_CHECK_FAILED",
        str(error),
        "Check Jira connectivity."
    )


if response.status_code == 401:
    fail(
        "JIRA_AUTH_FAILED",
        "Authentication failed while checking Jira permissions.",
        "Verify JIRA_EMAIL and JIRA_API_TOKEN."
    )


if response.status_code == 404:
    fail(
        "PERMISSION_CONTEXT_NOT_FOUND",
        f"Permission context could not be resolved for project {project_key}.",
        "Verify the project key and project visibility."
    )


if response.status_code != 200:
    fail(
        "PERMISSION_CHECK_ERROR",
        f"Jira returned HTTP {response.status_code}.",
        response.text[:300]
    )


try:
    permission_data = response.json()

except ValueError:
    fail(
        "PERMISSION_INVALID_RESPONSE",
        "Jira returned permission data that could not be parsed as JSON."
    )


browse_permission = (
    permission_data
    .get("permissions", {})
    .get("BROWSE_PROJECTS", {})
)

has_browse_permission = browse_permission.get(
    "havePermission",
    False
)


if not has_browse_permission:
    fail(
        "BROWSE_PROJECTS_DENIED",
        f"The authenticated account does not have Browse Projects "
        f"permission for {project_key}.",
        "Grant Browse Projects permission through the Jira project "
        "permission scheme or an appropriate project role/group."
    )


log(
    "PASS",
    f"Browse Projects permission confirmed for {project_key}"
)

# ---------------------------------------------------------
# 5. JQL SEARCH TEST
# ---------------------------------------------------------

log(
    "INFO",
    f"Running sample JQL search against project {project_key}"
)


search_url = f"{JIRA_URL}/rest/api/3/search/jql"

jql = (
    f'project = "{project_key}" '
    f'ORDER BY created DESC'
)


params = {
    "jql": jql,
    "maxResults": 5,
    "fields": (
        "summary,"
        "status,"
        "priority,"
        "created,"
        "resolutiondate"
    ),
}


try:
    response = requests.get(
        search_url,
        auth=auth,
        headers=headers,
        params=params,
        timeout=15,
    )

except requests.exceptions.Timeout:
    fail(
        "JIRA_SEARCH_TIMEOUT",
        "Jira issue search did not respond within 15 seconds.",
        "Check Jira availability and network connectivity."
    )

except requests.exceptions.RequestException as error:
    fail(
        "JIRA_SEARCH_FAILED",
        str(error),
        "Check Jira connectivity."
    )


if response.status_code == 400:
    fail(
        "JQL_INVALID",
        "Jira rejected the JQL query.",
        "Review the generated JQL syntax."
    )


if response.status_code == 401:
    fail(
        "JIRA_AUTH_FAILED",
        "Authentication failed during Jira search.",
        "Verify JIRA_EMAIL and JIRA_API_TOKEN."
    )


if response.status_code == 403:
    fail(
        "JIRA_SEARCH_ACCESS_DENIED",
        f"Jira search access was denied for project {project_key}.",
        "Check project and issue permissions."
    )


if response.status_code != 200:
    fail(
        "JIRA_SEARCH_ERROR",
        f"Jira returned HTTP {response.status_code}.",
        response.text[:300]
    )


try:
    data = response.json()

except ValueError:
    fail(
        "JIRA_SEARCH_INVALID_RESPONSE",
        "Jira search returned data that could not be parsed as JSON."
    )


issues = data.get("issues", [])


log(
    "PASS",
    "JQL search completed successfully"
)


# ---------------------------------------------------------
# 6. SAMPLE ISSUE OUTPUT
# ---------------------------------------------------------

print()
print("=" * 75)
print("SAMPLE JIRA ISSUES")
print("=" * 75)


if not issues:
    print(
        f"Project {project_key} is valid and accessible, "
        "but currently contains no matching issues."
    )

else:
    for issue in issues:

        fields = issue.get("fields", {})

        status = fields.get("status") or {}
        priority = fields.get("priority") or {}

        issue_key = issue.get("key", "Unknown")
        summary = fields.get("summary", "Not set")
        status_name = status.get("name", "Not set")
        priority_name = priority.get("name", "Not set")
        created = fields.get("created", "Not set")
        resolved = (
            fields.get("resolutiondate")
            or "Not resolved"
        )

        print(f"Issue:      {issue_key}")
        print(f"Summary:    {summary}")
        print(f"Status:     {status_name}")
        print(f"Priority:   {priority_name}")
        print(f"Created:    {created}")
        print(f"Resolved:   {resolved}")
        print("-" * 75)


# ---------------------------------------------------------
# 7. FINAL SMOKE TEST RESULT
# ---------------------------------------------------------

print()
print("=" * 55)
print("JIRA MONDAY BRIEF - SMOKE TEST")
print("=" * 55)
print("Configuration       PASS")
print("Jira connectivity   PASS")
print("Authentication      PASS")
print("Project validation  PASS")
print("Browse Projects     PASS")
print("JQL search          PASS")
print("=" * 55)

log(
    "PASS",
    "Smoke test completed successfully"
)