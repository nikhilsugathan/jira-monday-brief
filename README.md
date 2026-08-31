# Jira Monday Brief

A Python-based Jira Cloud reporting workflow for the Scalable Capital Cloud Application Administrator technical assignment.

## Objective

The solution generates a Jira Cloud report for a selected project showing:

- issues created during the selected reporting period;
- issues resolved during the selected reporting period;
- issues created during the selected reporting period that are still unresolved when the report runs;
- direct Jira links, current status and priority for still-open issues.

The scheduled report targets every Monday at **10:00 Europe/Berlin** and emails the result to the configured report recipient.

The solution uses the **Jira Cloud REST API v3** directly. **Jira Automation is not used.**

## Demo and source

- Operations dashboard: https://nikhilsugathan.github.io/jira-monday-brief/
- Source repository: https://github.com/nikhilsugathan/jira-monday-brief
- GitHub Actions workflow: https://github.com/nikhilsugathan/jira-monday-brief/actions/workflows/jira-report.yml
- Jira test project: `CAO` — Cloud Application Operations

## Architecture

```text
GitHub Pages dashboard
        |
        v
GitHub Actions
        |
        +-----------------------------+
        |                             |
Manual report                  Monday schedule
                               09:37 runner request
                               10:00 report start
        |                             |
        +--------------+--------------+
                       |
                       v
               GitHub-hosted runner
                       |
                       v
                   report.py
                       |
                       v
            Jira Cloud REST API v3
                       |
            +----------+----------+
            |          |          |
         Created    Resolved   Still Open
            +----------+----------+
                       |
                       v
               HTML email report
                       |
                       v
               Report recipient
```

There is no permanent VM, database, container or application server. GitHub provides an ephemeral hosted runner only while the workflow is active.

## Main files

- `report.py` — Jira access validation, reporting-period logic, status selection, JQL queries, pagination, report calculations, HTML email generation, SMTP delivery and retry/error handling.
- `.github/workflows/jira-report.yml` — manual workflow inputs, Monday schedule, Python runtime and secret injection.
- `requirements.txt` — Python dependencies.
- `.env.example` — configuration template containing placeholder values only.
- `docs/index.html` — GitHub Pages operations dashboard.

## Tools and external services

### Jira Cloud

Jira Cloud is the report data source. The implementation uses Jira REST API v3.

Endpoints used:

```text
GET  /rest/api/3/myself
GET  /rest/api/3/project/{projectKey}
GET  /rest/api/3/project/{projectKey}/statuses
POST /rest/api/3/search/jql
```

### GitHub Actions

GitHub Actions provides:

- scheduled Monday execution;
- manual `workflow_dispatch` execution;
- ephemeral `ubuntu-latest` compute;
- Python 3.12 runtime;
- runtime secret injection;
- workflow logs and execution history;
- generated job summaries.

### GitHub Pages

`docs/index.html` provides a static operations dashboard showing Berlin time, the next scheduled report and the latest workflow result. The dashboard contains no privileged credentials.

### SMTP

SMTP is used to deliver the final HTML report to the configured recipient using STARTTLS.

## Reporting rules and assumptions

All report date calculations use `Europe/Berlin`.

**Past week** is interpreted as the previous completed Monday-Sunday calendar week:

```text
Previous Monday 00:00 inclusive
to
Current Monday 00:00 exclusive
```

The exclusive end boundary avoids double-counting issues exactly at a date boundary.

**Created** means the Jira `created` timestamp falls inside the selected reporting period.

**Resolved** means the Jira `resolutiondate` falls inside the selected reporting period. The issue may have been created earlier.

**Still Open** means the issue was created during the selected reporting period and `resolution IS EMPTY` when the report is generated.

Additional assumptions:

- the configured `REPORT_RECIPIENT` represents the project lead/report recipient;
- the Jira API identity can see all issues that are expected to be counted;
- issue-level Jira security can reduce counts if the reporting identity cannot see an issue;
- the Monday schedule is operational rather than hard real-time because GitHub-hosted runner allocation can be delayed;
- scheduled Monday reports use **Previous Week** and **All Statuses**.

## Manual report options

Manual workflow runs support:

```text
Current Report
Previous Week
Previous 2 Weeks
Previous 30 Days
Custom Range
```

Status selections:

```text
All Statuses
To Do
In Progress
Done
```

