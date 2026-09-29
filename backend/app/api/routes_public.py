"""Public, unauthenticated endpoints: the web enquiry form.

Everything here is reachable by anyone who has the form's secret link, so
the handlers stay thin and all checks live in domain/web_form.py.
"""

import json
from html import escape
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domain import web_form
from app.domain.errors import ConflictError, NotFoundError

router = APIRouter(prefix="/api/public", tags=["public"])

MAX_BODY = 20 * 1024

_STYLE = """
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
background:#f4f6f8;color:#14202b}main{max-width:520px;margin:0 auto;padding:24px 16px}
h1{font-size:20px;margin:0 0 4px}p{margin:0 0 16px;color:#4a5866;font-size:14px}
form{background:#fff;border:1px solid #dde3e8;border-radius:14px;padding:18px;display:grid;gap:12px}
label{display:grid;gap:5px;font-size:13px;font-weight:600;color:#4a5866}
input,textarea{font:inherit;font-size:15px;color:#14202b;border:1px solid #cfd7de;border-radius:9px;padding:10px 11px;width:100%}
textarea{min-height:110px;resize:vertical}input:focus,textarea:focus{outline:2px solid #1fa9a2;border-color:transparent}
button{font:inherit;font-weight:700;font-size:15px;background:#14202b;color:#fff;border:0;border-radius:10px;padding:12px;cursor:pointer}
.hp{position:absolute;left:-10000px;width:1px;height:1px;overflow:hidden}.err{background:#fdecec;color:#b42318;
border-radius:9px;padding:10px 12px;font-size:14px}.ok{background:#e7f6ee;color:#146c43;border-radius:12px;padding:18px;font-size:15px}
small{color:#6b7885;font-weight:400}
@media (prefers-color-scheme:dark){body{background:#0f1720;color:#e6edf3}p,label{color:#a8b3bd}
form{background:#16212c;border-color:#26323e}input,textarea{background:#0f1720;color:#e6edf3;border-color:#2c3a47}
button{background:#d6f46f;color:#14202b}}
"""


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head><body><main>{body}</main></body></html>"
    )
    # No framing restriction on purpose: businesses embed this in their own site.
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def _form_html(company: str, values: dict, error: str | None = None) -> str:
    v = {k: escape(str(values.get(k, "") or "")) for k in ("name", "company", "phone", "email", "message")}
    err = f'<div class="err" role="alert">{escape(error)}</div>' if error else ""
    return f"""
<h1>Contact {escape(company)}</h1>
<p>Tell us what you need and we'll get back to you.</p>
<form method="post">
  {err}
  <label>Your name<input name="name" value="{v['name']}" maxlength="160" required autocomplete="name"></label>
  <label>Company <small>(optional)</small><input name="company" value="{v['company']}" maxlength="160" autocomplete="organization"></label>
  <label>Phone<input name="phone" value="{v['phone']}" maxlength="40" inputmode="tel" autocomplete="tel"></label>
  <label>Email<input name="email" type="email" value="{v['email']}" maxlength="160" autocomplete="email"></label>
  <label>How can we help?<textarea name="message" maxlength="2000">{v['message']}</textarea></label>
  <div class="hp" aria-hidden="true"><label>Website<input name="website" tabindex="-1" autocomplete="off"></label></div>
  <button type="submit">Send enquiry</button>
  <small>Give a phone number or an email so we can reply.</small>
</form>"""


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/enquiry/{key}", response_class=HTMLResponse)
def enquiry_page(key: str, db: Session = Depends(get_db)):
    """The hosted form: link to it, or embed it with an <iframe>."""

    try:
        _, company = web_form.form_for_key(db, key)
    except NotFoundError as exc:
        return _page("Enquiry form", f"<h1>Enquiry form</h1><p>{escape(str(exc))}</p>", 404)
    return _page(f"Contact {company.name}", _form_html(company.name, {}))


@router.post("/enquiry/{key}")
async def submit_enquiry(key: str, request: Request, db: Session = Depends(get_db)):
    """Form posts (application/x-www-form-urlencoded) get an HTML page back;
    JSON posts get JSON: {"ok": true, "message": ...} or {"ok": false, "error": ...}."""

    wants_json = "application/json" in request.headers.get("content-type", "")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        error, status = "That enquiry is too long.", 413
        return JSONResponse({"ok": False, "error": error}, status) if wants_json else _page("Enquiry", f'<div class="err">{error}</div>', status)
    try:
        if wants_json:
            data = json.loads(raw or b"{}")
            if not isinstance(data, dict):
                raise ValueError
        else:
            data = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}
    except ValueError:
        return JSONResponse({"ok": False, "error": "Send a JSON object."}, 400)

    try:
        result = web_form.submit(db, key, data, _client_ip(request))
    except NotFoundError as exc:
        if wants_json:
            return JSONResponse({"ok": False, "error": str(exc)}, 404)
        return _page("Enquiry form", f"<h1>Enquiry form</h1><p>{escape(str(exc))}</p>", 404)
    except web_form.RateLimited as exc:
        if wants_json:
            return JSONResponse({"ok": False, "error": str(exc)}, 429)
        return _page("Enquiry", f'<div class="err" role="alert">{escape(str(exc))}</div>', 429)
    except ConflictError as exc:
        if wants_json:
            return JSONResponse({"ok": False, "error": str(exc)}, 422)
        _, company = web_form.form_for_key(db, key)
        return _page(f"Contact {company.name}", _form_html(company.name, data, str(exc)), 422)

    if wants_json:
        return {"ok": True, "message": result["thank_you"]}
    return _page("Thank you", f'<div class="ok" role="status">{escape(result["thank_you"])}</div>')
