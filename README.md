# Jira Monday Brief - Scalable Capital Test Assignment

## 1. Objective

This solution creates a weekly Jira Cloud report for a selected project using the Jira REST API. The report shows:

- issues created during the reporting period
- issues resolved during the reporting period
- issues created during the reporting period that are still unresolved when the report runs
- links to currently open Jira issues, including summary, priority, and status

The default report is generated every Monday at 10:00 Europe/Berlin and emailed to the configured project lead.

Jira Automation is not used.

## 2. Demo and Source

- Operations dashboard: https://nikhilsugathan.github.io/jira-monday-brief/
- Source repository: https://github.com/nikhilsugathan/jira-monday-brief
- Jira test project: `CAO` - Cloud Application Operations

The GitHub Pages dashboard is a read-only operational front end. Manual report execution is performed through the authenticated GitHub Actions `workflow_dispatch` interface. This avoids exposing Jira, SMTP, or GitHub credentials in browser-side code.

## 3. Architecture

```text
Technical user / project admin
            |
            v
   GitHub Pages dashboard
   - service health
   - last workflow run
   - next scheduled run
   - links to operations/docs
            |
            | manual execution uses GitHub authentication
            v
      GitHub Actions
   - schedule: Monday 10:00
   - timezone: Europe/Berlin
   - manual workflow_dispatch
   - ephemeral ubuntu-latest runner
   - GitHub Actions Secrets
            |
            v
       jira_report.py
            |
            | HTTPS 443
            v
      Jira Cloud REST API v3
            |
            v
 Created / Resolved / Still Open
            |
            v
       HTML email report
            |
            | STARTTLS SMTP 587
            v
        Project Lead
```

There is no persistent VM, database, container, or application server.

## 4. Components

### Jira Cloud

Test site:

```text
https://nikhilsugathan.atlassian.net
```

Project:

```text
Cloud Application Operations
Key: CAO
```

The API identity requires access to the project and the `Browse Projects` permission.

### Python report engine

`jira_report.py`:

- authenticates to Jira Cloud
- validates connectivity and permissions
- queries issues using Jira REST API v3
- supports Jira pagination
- calculates created, resolved, and still-open counts
- creates an HTML email
- includes clickable Jira issue links
- supports several report periods
- exits with explicit error codes/messages when checks fail

### GitHub Actions

`.github/workflows/weekly-report.yml` provides:

- scheduled Monday execution
- `Europe/Berlin` timezone
- manual report execution
- short-lived GitHub-hosted compute
- secret injection at runtime
- execution logs
- version-controlled workflow history

### GitHub Pages

`docs/index.html` provides a lightweight operational dashboard.

It contains no Jira API token, SMTP password, or other secret.

## 5. Reporting Rules and Assumptions

The phrase "past week" is interpreted as the previous completed calendar week:

```text
Monday 00:00 inclusive
to
following Monday 00:00 exclusive
```

Using an exclusive upper boundary avoids double-counting issues exactly at midnight.

### Created

```jql
project = "CAO"
AND created >= "<start>"
AND created < "<end>"
```

### Resolved

```jql
project = "CAO"
AND resolutiondate >= "<start>"
AND resolutiondate < "<end>"
```

### Still Open

```jql
project = "CAO"
AND created >= "<start>"
AND created < "<end>"
AND resolution IS EMPTY
```

"Still Open" means an issue that was created during the reporting period and remains unresolved at report-generation time.

## 6. Supported Report Periods

```text
previous-week
previous-2-weeks
previous-30-days
custom
```

Custom start/end dates use `YYYY-MM-DD`. The operator-facing end date is inclusive.

Example:

```powershell
python jira_report.py --period custom --start 2026-08-27 --end 2026-08-27
```

Observed test result:

```text
Created:          6
Resolved:         2
Still open:       4
```

## 7. Prerequisites

- Jira Cloud site and project
- Jira API identity with project visibility
- GitHub repository
- SMTP account supporting STARTTLS
- Python 3.12 for local testing

## 8. Repository Structure

```text
jira-monday-brief/
|
|-- .github/
|   `-- workflows/
|       `-- weekly-report.yml
|
|-- docs/
|   `-- index.html
|
|-- .env.example
|-- .gitignore
|-- jira_report.py
|-- requirements.txt
`-- README.md
```

No local `.env` file or production credential should be committed.

## 9. Local Setup

```powershell
git clone https://github.com/nikhilsugathan/jira-monday-brief.git
cd jira-monday-brief

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

Copy-Item .env.example .env
notepad .env
```

Populate `.env`:

```text
JIRA_URL=https://your-site.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=<jira-api-token>
JIRA_PROJECT_KEY=CAO

SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=sender@example.com
SMTP_PASSWORD=<smtp-password>
REPORT_RECIPIENT=project-lead@example.com
```

## 10. Validate Jira Access

```powershell
python jira_report.py --smoke-test
```

Expected shape:

```text
JIRA SMOKE TEST
User:        <Jira user>
Project:     Cloud Application Operations (CAO)
Permission:  Browse Projects PASS
JQL search:  PASS
```

## 11. Generate Reports Locally

```powershell
python jira_report.py --period previous-week
python jira_report.py --period previous-2-weeks
python jira_report.py --period previous-30-days
python jira_report.py --period custom --start 2026-08-27 --end 2026-08-27
python jira_report.py --period previous-week --send-email
```

