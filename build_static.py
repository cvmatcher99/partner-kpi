"""
Generates a static single-page HTML from live DB data → docs/index.html
Run: python build_static.py
"""
import json, os
import psycopg2, psycopg2.extras
from datetime import datetime

DB = dict(host="77.243.85.225", database="tabashir",
          user="postgres", password="tabashir2025", connect_timeout=8)

def categorize(link):
    if not link: return "other"
    l = link.lower()
    if "linkedin.com" in l: return "linkedin"
    if "indeed.com"   in l: return "indeed"
    return "website"

def parse(title):
    for sep in [" | ", " — ", " - "]:
        if sep in title:
            p = title.split(sep, 1)
            return p[0].strip(), p[1].strip()
    return title.strip(), ""

conn = psycopg2.connect(**DB, cursor_factory=psycopg2.extras.RealDictCursor)
cur  = conn.cursor()

# KPI totals
cur.execute("""
    SELECT COUNT(DISTINCT c.id) AS tc,
           COALESCE(SUM(c.jobs_to_apply_number),0) AS tt,
           COUNT(DISTINCT ma.id) AS tm,
           COALESCE(SUM(ra.ai_count),0) AS ta
    FROM clients c
    LEFT JOIN manual_applications ma ON ma.client_id = c.id
    LEFT JOIN (SELECT LOWER(email) em, COUNT(*) ai_count
               FROM rankings WHERE status='applied' GROUP BY LOWER(email)) ra
           ON ra.em = LOWER(c.email)
    WHERE c.is_partner = TRUE
""")
k = dict(cur.fetchone())
kpi = {"clients": int(k["tc"]), "target": int(k["tt"]),
       "manual": int(k["tm"]), "ai": int(k["ta"]),
       "total": int(k["tm"]) + int(k["ta"])}

# Clients
cur.execute("""
    SELECT c.id, c.name, c.email,
           COUNT(DISTINCT ma.id) AS mc, COALESCE(ra.ai_count,0) AS ac,
           c.jobs_to_apply_number AS tg
    FROM clients c
    LEFT JOIN manual_applications ma ON ma.client_id = c.id
    LEFT JOIN (SELECT LOWER(email) em, COUNT(*) ai_count
               FROM rankings WHERE status='applied' GROUP BY LOWER(email)) ra
           ON ra.em = LOWER(c.email)
    WHERE c.is_partner = TRUE
    GROUP BY c.id, c.name, c.email, c.jobs_to_apply_number, ra.ai_count
    ORDER BY (COUNT(DISTINCT ma.id)+COALESCE(ra.ai_count,0)) DESC, c.name
""")
clients_raw = [dict(r) for r in cur.fetchall()]