For a custom range, enter both dates in `YYYY-MM-DD`.

Requested status names are checked against the statuses returned by Jira before the report queries run.

## Scheduling

The workflow requests a GitHub-hosted runner at 09:37 every Monday:

```yaml
schedule:
  - cron: "37 9 * * 1"
    timezone: "Europe/Berlin"
```

If the runner is available before 10:00, `report.py` waits until **10:00:00 Europe/Berlin** before querying Jira and generating the report.

If the runner is allocated after 10:00, the report starts immediately and logs the delay.

## Reproduction steps

### 1. Clone the repository

```powershell
git clone https://github.com/nikhilsugathan/jira-monday-brief.git
cd jira-monday-brief
```

### 2. Create a local Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Optional syntax check:

```powershell
python -m py_compile report.py
```

### 3. Create Jira access

Create or select a Jira Cloud project and create an Atlassian API token for an account that can browse the project.

The Jira account needs read access only:

- Browse Projects;
- visibility of the issues being reported;
- permission to search issues;
- permission to read project statuses.

### 4. Configure GitHub Actions Secrets

Open:

**Repository → Settings → Secrets and variables → Actions**

Create:

```text
JIRA_URL
JIRA_EMAIL
JIRA_API_TOKEN
JIRA_PROJECT_KEY
REPORT_RECIPIENT
SMTP_HOST
SMTP_PORT
SMTP_USERNAME
SMTP_PASSWORD
```

### 5. Run a manual report

Open:

**GitHub → Actions → Jira Monday Brief → Run workflow**

For a standard verification run:

```text
Reporting period: Previous Week
All Statuses: enabled
```

Run the workflow, open the generated job and confirm **Generate Jira Monday Brief** succeeds.

Then confirm the report email reaches `REPORT_RECIPIENT`.

## Compute, permissions and network

### Compute

The report uses a GitHub-hosted `ubuntu-latest` runner with Python 3.12. The runner exists only for the workflow execution.

No persistent compute resource is required.

### GitHub permissions

The workflow token is restricted to:

```yaml
permissions:
  contents: read
```

### Network connections

The GitHub-hosted runner makes outbound connections to:

- Jira Cloud over HTTPS / TCP 443;
- the SMTP provider over STARTTLS / TCP 587;
- GitHub and Python package infrastructure over HTTPS / TCP 443.

No custom inbound network connection is required.

## Security

Real credentials are not stored in the repository.

`.gitignore` excludes `.env`, and `.env.example` contains placeholders only.

Do not commit or publish:

```text
.env
JIRA_API_TOKEN
SMTP_PASSWORD
Gmail App Password
GitHub write token
```

The public GitHub Pages dashboard does not call the authenticated workflow-dispatch API directly. Manual execution stays inside GitHub's authenticated Actions interface so that no write-capable token is exposed in browser JavaScript.

## Error handling

`report.py` handles configuration errors, Jira authentication and authorization failures, inaccessible projects, invalid reporting periods and statuses, Jira rate limiting, temporary Jira failures, connection errors, timeouts and SMTP delivery failures.

Retryable Jira responses are:

```text
429
500
502
503
504
```

They are retried up to three attempts. `Retry-After` is respected where supplied; otherwise the script uses a short backoff.

## Final validation

The final end-to-end manual validation used:

```text
Project: Cloud Application Operations (CAO)
Reporting period: 2026-08-02 to 2026-08-31
Status filter: All Statuses
Created: 6
Resolved: 2
Still Open: 4
Workflow: SUCCESS
Email delivery: SUCCESS
```

The Operations, Validation & Handover Runbook contains the final evidence screenshots:

1. Operations dashboard showing the healthy state and successful workflow.
2. Successful GitHub Actions execution and generated report summary.
3. Received Jira Monday Brief HTML email.

## Documentation

- Service Overview & Documentation Index: https://nikhilsugathan.atlassian.net/wiki/spaces/OPERATIONS/pages/753667
- Architecture, Data Flow & Technical Design: https://nikhilsugathan.atlassian.net/wiki/spaces/OPERATIONS/pages/720931
- Operations, Validation & Handover Runbook: https://nikhilsugathan.atlassian.net/wiki/spaces/OPERATIONS/pages/753694
- Troubleshooting & Error Handling: https://nikhilsugathan.atlassian.net/wiki/spaces/OPERATIONS/pages/688144
