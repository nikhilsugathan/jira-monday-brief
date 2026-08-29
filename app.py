from datetime import datetime
import subprocess

from flask import Flask, jsonify, request, send_from_directory


app = Flask(__name__)

REPO = "nikhilsugathan/jira-monday-brief"
WORKFLOW = "weekly-report.yml"

PERIODS = {
    "previous-week",
    "previous-2-weeks",
    "previous-30-days",
    "custom",
}


@app.get("/")
def index():
    return send_from_directory("docs", "index.html")


@app.post("/generate")
def generate():
    data = request.get_json(silent=True) or {}

    period = data.get("report_period")
    start = data.get("start_date", "")
    end = data.get("end_date", "")

    if period not in PERIODS:
        return jsonify(error="Invalid report period."), 400

    if period == "custom":
        if not start or not end:
            return jsonify(
                error="Start and end dates are required."
            ), 400

        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            return jsonify(
                error="Dates must use YYYY-MM-DD."
            ), 400

        if end_date < start_date:
            return jsonify(
                error="End date cannot be before start date."
            ), 400

    command = [
        "gh",
        "workflow",
        "run",
        WORKFLOW,
        "--repo",
        REPO,
        "--ref",
        "main",
        "-f",
        f"report_period={period}",
        "-f",
        f"start_date={start}",
        "-f",
        f"end_date={end}",
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return jsonify(
            error=result.stderr.strip()
            or "Could not start report workflow."
        ), 500

    return jsonify(
        success=True,
        message="Report generation started."
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
    )