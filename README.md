# Jira Monday Brief

A Python-based Jira Cloud reporting workflow for the Scalable Capital Cloud Application Administrator technical assignment.

## What it does

The workflow queries Jira Cloud through the Jira REST API and emails a report containing:

- issues created in the selected reporting period;
- issues resolved in the selected reporting period;
- issues created in the selected reporting period that are still unresolved at generation time;
- issue links, current status and priority for the still-open issues.

The scheduled production path targets every Monday at **10:00 Europe/Berlin** and always generates the **Previous Week** report. To reduce GitHub's documented top-of-hour delay risk, the hosted runner is requested at 09:37 and Python waits internally until 10:00 before querying Jira and generating the email.

The same GitHub Actions workflow also supports manual runs with:

- Current Report
- Previous Week
- Previous 2 Weeks
- Previous 30 Days
- Custom Range
- All Statuses
- To Do
- In Progress
- Done

## Architecture

```text
Manual GitHub Actions run                  Weekly schedule
(period/status inputs)                 Monday 10:00 Europe/Berlin
             \                                  /
              \                                /
               +------ GitHub Actions --------+
                           |
                           v
                       report.py
                           |
                           v
                    Jira Cloud REST API
                           |
                +----------+-----------+
                |          |           |
             Created    Resolved   Still Open
                +----------+-----------+
                           |
                           v
                     HTML email report
                           |
                           v
                       Project lead
```

There is no continuously running application server, VM, database or container. GitHub provides an ephemeral hosted runner only when the workflow executes.

## Files

- `report.py` — Jira REST API integration, report-period logic, status validation, pagination, metrics, email generation and error handling.
- `.github/workflows/jira-report.yml` — manual input form and Monday schedule.
- `requirements.txt` — Python dependency list.
- `.env.example` — local configuration template without secrets.

## Jira API usage

The implementation uses Jira Cloud REST API v3.

It validates:

1. Jira authentication using `/rest/api/3/myself`.
2. Project access using `/rest/api/3/project/{projectKey}`.
3. Project workflow statuses using `/rest/api/3/project/{projectKey}/statuses`.
4. Report data using `/rest/api/3/search/jql`.

The search helper follows Jira's `nextPageToken` until all pages are retrieved.

## Report definitions

All date calculations use `Europe/Berlin`.

**Previous Week**

Previous Monday 00:00 through the current Monday 00:00, using an exclusive end boundary.

**Created**

Issues whose `created` timestamp falls inside the reporting period.

**Resolved**

Issues whose `resolutiondate` falls inside the reporting period. They may have been created before the reporting period.

**Still Open**

Issues created inside the reporting period whose Jira `resolution` is still empty when the report is generated.

**Status filter**

A manual run can limit results by current Jira status. The Python program validates requested status names against the project's statuses before running the JQL searches. The scheduled Monday report uses all statuses.

## Security and permissions

Secrets are stored as GitHub Actions repository secrets and are injected only into the job environment at runtime.

Required repository secrets:

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

The Jira account only requires read access appropriate for the report, including Browse Projects and visibility of the issues to be reported.

No Jira token or SMTP password is stored in source control, `.env.example`, workflow logs or report output.

The workflow token is explicitly restricted to:

```yaml
permissions:
  contents: read
```

## Network connections

The GitHub-hosted runner makes outbound connections only to:

- the configured Jira Cloud site over HTTPS;
- the configured SMTP service for report delivery;
- GitHub/Python package infrastructure required to start the workflow and install `requests`.

No inbound network connection to a custom server is required.

## Error handling

`report.py` returns clear diagnostic errors for:

- missing configuration;
- invalid Jira URL;
- failed authentication;
- inaccessible/nonexistent project;
- unavailable project statuses;
- invalid custom date ranges;
- invalid selected statuses;
- malformed JQL;
- authorization failures;
- rate limiting;
- temporary Jira 5xx failures;
- connection/timeouts;
- email-delivery failures.

Temporary Jira `429` and common `5xx` responses are retried up to three attempts with a short backoff.

## Reproduce

1. Create a Jira Cloud project and note the project key.
2. Create an Atlassian API token for the account that can browse the project.
3. Create a GitHub repository and add these files.
4. In **Settings → Secrets and variables → Actions**, create the nine repository secrets listed above.
5. For Gmail SMTP, use a Gmail App Password rather than the normal account password.
6. Open **Actions → Jira Monday Brief → Run workflow**.
7. Leave **All Statuses** selected for the normal report, or uncheck it and choose one or more specific status checkboxes.
8. Select the reporting period. For `custom`, enter start and end dates in `YYYY-MM-DD`.
9. Run the workflow.
10. Verify the workflow summary and the email received by the report recipient.

The runner pre-start schedule is:

```yaml
cron: "37 9 * * 1"
timezone: "Europe/Berlin"
```

`report.py` detects the scheduled run and waits until **10:00 Europe/Berlin** before starting Jira report generation. If GitHub does not allocate the runner until after 10:00, it runs immediately and logs the measured lateness.

## Scheduling note

GitHub documents that scheduled workflows can be delayed, especially at the start of an hour. This project therefore requests the hosted runner at 09:37 Europe/Berlin and uses a Python scheduling gate to wait until 10:00:00 before report generation. This materially reduces the top-of-hour delay risk while keeping the solution serverless. It is still not a hard real-time guarantee: if GitHub does not provide a runner by 10:00, the report starts as soon as the runner becomes available and the delay is logged.

## Testing evidence

During development the Jira connection was validated independently before the final workflow was assembled.

Tests included:

- successful Jira authentication;
- malformed Jira URL;
- intentionally invalid API credentials returning HTTP 401;
- nonexistent/inaccessible project key;
- successful project validation;
- successful JQL retrieval;
- end-to-end report email delivery.

Add the final screenshots below before submission:

```text
docs/email-report.png
docs/manual-workflow-run.png
docs/scheduled-workflow.png
```

## AI-assisted development disclosure

AI tools were used as a supporting resource for brainstorming edge cases, reviewing failure scenarios and improving documentation clarity. The implementation, credentials, Jira configuration and execution were manually validated. No API tokens or passwords are included in this repository, and AI is not part of the runtime workflow.