## 12. GitHub Actions

Workflow stages:

```text
Checkout repository
        |
        v
Set up Python 3.12
        |
        v
Install dependencies
        |
        v
Validate Jira access
        |
        v
Generate report
        |
        v
Email project lead
```

Scheduled execution:

```yaml
schedule:
  - cron: "0 10 * * 1"
    timezone: "Europe/Berlin"
```

Manual execution uses `workflow_dispatch` inputs for the report period and optional custom dates.

## 13. GitHub Secrets

```text
JIRA_URL
JIRA_EMAIL
JIRA_API_TOKEN
JIRA_PROJECT_KEY
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASSWORD
REPORT_RECIPIENT
```

Create them under:

```text
Repository -> Settings -> Secrets and variables -> Actions
```

Or with GitHub CLI:

```powershell
gh auth login
gh secret set -f .env
gh secret list
```

## 14. Network and Permissions

```text
GitHub Actions -> Jira Cloud        HTTPS/TCP 443
GitHub Actions -> SMTP service      STARTTLS/TCP 587
GitHub Actions -> GitHub services   HTTPS/TCP 443
GitHub Actions -> Python packages   HTTPS/TCP 443
```

Jira access must include:

```text
Browse Projects
Visibility of the issues being reported
```

Issue-level security can therefore affect counts if the API identity cannot see an issue.

## 15. Error Handling

Implemented failure paths include:

```text
CONFIG_MISSING
JIRA_CONNECTION_FAILED
JIRA_AUTH_FAILED
JIRA_ACCESS_DENIED
BROWSE_PROJECTS_DENIED
INVALID_DATE_RANGE
EMAIL_CONFIG_MISSING
EMAIL_CONFIG_INVALID
EMAIL_FAILED
```

The Jira API search follows `nextPageToken` pagination.

## 16. Validation Performed

### Normal weekly report

A previous-week run covering 17-23 August returned:

```text
Created:          0
Resolved:         0
Still open:       0
```

This was expected because the controlled CAO issues were created on 27 August.

### Controlled custom report

For:

```text
2026-08-27 to 2026-08-27
```

the report returned:

```text
Created:          6
Resolved:         2
Still open:       4
```

Open issues:

```text
CAO-6  Production dashboard unavailable
CAO-4  Monitoring alert requires threshold review
CAO-2  New starter missing application access
CAO-1  VPN access fails after MFA
```

The delivered HTML email includes clickable Jira issue keys.

## 17. Security Decisions

- credentials remain outside source code
- GitHub Actions Secrets are used for cloud execution
- `.env` is excluded from Git
- `.env.example` contains placeholders only
- GitHub Pages contains no secret
- manual cloud execution uses GitHub authentication
- no long-running public server is required

For production, the repository would normally be company-owned and controlled through GitHub organisation SSO/RBAC.

## 18. Handover and Recovery

The solution is stateless and configuration-driven.

A replacement administrator should:

1. obtain repository access
2. create/rotate Jira credentials
3. create/rotate SMTP credentials
4. update GitHub Actions Secrets
5. run a manual workflow
6. verify the email
7. revoke superseded credentials

Secret values are intentionally not retrievable after creation; rotation is preferred over recovering old values.

## 19. Operational Runbook

Normal operation requires no action.

Manual report:

```text
GitHub repository
-> Actions
-> Jira Monday Brief
-> Run workflow
```

Select a report period. For `custom`, provide start and end dates.

If Jira validation fails, check URL, API token, project key, Browse Projects permission and issue visibility.

If mail delivery fails, check SMTP host, port, credentials, STARTTLS support and recipient address.

## 20. Limitations and Production Considerations

GitHub Actions scheduled jobs can occasionally start later than the exact requested minute due to platform load. The workflow requests Monday 10:00 Europe/Berlin but is not a hard real-time scheduler.

The demo uses SMTP. A production company can replace it with an approved internal mail relay/API without changing the reporting logic.

Date-range customization is implemented. Type/priority filtering is not included in the submitted version to keep the solution small and reproducible.

The GitHub Pages dashboard is operational visibility only and does not directly call Jira.

## 21. Requirement Mapping

| Requirement | Implementation |
| --- | --- |
| Jira Cloud data | Jira REST API v3 |
| Created count | JQL `created` query |
| Resolved count | JQL `resolutiondate` query |
| Currently open | Created-in-period + `resolution IS EMPTY` |
| Monday 10:00 | GitHub Actions schedule, Europe/Berlin |
| Email project lead | SMTP/STARTTLS |
| No Jira Automation | Not used |
| Exact setup steps | This README |
| Programming code | `jira_report.py`, workflow YAML |
| Compute resources | Ephemeral GitHub-hosted runner |
| Network/permissions | Documented above |
| Architecture | Included above |
| External tool workflow | GitHub Actions + SMTP |
| Sample output | Included in final PDF/evidence |
| API error handling | Implemented |
| Jira links | Implemented |
| Date customization | Implemented |

## 22. Final Result

The final architecture is deliberately small:

```text
GitHub Pages + GitHub Actions + Python + Jira REST API + SMTP
```

The scheduled workload does not depend on a local workstation or continuously running server.
