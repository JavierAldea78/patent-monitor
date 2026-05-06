#!/usr/bin/env python3
"""
Send HTML patent newsletter via Gmail SMTP.
Required env vars: GMAIL_USER, GMAIL_APP_PASSWORD, NEWSLETTER_TO
Optional: PAGES_URL
"""

import json
import os
import re
import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

REPO_ROOT    = Path(__file__).parent.parent
PATENTS_JSON = REPO_ROOT / "patents.json"

GMAIL_USER         = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
NEWSLETTER_TO      = os.environ["NEWSLETTER_TO"]
PAGES_URL          = os.environ.get("PAGES_URL") or "https://patent-monitor.netlify.app/"

DOMAIN_COLORS = {
    "Packaging & Smart Packaging":   "#d97706",
    "Bebidas Funcionales":           "#b45309",
    "Microencapsulación":            "#7c3aed",
    "Materias Primas Alternativas":  "#059669",
    "Procesos Avanzados Cervecería": "#0284c7",
    "Reciclado PET":                 "#dc2626",
}

STATUS_COLORS = {
    "granted": "#059669",
    "pending": "#d97706",
    "expired": "#64748b",
}

JURISDICTION_FLAGS = {
    "US": "🇺🇸", "EP": "🇪🇺", "WO": "🌐", "JP": "🇯🇵",
    "CN": "🇨🇳", "DE": "🇩🇪", "GB": "🇬🇧", "FR": "🇫🇷",
    "KR": "🇰🇷", "AU": "🇦🇺", "CA": "🇨🇦",
}


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def badge(text: str, color: str) -> str:
    return (f'<span style="background:{color};color:#fff;padding:2px 7px;'
            f'border-radius:10px;font-size:11px;font-weight:600;">{text}</span>')


def patent_row(p: dict) -> str:
    domain      = p.get("domain", "General")
    color       = DOMAIN_COLORS.get(domain, "#64748b")
    status      = p.get("status", "pending")
    s_color     = STATUS_COLORS.get(status, "#64748b")
    score       = p.get("score", 0)
    score_color = "#059669" if score >= 60 else ("#d97706" if score >= 40 else "#64748b")
    juris       = p.get("jurisdiction", "")
    flag        = JURISDICTION_FLAGS.get(juris, "")
    title       = strip_tags(p.get("title", ""))[:110]
    assignee    = (p.get("assignee") or "—")[:60]
    pat_num     = p.get("patent_number", "")
    link        = p.get("patent_url") or p.get("google_url") or ""
    g_link      = p.get("google_url") or ""
    ipc         = ", ".join((p.get("ipc_codes") or [])[:3])

    link_html = (f'<a href="{link}" style="color:#b45309;font-size:10px;">{pat_num[:20]}</a>'
                 if link else pat_num[:20])
    g_link_html = (f' &bull; <a href="{g_link}" style="color:#b45309;font-size:10px;">Google ↗</a>'
                   if g_link else "")

    return f"""
        <tr>
          <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;vertical-align:top;width:55%;">
            <strong style="color:#1e293b;font-size:13px;">{title}</strong><br>
            <span style="color:#64748b;font-size:11px;">{assignee}</span><br>
            <span style="margin-top:4px;display:inline-block;">
              {badge(domain[:20], color)}
              &nbsp;{badge(status.capitalize(), s_color)}
              &nbsp;{flag} {juris}
            </span>
            {f'<br><span style="color:#94a3b8;font-size:10px;">{ipc}</span>' if ipc else ""}
          </td>
          <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;text-align:center;width:8%;">
            <span style="color:{score_color};font-weight:700;font-size:16px;">{score}</span>
          </td>
          <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;width:20%;font-size:11px;">
            {link_html}{g_link_html}
          </td>
          <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;width:17%;font-size:11px;color:#64748b;">
            {p.get('filing_date','') or p.get('pub_date','')[:10]}
          </td>
        </tr>"""


def build_html(patents: list[dict], today: str) -> str:
    top = patents[:60]

    by_domain: dict[str, list] = {}
    for p in top:
        by_domain.setdefault(p.get("domain", "General"), []).append(p)

    sections = ""
    for domain in sorted(by_domain):
        color = DOMAIN_COLORS.get(domain, "#64748b")
        rows  = "".join(patent_row(p) for p in by_domain[domain][:15])
        sections += f"""
        <h2 style="color:#1e293b;margin:32px 0 8px;padding-bottom:6px;
                   border-bottom:2px solid {color};">{domain}</h2>
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="background:#f1f5f9;">
              <th style="padding:8px;text-align:left;color:#475569;font-size:11px;">TITLE / ASSIGNEE</th>
              <th style="padding:8px;text-align:center;color:#475569;font-size:11px;">SCORE</th>
              <th style="padding:8px;text-align:left;color:#475569;font-size:11px;">PATENT</th>
              <th style="padding:8px;text-align:left;color:#475569;font-size:11px;">DATE</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>"""

    total_granted = sum(1 for p in patents if p.get("status") == "granted")
    total_pending = len(patents) - total_granted

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ffffff;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:820px;margin:0 auto;padding:24px;background:#ffffff;color:#1e293b;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#451a03,#b45309);
                padding:32px;border-radius:14px;margin-bottom:32px;">
      <div style="display:flex;align-items:center;gap:16px;">
        <div style="width:48px;height:48px;background:rgba(255,255,255,.15);
                    border-radius:12px;display:flex;align-items:center;
                    justify-content:center;font-size:24px;">⚡</div>
        <div>
          <h1 style="color:#fff;margin:0;font-size:24px;font-weight:700;">Patent Monitor</h1>
          <p style="color:#fcd34d;margin:4px 0 0;font-size:13px;">
            Weekly digest &bull; {today} &bull;
            {len(patents)} patents &bull;
            ✓ {total_granted} granted &bull; ⏳ {total_pending} pending
          </p>
        </div>
      </div>
    </div>

    {sections}

    <!-- Footer -->
    <div style="margin-top:40px;padding:20px;border-top:1px solid #e2e8f0;text-align:center;">
      <a href="{PAGES_URL}"
         style="display:inline-block;background:#b45309;color:#fff;
                padding:10px 28px;border-radius:8px;text-decoration:none;
                font-weight:600;font-size:13px;">
        Open Patent Dashboard ↗
      </a>
      <p style="color:#64748b;font-size:11px;margin-top:16px;">
        Sources: EPO OPS &bull; USPTO PatentsView &bull; Last 2 years
      </p>
    </div>

  </div>
</body>
</html>"""


def main():
    today   = datetime.date.today().isoformat()
    patents = json.loads(PATENTS_JSON.read_text(encoding="utf-8"))

    if not patents:
        print("No patents in patents.json — skipping newsletter.")
        return

    recipients = [r.strip() for r in NEWSLETTER_TO.split(",") if r.strip()]
    html_body  = build_html(patents, today)

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = f"Patent Monitor — {today} ({len(patents)} patents)"
    msg["From"]    = GMAIL_USER
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.sendmail(GMAIL_USER, recipients, msg.as_string())

    print(f"Newsletter sent → {recipients}  ({today}, {len(patents)} patents)")


if __name__ == "__main__":
    main()