clients = []
for c in clients_raw:
    total = int(c["mc"]) + int(c["ac"])
    tg    = int(c["tg"] or 0)
    c["total"] = total
    c["pct"]   = min(100, int(total*100/tg) if tg > 0 else 0)

    # AI apps
    cur.execute("""
        SELECT COALESCE(j.company_name, r.job_title) AS company,
               r.job_application_email AS email
        FROM rankings r
        LEFT JOIN jobs j ON r.job_id = j.id::text
        WHERE LOWER(r.email)=LOWER(%s) AND r.status='applied'
        ORDER BY r.date DESC, r.id DESC
    """, (c["email"],))
    ai = [dict(r) for r in cur.fetchall()]

    # Manual apps
    cur.execute("SELECT job_title, job_link FROM manual_applications WHERE client_id=%s ORDER BY app_date DESC", (c["id"],))
    manual_raw = [dict(r) for r in cur.fetchall()]

    linkedin, indeed, website, other = [], [], [], []
    for m in manual_raw:
        t, co = parse(m["job_title"] or "")
        entry = {"title": t, "company": co}
        cat = categorize(m.get("job_link",""))
        if   cat == "linkedin": linkedin.append(entry)
        elif cat == "indeed":   indeed.append(entry)
        elif cat == "website":  website.append(entry)
        else:                   other.append(entry)

    # Build copy text
    lines = [f"*تقرير العميل:* *{c['name']}*"]
    if ai:
        lines.append("التقديم عبر الإيميلات")
        for a in ai: lines.append(f"{a['company']} — {a['email']}")
    if linkedin:
        lines.append("التقديم عبر LinkedIn")
        for e in linkedin:
            lines.append(e["title"] + (f" — {e['company']}" if e["company"] else ""))
    if indeed:
        lines.append("التقديم عبر Indeed")
        for e in indeed:
            lines.append(e["title"] + (f" — {e['company']}" if e["company"] else ""))
    if website:
        lines.append("التقديم عبر الموقع الإلكتروني")
        for e in website:
            lines.append(e["title"] + (f" — {e['company']}" if e["company"] else ""))
    if other:
        lines.append("تقديمات أخرى")
        for e in other:
            lines.append(e["title"] + (f" — {e['company']}" if e["company"] else ""))
    total_all = len(ai)+len(linkedin)+len(indeed)+len(website)+len(other)
    lines.append(f"\nالإجمالي: {total_all} تقديم | {datetime.now().strftime('%d/%m/%Y')}")

    clients.append({
        "id":       c["id"],
        "name":     c["name"],
        "email":    c["email"],
        "mc":       int(c["mc"]),
        "ac":       int(c["ac"]),
        "total":    total,
        "pct":      c["pct"],
        "target":   tg,
        "ai":       ai,
        "linkedin": linkedin,
        "indeed":   indeed,
        "website":  website,
        "other":    other,
        "copyText": "\n".join(lines),
    })

conn.close()

data_json = json.dumps({"kpi": kpi, "clients": clients,
                        "now": datetime.now().strftime("%d %b %Y, %H:%M")},
                       ensure_ascii=False)

