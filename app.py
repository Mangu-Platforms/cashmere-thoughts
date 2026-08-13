"""
SkillVoice Studio — Vercel / web entrypoint

This is a lightweight control-plane and landing page.
Full audiobook generation (Piper + ffmpeg + long jobs) is designed
to run locally on production workstations, not on serverless.

The web surface exists so the repo can live as a proper Vercel project
with a real Python entrypoint.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from skillvoice import __version__

app = FastAPI(
    title="SkillVoice Studio",
    description="Local-first house narration pipeline — control plane & status",
    version=__version__,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)


def _safe_doctor() -> dict:
    """Best-effort status. On Vercel most checks will be limited."""
    try:
        from skillvoice.doctor import run_checks

        checks = run_checks()
        return {
            "ready": all(c.ready for c in checks),
            "checks": [
                {"name": c.name, "ready": c.ready, "detail": c.detail} for c in checks
            ],
        }
    except Exception as exc:  # noqa: BLE001 — status endpoint must never 500
        return {
            "ready": False,
            "checks": [],
            "note": f"Doctor unavailable in this environment: {exc}",
        }


@app.get("/api/health")
def health() -> dict:
    return {
        "service": "skillvoice-studio",
        "version": __version__,
        "mode": "control-plane",
        "message": "Full narration runs locally. This is the web surface.",
    }


@app.get("/api/doctor")
def doctor() -> dict:
    return _safe_doctor()


@app.get("/api/version")
def version() -> dict:
    return {"skillvoice": __version__}


@app.get("/", response_class=HTMLResponse)
def landing(request: Request) -> str:
    doctor = _safe_doctor()
    status_color = "#16a34a" if doctor.get("ready") else "#ca8a04"
    status_label = "Ready" if doctor.get("ready") else "Limited / Demo"

    checks_html = ""
    for c in doctor.get("checks", []):
        icon = "✓" if c["ready"] else "✗"
        color = "#16a34a" if c["ready"] else "#dc2626"
        checks_html += f"""
        <tr>
          <td style="padding:6px 12px;font-weight:600">{c['name']}</td>
          <td style="padding:6px 12px;color:{color}">{icon} {'ready' if c['ready'] else 'fail'}</td>
          <td style="padding:6px 12px;color:#64748b;font-size:0.9em">{c['detail']}</td>
        </tr>
        """

    if not checks_html:
        checks_html = f"""
        <tr><td colspan="3" style="padding:12px;color:#64748b">
          {doctor.get('note', 'No checks available in this environment.')}
        </td></tr>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SkillVoice Studio</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card: #1e293b;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --border: #334155;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.55;
      min-height: 100vh;
    }}
    .wrap {{ max-width: 860px; margin: 0 auto; padding: 48px 24px 80px; }}
    h1 {{
      font-size: 2.1rem;
      font-weight: 700;
      letter-spacing: -0.03em;
      margin: 0 0 8px;
    }}
    .tag {{
      display: inline-block;
      background: #0c4a6e;
      color: var(--accent);
      font-size: 0.75rem;
      font-weight: 600;
      padding: 3px 10px;
      border-radius: 999px;
      margin-bottom: 20px;
    }}
    .lead {{
      font-size: 1.15rem;
      color: var(--muted);
      margin-bottom: 32px;
      max-width: 640px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 24px;
      margin-bottom: 24px;
    }}
    .card h2 {{
      margin: 0 0 12px;
      font-size: 1.1rem;
      font-weight: 600;
    }}
    .status {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-weight: 600;
      color: {status_color};
    }}
    .status::before {{
      content: "";
      width: 8px; height: 8px;
      border-radius: 50%;
      background: {status_color};
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
    code, pre {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.88em;
    }}
    pre {{
      background: #0f172a;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px 16px;
      overflow-x: auto;
      color: #e2e8f0;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .grid {{ display: grid; gap: 16px; grid-template-columns: 1fr 1fr; }}
    @media (max-width: 640px) {{ .grid {{ grid-template-columns: 1fr; }} }}
    footer {{
      margin-top: 48px;
      color: var(--muted);
      font-size: 0.85rem;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="tag">v{__version__} · control plane</div>
    <h1>SkillVoice Studio</h1>
    <p class="lead">
      Local-first narration pipeline for house voice models.
      Piper TTS → resumable jobs → chaptered M4B.
      Production work happens on the studio workstation.
      This page is the web surface for the project.
    </p>

    <div class="card">
      <h2>Environment status</h2>
      <p class="status">{status_label}</p>
      <table style="margin-top:16px">
        <thead>
          <tr style="text-align:left;color:var(--muted);font-size:0.8rem">
            <th style="padding:4px 12px">Check</th>
            <th style="padding:4px 12px">Status</th>
            <th style="padding:4px 12px">Detail</th>
          </tr>
        </thead>
        <tbody>
          {checks_html}
        </tbody>
      </table>
    </div>

    <div class="grid">
      <div class="card">
        <h2>Local usage</h2>
        <pre>skillvoice init
skillvoice doctor
skillvoice generate \\
  --skill eve-raspy \\
  --text-file ch01.txt \\
  --format m4b</pre>
      </div>
      <div class="card">
        <h2>API</h2>
        <p style="color:var(--muted);margin:0 0 12px;font-size:0.95rem">
          Lightweight status endpoints available on this deployment.
        </p>
        <p style="margin:0"><a href="/api/health">/api/health</a></p>
        <p style="margin:8px 0 0"><a href="/api/doctor">/api/doctor</a></p>
        <p style="margin:8px 0 0"><a href="/api/docs">/api/docs</a> (OpenAPI)</p>
      </div>
    </div>

    <div class="card">
      <h2>Why local-first?</h2>
      <p style="color:var(--muted);margin:0">
        Full-length books need resumable chunked synthesis, house-owned voice models,
        ffmpeg mastering, and hours of stable CPU. That belongs on the production
        workstation, not in a serverless function. The Vercel surface exists so the
        project has a real web entrypoint and a clean public face.
      </p>
    </div>

    <footer>
      SkillVoice Studio · Proprietary internal house tool ·
      <a href="https://github.com/Mangu-Platforms/cashmere-thoughts">GitHub</a>
    </footer>
  </div>
</body>
</html>
"""


# Vercel / ASGI entrypoint
# Some runtimes look for `app` or `handler`. FastAPI app is the standard.
handler = app
