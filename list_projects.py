import os
import sys

import requests
from dotenv import load_dotenv


load_dotenv()

jira_url = os.getenv("JIRA_URL", "").rstrip("/")
jira_email = os.getenv("JIRA_EMAIL")
jira_token = os.getenv("JIRA_API_TOKEN")


print("Checking Jira projects visible to this account...")


try:
    response = requests.get(
        f"{jira_url}/rest/api/3/project/search",
        auth=(jira_email, jira_token),
        headers={"Accept": "application/json"},
        params={"maxResults": 50},
        timeout=15,
    )

except requests.exceptions.RequestException as error:
    print(f"ERROR: {error}")
    sys.exit(1)


print(f"HTTP {response.status_code}")


if response.status_code != 200:
    print(response.text[:500])
    sys.exit(1)


data = response.json()
projects = data.get("values", [])


if not projects:
    print("No Jira projects are visible to this account.")
    sys.exit(0)


print()
print("VISIBLE JIRA PROJECTS")
print("=" * 70)

for project in projects:
    print(
        f"{project.get('key')} | "
        f"{project.get('name')} | "
        f"ID={project.get('id')}"
    )