HTML = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>KPI</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}}
:root{{
  --bg:#f5f7fa;--surface:#fff;--sf2:#f0f2f5;--sf3:#e8eaed;
  --accent:#2563eb;--mint:#059669;--orange:#ea6800;
  --muted:#6b7280;--text:#111827;--border:#e5e7eb;
}}
html{{font-size:16px;-webkit-text-size-adjust:100%}}
body{{background:var(--bg);color:var(--text);font-family:'Cairo',sans-serif;min-height:100dvh;overscroll-behavior:none}}
.top-bar{{background:var(--surface);border-bottom:1px solid var(--border);padding:0 16px;height:52px;display:flex;align-items:center;gap:8px;position:sticky;top:0;z-index:100}}
.logo{{font-size:22px;font-weight:900;color:var(--accent)}}
.sub{{font-size:12px;color:var(--muted)}}
.spacer{{flex:1}}
.badge-time{{font-size:11px;color:var(--muted);background:var(--sf3);padding:4px 10px;border-radius:20px}}
.page{{padding:12px 14px}}
.kpi-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:18px;margin-top:14px}}
.kpi-card{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:14px 12px;text-align:center}}
.kpi-label{{font-size:11px;color:var(--muted);margin-bottom:4px}}
.kpi-value{{font-size:34px;font-weight:900;line-height:1}}
.section-title{{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin:18px 0 10px}}
.client-row{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:16px;margin-bottom:10px;display:block;text-decoration:none;color:var(--text);cursor:pointer}}
.client-row:active{{background:var(--sf2)}}
.client-name{{font-size:16px;font-weight:700;margin-bottom:8px;line-height:1.3}}
.client-meta{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}}
.badge{{font-size:12px;padding:3px 12px;border-radius:20px;font-weight:700}}
.badge-ai{{background:#dbeafe;color:#1d4ed8}}
.badge-m{{background:#d1fae5;color:#065f46}}
.badge-total{{background:#ffedd5;color:#9a3412}}
.progress{{height:7px;background:var(--sf3);border-radius:4px;overflow:hidden}}
.progress-fill{{height:100%;border-radius:4px;background:linear-gradient(90deg,var(--accent),var(--mint))}}
.progress-label{{font-size:11px;color:var(--muted);margin-top:4px;direction:ltr;text-align:left}}
/* Detail view */
#detail{{display:none}}
.back-link{{display:inline-flex;align-items:center;gap:6px;color:var(--muted);font-size:14px;text-decoration:none;min-height:44px;margin-bottom:12px;cursor:pointer;background:none;border:none;font-family:'Cairo',sans-serif}}
.client-header{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:18px 16px;margin-bottom:14px}}
.client-header h1{{font-size:20px;font-weight:900;margin-bottom:4px;line-height:1.3}}
.client-email{{font-size:12px;color:var(--muted);direction:ltr;display:block}}
.client-badges{{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap}}
.app-section{{margin-bottom:14px}}
.app-section-title{{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;padding:0 4px;margin-bottom:8px;display:flex;align-items:center;gap:8px}}
.count-pill{{background:var(--sf2);border:1px solid var(--border);border-radius:20px;font-size:11px;padding:1px 8px;color:var(--text)}}
.app-item{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:13px 14px;margin-bottom:8px}}
.app-title{{font-size:14px;font-weight:700;margin-bottom:2px;line-height:1.35}}
.app-sub{{font-size:12px;color:var(--muted);direction:ltr;display:block}}
.copy-bar{{position:sticky;bottom:0;background:var(--surface);border-top:1px solid var(--border);padding:12px 14px;padding-bottom:calc(12px + env(safe-area-inset-bottom));margin:0 -14px}}
.btn{{display:flex;align-items:center;justify-content:center;gap:6px;min-height:52px;padding:0 20px;border-radius:14px;font-family:'Cairo',sans-serif;font-size:15px;font-weight:700;border:none;cursor:pointer;width:100%}}
.btn:active{{opacity:.75}}
.btn-mint{{background:var(--mint);color:#fff}}
.empty{{text-align:center;color:var(--muted);font-size:14px;padding:40px 20px}}
.bottom-space{{height:90px}}
.toast{{position:fixed;bottom:80px;left:50%;transform:translateX(-50%) translateY(60px);background:#111827;color:#fff;font-size:14px;font-weight:700;padding:12px 28px;border-radius:30px;transition:transform .25s ease;z-index:999;pointer-events:none}}
.toast.show{{transform:translateX(-50%) translateY(0)}}
</style>
</head>
<body>
<div class="top-bar">
  <span class="logo">KPI</span>
  <span class="sub">Tabashir</span>
  <span class="spacer"></span>
  <span class="badge-time" id="nowBadge"></span>
</div>

<!-- Dashboard -->
<div id="dashboard" class="page"></div>

<!-- Detail -->
<div id="detail" class="page"></div>

<div class="toast" id="toast">✓ Copied!</div>

<script>
const DATA = {data_json};
let currentClient = null;

function showToast(){{
  const t=document.getElementById('toast');
  t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),2000);
}}
function copyText(text){{
  if(navigator.clipboard){{navigator.clipboard.writeText(text).then(showToast);}}
  else{{const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);showToast();}}
}}

function renderDashboard(){{
  document.getElementById('detail').style.display='none';
  const dash=document.getElementById('dashboard');
  dash.style.display='block';
  const k=DATA.kpi;
  let html=`
  <div class="kpi-grid">
    <div class="kpi-card"><div class="kpi-label">Clients</div><div class="kpi-value" style="color:#2563eb">${{k.clients}}</div></div>
    <div class="kpi-card"><div class="kpi-label">Total Apps</div><div class="kpi-value" style="color:#ea6800">${{k.total}}</div></div>
    <div class="kpi-card"><div class="kpi-label">AI Email</div><div class="kpi-value" style="color:#059669">${{k.ai}}</div></div>
    <div class="kpi-card"><div class="kpi-label">Manual</div><div class="kpi-value" style="color:#7c3aed">${{k.manual}}</div></div>
  </div>
  <div class="section-title">Clients</div>`;
  DATA.clients.forEach(c=>{{
    html+=`<div class="client-row" onclick="showClient(${{c.id}})">
      <div class="client-name">${{c.name}}</div>
      <div class="client-meta">
        <span class="badge badge-total">${{c.total}} apps</span>
        <span class="badge badge-ai">AI: ${{c.ac}}</span>
        <span class="badge badge-m">Manual: ${{c.mc}}</span>
      </div>
      <div class="progress"><div class="progress-fill" style="width:${{c.pct}}%"></div></div>
      <div class="progress-label">${{c.pct}}% of ${{c.target}} target</div>
    </div>`;
  }});
  html+='<div class="bottom-space"></div>';
  dash.innerHTML=html;
}}

function showClient(id){{
  const c=DATA.clients.find(x=>x.id===id);
  if(!c)return;
  currentClient=c;
  document.getElementById('dashboard').style.display='none';
  const det=document.getElementById('detail');
  det.style.display='block';
  const manualCount=c.linkedin.length+c.indeed.length+c.website.length+c.other.length;
  let html=`
  <button class="back-link" onclick="renderDashboard()">← Dashboard</button>
  <div class="client-header">
    <h1>${{c.name}}</h1>
    <span class="client-email">${{c.email}}</span>
    <div class="client-badges">
      <span class="badge badge-total">${{c.total}} total</span>
      <span class="badge badge-ai">AI: ${{c.ac}}</span>
      <span class="badge badge-m">Manual: ${{manualCount}}</span>
    </div>
  </div>`;
  if(c.ai.length){{
    html+=`<div class="app-section"><div class="app-section-title">📧 Email Applications<span class="count-pill">${{c.ai.length}}</span></div>`;
    c.ai.forEach(a=>{{html+=`<div class="app-item"><div class="app-title">${{a.company}}</div><span class="app-sub">${{a.email}}</span></div>`;}});
    html+='</div>';
  }}
  if(c.linkedin.length){{
    html+=`<div class="app-section"><div class="app-section-title">💼 LinkedIn<span class="count-pill">${{c.linkedin.length}}</span></div>`;
    c.linkedin.forEach(e=>{{html+=`<div class="app-item"><div class="app-title">${{e.title}}</div>${{e.company?`<span class="app-sub">${{e.company}}</span>`:''}}</div>`;}});
    html+='</div>';
  }}
  if(c.indeed.length){{
    html+=`<div class="app-section"><div class="app-section-title">🔍 Indeed<span class="count-pill">${{c.indeed.length}}</span></div>`;
    c.indeed.forEach(e=>{{html+=`<div class="app-item"><div class="app-title">${{e.title}}</div>${{e.company?`<span class="app-sub">${{e.company}}</span>`:''}}</div>`;}});
    html+='</div>';
  }}
  if(c.website.length){{
    html+=`<div class="app-section"><div class="app-section-title">🌐 Website<span class="count-pill">${{c.website.length}}</span></div>`;
    c.website.forEach(e=>{{html+=`<div class="app-item"><div class="app-title">${{e.title}}</div>${{e.company?`<span class="app-sub">${{e.company}}</span>`:''}}</div>`;}});
    html+='</div>';
  }}
  if(!c.total)html+='<div class="empty">No applications yet.</div>';
  html+=`<div class="bottom-space"></div>
  <div class="copy-bar">
    <button class="btn btn-mint" onclick="copyText(currentClient.copyText)">📋  Copy Report</button>
  </div>`;
  det.innerHTML=html;
  det.scrollTop=0;
  window.scrollTo(0,0);
}}

// Init
document.getElementById('nowBadge').textContent=DATA.now;
renderDashboard();
</script>
</body>
</html>"""

os.makedirs("docs", exist_ok=True)
with open("docs/index.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print("Done: docs/index.html generated")
