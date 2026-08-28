import os
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv


load_dotenv()


JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")


def log(level, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} [{level}] {message}")


def get_previous_week():
    today = date.today()

    current_monday = today - timedelta(days=today.weekday())
    previous_monday = current_monday - timedelta(days=7)
    previous_sunday = current_monday - timedelta(days=1)

    return previous_monday, previous_sunday, current_monday


def main():
    if not JIRA_PROJECT_KEY:
        log("FAIL", "JIRA_PROJECT_KEY is missing.")
        sys.exit(1)

    start_date, sunday, query_end = get_previous_week()

    log("INFO", "Starting Jira Monday Brief")
    log("INFO", f"Project: {JIRA_PROJECT_KEY}")

    print()
    print("=" * 60)
    print("JIRA MONDAY BRIEF")
    print("=" * 60)
    print(f"Project:          {JIRA_PROJECT_KEY}")
    print(
        f"Reporting period: "
        f"{start_date} 00:00 to {sunday} 23:59"
    )
    print("=" * 60)

    log(
        "INFO",
        f"Query boundary: >= {start_date} and < {query_end}"
    )

    log("PASS", "Reporting period calculated successfully")


if __name__ == "__main__":
    main()