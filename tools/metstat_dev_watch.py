#!/usr/bin/env python3
"""Monitor the MetStat development PR without touching production or merging.

Every scheduled check updates a single issue only when its status changes.
Missing CI for a new revision may be dispatched; failed checks need a code fix,
not indefinite reruns. This is not an AI coding agent.
"""
import datetime as dt
import json
import os
import subprocess
import sys
from urllib.parse import quote

START = "<!-- metstat-watch:start -->"
END = "<!-- metstat-watch:end -->"
REPO = os.environ.get("GITHUB_REPOSITORY", "monsoonrain83-hub/metstat-nwp")
PR_ID = int(os.environ.get("METSTAT_DEV_PR", "14"))
ISSUE_ID = int(os.environ.get("METSTAT_DEV_ISSUE", "15"))


def api(path, method="GET", data=None):
    cmd = ["gh", "api", "--method", method, "-H", "Accept: application/vnd.github+json", path]
    body = None
    if data is not None:
        cmd += ["--input", "-"]
        body = json.dumps(data, ensure_ascii=False)
    result = subprocess.run(cmd, input=body, text=True, check=True, capture_output=True)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def latest_run(workflow, branch, sha=None):
    path = f"repos/{REPO}/actions/workflows/{workflow}/runs?branch={quote(branch, safe='')}&per_page=50"
    runs = api(path).get("workflow_runs", [])
    if sha:
        runs = [r for r in runs if r.get("head_sha") == sha]
    return max(runs, key=lambda r: r.get("created_at", "")) if runs else None


def human(run):
    if not run:
        return "هیچ اجرای متناظری پیدا نشد"
    status = run.get("status") or "unknown"
    conclusion = run.get("conclusion")
    name = conclusion if status == "completed" else status
    return f"**{name}** ([گزارش]({run.get('html_url', '')}))"


def main():
    pr = api(f"repos/{REPO}/pulls/{PR_ID}")
    issue = api(f"repos/{REPO}/issues/{ISSUE_ID}")
    if issue.get("state") != "open":
        print("Issue is closed; no changes")
        return 0
    branch = pr["head"]["ref"]
    sha = pr["head"]["sha"]
    ci = latest_run("quality-nwp.yml", branch, sha)
    prod = latest_run("nwp.yml", "main")

    # Dispatch missing checks once a revision has had time to create a CI run.
    # Never re-run a failed deterministic check unless the code actually changes.
    dispatched = False
    pushed = pr.get("updated_at") or pr.get("created_at") or ""
    try:
        changed = dt.datetime.fromisoformat(pushed.replace("Z", "+00:00"))
        mature = dt.datetime.now(dt.timezone.utc) - changed >= dt.timedelta(minutes=15)
    except ValueError:
        mature = False
    if (not ci and mature and pr.get("state") == "open" and
            not pr.get("merged") and not pr.get("head", {}).get("repo", {}).get("fork")):
        api(f"repos/{REPO}/actions/workflows/quality-nwp.yml/dispatches",
            method="POST", data={"ref": branch})
        dispatched = True

    if not ci:
        next_step = "آزمون شاخه هنوز ثبت نشده؛ منتظر اجرای CI" if dispatched else "آزمون نسخه جدید را بررسی کنید"
    elif ci.get("status") == "completed" and ci.get("conclusion") == "success":
        next_step = "آزمون‌ها سبز شدند؛ مرحله بعدی از صف کار با عامل توسعه انجام شود"
    elif ci.get("status") == "completed":
        next_step = "CI شکست خورد؛ علت را از لاگ رفع کنید؛ تکرار بدون تغییر کد مفید نیست"
    else:
        next_step = "CI در حال اجراست؛ پس از پایان وضعیت تازه ثبت می‌شود"

    pr_status = "ادغام‌شده" if pr.get("merged") else ("باز / پیش‌نویس" if pr.get("draft") else "باز")
    box = "\n".join([
        START,
        "### گزارش خودکار GitHub (حداکثر هر ۳۰ دقیقه)",
        f"- [PR #{PR_ID}](https://github.com/{REPO}/pull/{PR_ID}): **{pr_status}**؛ کامیت `{sha[:12]}`",
        f"- آزمون کیفیت برای همین کامیت: {human(ci)}",
        f"- آخرین اجرای تولید NWP روی `main`: {human(prod)}",
        f"- مرحله بعدی: {next_step}",
        "- این ربات **پایش و بازیابی چک‌های غایب** انجام می‌دهد؛ "
        "خودش کد نمی‌نویسد، PR ادغام نمی‌کند و تولید نقشهٔ سایت را تغییر نمی‌دهد.",
        END,
    ])
    old = issue.get("body") or ""
    if START in old and END in old:
        prefix, tail = old.split(START, 1)
        _, suffix = tail.split(END, 1)
        new_body = prefix + box + suffix
    else:
        new_body = old.rstrip() + "\n\n" + box + "\n"
    if new_body != old:
        api(f"repos/{REPO}/issues/{ISSUE_ID}", method="PATCH", data={"body": new_body})
        print("Issue status updated")
    else:
        print("No material status change; nothing written")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f"GitHub API error: {exc.stderr[-1200:]}", file=sys.stderr)
        sys.exit(1)
