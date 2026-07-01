"""The demo website (FastAPI). Serve with: python -m tokenops.bench_site  (port 8090).

Every page renders the SAME chrome (header + nav + sidebar) — that shared, static prefix is
what a prompt-cache would reuse. The page-specific `<main>` is the only volatile part.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

CHROME_CSS = """
:root{--bg:#0f1420;--panel:#161c2b;--ink:#e7ecf5;--muted:#8b97ad;--line:#232c40;--accent:#5b8cff}
*{box-sizing:border-box}body{margin:0;font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
header{display:flex;align-items:center;gap:12px;padding:14px 22px;border-bottom:1px solid var(--line);background:var(--panel)}
header .logo{width:26px;height:26px;border-radius:7px;background:linear-gradient(135deg,#5b8cff,#8b5bff)}
header h1{font-size:16px;margin:0;font-weight:600;letter-spacing:.2px}
.layout{display:grid;grid-template-columns:220px 1fr;min-height:calc(100vh - 57px)}
aside{border-right:1px solid var(--line);background:var(--panel);padding:18px}
aside a{display:block;color:var(--muted);text-decoration:none;padding:9px 12px;border-radius:8px;margin-bottom:4px}
aside a:hover,aside a.active{color:var(--ink);background:#1e2740}
main{padding:30px 40px;max-width:900px}
h2{margin:0 0 6px;font-size:22px}.sub{color:var(--muted);margin:0 0 22px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:22px;margin:14px 0}
.btn{display:inline-block;background:var(--accent);color:#fff;border:0;border-radius:9px;padding:10px 18px;font-weight:600;text-decoration:none}
.kv{color:var(--muted)}.kv b{color:var(--ink)}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid var(--line);padding:5px 9px;text-align:left}
th{background:#1a2236;color:var(--muted)}
"""

NAV = [("/", "Home"), ("/easy", "Easy task"), ("/hard", "Hard task"),
       ("/huge", "Large report"), ("/loop", "Paginated feed")]


def _chrome(path: str, title: str, sub: str, body: str) -> str:
    nav = "".join(
        f'<a href="{href}" class="{"active" if href == path else ""}">{label}</a>'
        for href, label in NAV
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title} · Acme Portal</title>
<style>{CHROME_CSS}</style></head><body>
<header><div class="logo"></div><h1>Acme Analytics Portal</h1></header>
<div class="layout"><aside><nav>{nav}</nav></aside>
<main><h2>{title}</h2><p class="sub">{sub}</p>{body}</main></div></body></html>"""


def build_app() -> FastAPI:
    app = FastAPI(title="bench-site")

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        body = """<div class="card">Welcome to the Acme portal. Use the navigation to open a task.
        Each page is a small, self-contained workspace.</div>"""
        return _chrome("/", "Home", "Pick a task from the left.", body)

    @app.get("/easy", response_class=HTMLResponse)
    def easy() -> str:
        body = """<div class="card">
        <p class="kv">Support contact: <b id="phone">+1-555-0142</b></p>
        <a href="#" id="submit" class="btn">Submit ticket</a></div>"""
        return _chrome("/easy", "Easy task", "Extract the support phone number.", body)

    @app.get("/hard", response_class=HTMLResponse)
    def hard() -> str:
        para = (
            "Enterprise SaaS pricing has shifted from flat per-seat licensing toward hybrid "
            "consumption models that blend a committed platform fee with usage-metered add-ons. "
            "Vendors increasingly gate advanced governance, SSO, and audit logging behind an "
            "enterprise tier while exposing usage-based inference or storage charges that scale "
            "non-linearly with adoption. The net effect is that headline per-seat prices understate "
            "true cost of ownership: procurement teams must model committed-use discounts against "
            "elastic overage, factor in annual ramp clauses, and reconcile list price with the "
            "negotiated floor. A defensible estimate therefore requires separating the fixed "
            "platform commitment from the variable metered component and stress-testing both "
            "against projected seat growth and workload intensity over the contract term. "
        ) * 3
        body = f'<div class="card"><p>{para}</p></div>'
        return _chrome("/hard", "Hard task", "Read and summarize the pricing analysis.", body)

    @app.get("/huge", response_class=HTMLResponse)
    def huge(rows: int = 5000) -> str:
        cells = "".join(
            f"<tr><td>{i}</td><td>SKU-{i:05d}</td><td>${(i * 37) % 9999}.00</td>"
            f"<td>region-{i % 12}</td><td>{'active' if i % 3 else 'archived'}</td></tr>"
            for i in range(rows)
        )
        body = f"""<div class="card"><table><thead><tr><th>#</th><th>SKU</th><th>Price</th>
        <th>Region</th><th>Status</th></tr></thead><tbody>{cells}</tbody></table></div>"""
        return _chrome("/huge", "Large report", f"{rows} rows of catalog data.", body)

    @app.get("/loop", response_class=HTMLResponse)
    def loop(p: int = 1) -> str:
        nxt = 2 if p == 1 else 1  # cycles 1 -> 2 -> 1 forever
        body = f"""<div class="card"><p class="kv">Feed page <b>{p}</b> of the activity stream.</p>
        <p>No new items on this page.</p>
        <a href="/loop?p={nxt}" id="next" class="btn">Load next page &rarr;</a></div>"""
        return _chrome("/loop", "Paginated feed", "Browse the activity stream.", body)

    return app


def main() -> None:
    import uvicorn
    uvicorn.run(build_app(), host="127.0.0.1", port=8090, log_level="warning")


if __name__ == "__main__":
    main()
