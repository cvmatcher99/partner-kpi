"""
Generates docs/index.html with TODAY_COPY data baked in from live DB.
The page still fetches live data from backend.tabashir.ae for display.
TODAY_COPY holds today's application text per client for the نسخ اليوم button.

Run: python build_static.py
"""
import json, os
import psycopg2, psycopg2.extras
from datetime import datetime

DB = dict(
    host="77.243.85.225", database="tabashir",
    user="postgres", password="tabashir2025",
    connect_timeout=10,
    # Prevent queries from hanging indefinitely (GitHub Actions runners
    # sometimes have poor routing to this server — fail fast instead).
    options="-c statement_timeout=25000 -c lock_timeout=10000",
    keepalives=1, keepalives_idle=10,
    keepalives_interval=5, keepalives_count=3,
)


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


# ---- entity (company) extraction from application links / emails ------------
import re
from urllib.parse import urlparse

# Known application emails → the real entity name behind them.
EMAIL_CO = {
    "careers@tamimi.com": "Al Tamimi & Company",
    "careers@moe.gov.ae": "UAE Ministry of Education",
    "info@fbi.ae": "FBI (First Building & Interiors)",
}


def _spaced(s):
    s = re.sub(r"[-_]+", " ", s or "")
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)  # camelCase -> spaced
    out = s.strip().title()
    return {"Cpx": "CPX"}.get(out, out)         # acronym fix-ups


# ATS host → fixed brand, when the company isn't in the URL path.
_HOST_BRAND = {
    "adnoc.ae": "ADNOC", "adu.ac.ae": "Abu Dhabi University", "puffy.com": "Puffy",
    "revolut.com": "Revolut", "micro1.ai": "micro1", "hrapp.co": "Pulse Media (Workwisely)",
}
# Generic ATS hosts where the company can't be recovered from the URL.
_GENERIC = ("oraclecloud.com", "ceipal.com", "recruitcrm.io", "linkedin.com",
            "indeed.com", "bayt.com", "naukrigulf.com")


def company_from_link(link):
    if not link:
        return None
    try:
        u = urlparse(link); host = u.netloc.lower(); path = u.path
    except Exception:
        return None
    segs = [p for p in path.split("/") if p]
    if any(g in host for g in _GENERIC):
        return None
    for h, brand in _HOST_BRAND.items():
        if h in host:
            return brand
    if "smartrecruiters.com" in host:
        m = re.search(r"/company/([^/]+)", path)
        return _spaced(re.sub(r"\d+$", "", m.group(1))) if m else None  # EtihadAirways5 -> Etihad Airways
    if "ncoreplat.com" in host and segs: return _spaced(segs[-1].split("-")[0])  # .../saipem-spa-... -> Saipem
    if "lever.co" in host and segs:      return _spaced(segs[0])
    if "ashbyhq.com" in host and segs:   return _spaced(segs[0])
    if "greenhouse.io" in host and segs: return _spaced(segs[0])
    if "g42.ai" in host and segs:        return _spaced(segs[0]) + " (G42)"
    if "now-remote.com" in host:         return _spaced(host.split(".")[0])
    parts = host.split(".")
    if len(parts) >= 3 and parts[0] in ("careers", "jobs", "apply", "app", "recruiting"):
        return _spaced(parts[1])
    if len(parts) >= 2:
        return _spaced(parts[-2])
    return None


_PLAT = {"linkedin.com": "LinkedIn", "indeed.com": "Indeed", "smartrecruiters.com": "SmartRecruiters",
         "lever.co": "Lever", "ashbyhq.com": "Ashby", "greenhouse.io": "Greenhouse", "hrapp.co": "HRApp",
         "oraclecloud.com": "Oracle", "ceipal.com": "Ceipal", "recruitcrm.io": "RecruitCRM",
         "now-remote.com": "Now-Remote", "ncoreplat.com": "nCore", "g42.ai": "G42", "adnoc.ae": "ADNOC"}


def platform(link):
    if not link:
        return "-"
    try: host = urlparse(link).netloc.lower()
    except Exception: return "-"
    for k, v in _PLAT.items():
        if k in host:
            return v
    return host.replace("www.", "")


def build_entities(cur, cid, email):
    """{'email': [{company,email}], 'portal': [{company,count}]} for one client."""
    cur.execute("""SELECT job_application_email AS em, job_title
                   FROM rankings WHERE LOWER(email)=LOWER(%s) AND status='applied'
                   ORDER BY date DESC""", (email,))
    email_apps, seen_em = [], set()
    for r in cur.fetchall():
        em = (r["em"] or "").strip()
        if not em or em.lower() in seen_em:
            continue
        seen_em.add(em.lower())
        email_apps.append({"company": EMAIL_CO.get(em.lower(), ""), "email": em})

    cur.execute("SELECT job_title, job_link FROM manual_applications WHERE client_id=%s ORDER BY app_date", (cid,))
    by_co = {}
    for m in cur.fetchall():
        co = company_from_link(m["job_link"])
        if not co:
            continue
        by_co.setdefault(co, []).append(
            {"title": (m["job_title"] or "").strip(), "platform": platform(m["job_link"])})
    portal = [{"company": co, "count": len(apps), "apps": apps} for co, apps in
              sorted(by_co.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    return {"email": email_apps, "portal": portal}


def build_copy(name, ai, linkedin, indeed, website, other, label):
    lines = [f"‫*تقرير العميل:* *{name}* ({label})"]
    if ai:
        lines.append("التقديم عبر الإيميلات")
        for a in ai:
            lines.append(f"{a['company']} — {a['email']}")
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
    total = len(ai) + len(linkedin) + len(indeed) + len(website) + len(other)
    lines.append(f"\nالإجمالي: {total} تقديم | {datetime.now().strftime('%d/%m/%Y')}")
    return "\n".join(lines)


conn = psycopg2.connect(**DB, cursor_factory=psycopg2.extras.RealDictCursor)
cur  = conn.cursor()

# Get all partner clients
cur.execute("SELECT id, name, email FROM clients WHERE is_partner=TRUE")
clients_raw = [dict(r) for r in cur.fetchall()]

today_copy = {}   # {str(id): copyTextToday}
entities_map = {} # {str(id): {email:[...], portal:[...]}}  (all-time, real companies)

for c in clients_raw:
    entities_map[str(c["id"])] = build_entities(cur, c["id"], c["email"])

    # Today's AI apps
    cur.execute("""
        SELECT COALESCE(j.company_name, r.job_title) AS company,
               r.job_application_email AS email
        FROM rankings r
        LEFT JOIN jobs j ON r.job_id = j.id::text
        WHERE LOWER(r.email)=LOWER(%s) AND r.status='applied'
          AND DATE(r.date)=CURRENT_DATE
        ORDER BY r.date DESC, r.id DESC
    """, (c["email"],))
    ai = [dict(r) for r in cur.fetchall()]

    # Today's manual apps
    cur.execute("""
        SELECT job_title, job_link
        FROM manual_applications
        WHERE client_id=%s AND DATE(app_date)=CURRENT_DATE
        ORDER BY app_date DESC
    """, (c["id"],))
    manual_raw = [dict(r) for r in cur.fetchall()]

    linkedin, indeed, website, other = [], [], [], []
    for m in manual_raw:
        t, co = parse(m["job_title"] or "")
        entry = {"title": t, "company": co}
        cat = categorize(m.get("job_link", ""))
        if   cat == "linkedin": linkedin.append(entry)
        elif cat == "indeed":   indeed.append(entry)
        elif cat == "website":  website.append(entry)
        else:                   other.append(entry)

    today_copy[str(c["id"])] = build_copy(
        c["name"], ai, linkedin, indeed, website, other, "اليوم"
    )

conn.close()

today_json    = json.dumps(today_copy, ensure_ascii=False)
entities_json = json.dumps(entities_map, ensure_ascii=False)
build_label   = datetime.now().strftime("%d/%m/%Y %H:%M")

HTML = """<!DOCTYPE html>
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
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
:root{
  --bg:#f5f7fa;--surface:#fff;--sf2:#f0f2f5;--sf3:#e8eaed;
  --accent:#2563eb;--mint:#059669;--orange:#ea6800;
  --muted:#6b7280;--text:#111827;--border:#e5e7eb;
}
html{font-size:16px;-webkit-text-size-adjust:100%}
body{background:var(--bg);color:var(--text);font-family:'Cairo',sans-serif;min-height:100dvh;overscroll-behavior:none}
.top-bar{background:var(--surface);border-bottom:1px solid var(--border);padding:0 16px;height:52px;display:flex;align-items:center;gap:8px;position:sticky;top:0;z-index:100}
.logo{font-size:22px;font-weight:900;color:var(--accent)}
.sub{font-size:12px;color:var(--muted)}
.spacer{flex:1}
.live-badge{font-size:11px;color:#059669;background:#d1fae5;padding:4px 10px;border-radius:20px;font-weight:700}
.time-badge{font-size:11px;color:var(--muted);background:var(--sf3);padding:4px 10px;border-radius:20px}
.page{padding:12px 14px}
.kpi-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px;margin-top:14px}
.kpi-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:14px 12px;text-align:center}
.kpi-label{font-size:11px;color:var(--muted);margin-bottom:4px}
.kpi-value{font-size:34px;font-weight:900;line-height:1}
.filter-bar{display:flex;gap:8px;margin-bottom:14px}
.filter-btn{flex:1;min-height:40px;border-radius:12px;border:1.5px solid var(--border);background:var(--surface);color:var(--muted);font-family:'Cairo',sans-serif;font-size:13px;font-weight:700;cursor:pointer;transition:all .15s}
.filter-btn.active{border-color:var(--accent);background:#eff6ff;color:var(--accent)}
.filter-btn.active-new{border-color:#059669;background:#d1fae5;color:#065f46}
.section-title{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin:4px 0 10px}
.client-row{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:16px;margin-bottom:10px;display:block;text-decoration:none;color:var(--text);cursor:pointer;position:relative}
.client-row:active{background:var(--sf2)}
.client-row.is-new{border-color:#6ee7b7;border-width:2px}
.client-name{font-size:16px;font-weight:700;margin-bottom:8px;line-height:1.3}
.client-meta{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.badge{font-size:12px;padding:3px 12px;border-radius:20px;font-weight:700}
.badge-ai{background:#dbeafe;color:#1d4ed8}
.badge-m{background:#d1fae5;color:#065f46}
.badge-total{background:#ffedd5;color:#9a3412}
.badge-new{background:#d1fae5;color:#065f46;font-size:11px;padding:2px 9px}
.new-dot{position:absolute;top:14px;left:14px;width:8px;height:8px;border-radius:50%;background:#059669}
.date-label{font-size:11px;color:var(--muted);margin-top:4px}
.progress{height:7px;background:var(--sf3);border-radius:4px;overflow:hidden}
.progress-fill{height:100%;border-radius:4px;background:linear-gradient(90deg,var(--accent),var(--mint))}
.progress-label{font-size:11px;color:var(--muted);margin-top:4px;direction:ltr;text-align:left}
#detail{display:none}
.back-link{display:inline-flex;align-items:center;gap:6px;color:var(--muted);font-size:14px;text-decoration:none;min-height:44px;margin-bottom:12px;cursor:pointer;background:none;border:none;font-family:'Cairo',sans-serif}
.client-header{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:18px 16px;margin-bottom:14px}
.client-header h1{font-size:20px;font-weight:900;margin-bottom:4px;line-height:1.3}
.client-email{font-size:12px;color:var(--muted);direction:ltr;display:block}
.client-badges{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap}
.app-section{margin-bottom:14px}
.app-section-title{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;padding:0 4px;margin-bottom:8px;display:flex;align-items:center;gap:8px}
.count-pill{background:var(--sf2);border:1px solid var(--border);border-radius:20px;font-size:11px;padding:1px 8px;color:var(--text)}
.app-item{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:13px 14px;margin-bottom:8px}
.app-title{font-size:14px;font-weight:700;margin-bottom:2px;line-height:1.35}
.app-sub{font-size:12px;color:var(--muted);direction:ltr;display:block}
.entities-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:14px 14px 6px;margin-bottom:14px}
.entities-head{font-size:13px;font-weight:700;color:var(--text);margin-bottom:12px;display:flex;align-items:center;gap:8px}
.entities-head .count-pill{background:#eff6ff;border-color:#bfdbfe;color:#1d4ed8}
.entities{display:flex;flex-direction:column;gap:8px}
.entity-chip{display:flex;align-items:center;gap:10px;background:var(--sf2);border:1px solid var(--border);border-radius:10px;padding:10px 12px;font-size:14px;font-weight:600;line-height:1.35}
.entity-num{flex:0 0 24px;width:24px;height:24px;border-radius:7px;background:var(--accent);color:#fff;font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center}
.ent-sub{font-size:11px;font-weight:700;color:var(--muted);margin:12px 0 8px}
.ent-name{flex:1;display:flex;flex-direction:column;gap:2px}
.ent-mail{font-size:11px;font-weight:400;color:var(--muted);direction:ltr}
.ent-cnt{flex:0 0 auto;background:#eff6ff;border:1px solid #bfdbfe;color:#1d4ed8;font-size:11px;font-weight:700;border-radius:20px;padding:2px 9px;direction:ltr}
.copy-bar{position:sticky;bottom:0;background:var(--surface);border-top:1px solid var(--border);padding:12px 14px;padding-bottom:calc(12px + env(safe-area-inset-bottom));margin:0 -14px}
.copy-row{display:flex;gap:10px}
.btn{display:flex;align-items:center;justify-content:center;gap:6px;min-height:52px;padding:0 20px;border-radius:14px;font-family:'Cairo',sans-serif;font-size:15px;font-weight:700;border:none;cursor:pointer;flex:1}
.btn:active{opacity:.75}
.btn-mint{background:var(--mint);color:#fff}
.btn-orange{background:var(--orange);color:#fff}
.btn-blue{background:var(--accent);color:#fff}
.empty{text-align:center;color:var(--muted);font-size:14px;padding:40px 20px}
.bottom-space{height:90px}
.loading{text-align:center;padding:60px 20px;color:var(--muted);font-size:15px}
.error-box{background:#fef2f2;border:1px solid #fecaca;border-radius:14px;padding:20px;margin:20px 0;color:#991b1b;font-size:13px;text-align:center}
.toast{position:fixed;bottom:90px;left:50%;transform:translateX(-50%);background:#111827;color:#fff;font-size:14px;font-weight:700;padding:12px 28px;border-radius:30px;transition:opacity .3s ease,visibility .3s ease;z-index:9999;pointer-events:none;direction:ltr;white-space:nowrap;opacity:0;visibility:hidden}
.toast.show{opacity:1;visibility:visible}
</style>
</head>
<body>
<div class="top-bar">
  <span class="logo">KPI</span>
  <span class="sub">Tabashir</span>
  <span class="spacer"></span>
  <span class="live-badge" id="liveBadge">&#9679; LIVE</span>
  <span class="time-badge" id="nowBadge">—</span>
</div>

<div id="dashboard" class="page"><div class="loading">جاري التحميل...</div></div>
<div id="detail" class="page"></div>

<div class="toast" id="toast">Copied &#10003;</div>

<script>
const API = 'https://backend.tabashir.ae/api/v1/kpi/data';
const TODAY_COPY = """ + today_json + """;
const ENTITIES = """ + entities_json + """;
const BUILD_DATE = '""" + build_label + """';
let DATA = null;
let currentClient = null;
let refreshTimer = null;
let activeFilter = 'all';

function daysSince(dateStr){
  if(!dateStr) return 9999;
  const d=new Date(dateStr);
  const now=new Date();
  return Math.floor((now-d)/(1000*60*60*24));
}

function showToast(msg){
  const t=document.getElementById('toast');
  t.textContent=msg||'Copied ✓';
  t.classList.add('show');
  setTimeout(function(){t.classList.remove('show');},2500);
}
function copyText(text){
  if(navigator.clipboard){navigator.clipboard.writeText(text).then(function(){showToast();});}
  else{const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);showToast();}
}
function copyToday(id){
  const text=TODAY_COPY[String(id)];
  if(!text||text.indexOf('إجمالي: 0 ')!==-1){
    showToast('لا تقديمات اليوم');
    return;
  }
  copyText(text);
}

function setFilter(f){
  activeFilter=f;
  renderDashboard();
}

function renderDashboard(){
  document.getElementById('detail').style.display='none';
  const dash=document.getElementById('dashboard');
  dash.style.display='block';
  if(!DATA){dash.innerHTML='<div class="loading">جاري التحميل...</div>';return;}
  const k=DATA.kpi;

  const allClients=DATA.clients;
  const newClients=allClients.filter(c=>daysSince(c.dateIn)<=10);
  const list=activeFilter==='new'?newClients:allClients;

  let html=`
  <div class="kpi-grid">
    <div class="kpi-card"><div class="kpi-label">العملاء</div><div class="kpi-value" style="color:#2563eb">${k.clients}</div></div>
    <div class="kpi-card"><div class="kpi-label">إجمالي التقديمات</div><div class="kpi-value" style="color:#ea6800">${k.total}</div></div>
    <div class="kpi-card"><div class="kpi-label">تقديم بالإيميل</div><div class="kpi-value" style="color:#059669">${k.ai}</div></div>
    <div class="kpi-card"><div class="kpi-label">تقديم مباشر</div><div class="kpi-value" style="color:#7c3aed">${k.manual}</div></div>
  </div>
  <button onclick="copyAllTodayReports()" style="width:100%;min-height:50px;border-radius:14px;background:#059669;color:#fff;font-family:'Cairo',sans-serif;font-size:15px;font-weight:700;border:none;cursor:pointer;margin-bottom:10px;display:flex;align-items:center;justify-content:center;gap:8px;padding:0 20px;">📋 نسخ تقارير اليوم — الكل</button>
  <div class="filter-bar">
    <button class="filter-btn ${activeFilter==='all'?'active':''}" onclick="setFilter('all')">الكل (${allClients.length})</button>
    <button class="filter-btn ${activeFilter==='new'?'active-new':''}" onclick="setFilter('new')">🆕 جدد — آخر 10 أيام (${newClients.length})</button>
  </div>
  <div class="section-title">${activeFilter==='new'?'العملاء الجدد':'جميع العملاء'}</div>`;

  if(list.length===0){
    html+='<div class="empty">لا يوجد عملاء جدد في آخر 10 أيام</div>';
  } else {
    list.forEach(c=>{
      const days=daysSince(c.dateIn);
      const isNew=days<=10;
      const newBadge=isNew?`<span class="badge badge-new">جديد · منذ ${days===0?'اليوم':days+' يوم'}</span>`:'';
      const newDot=isNew?'<div class="new-dot"></div>':'';
      html+=`<div class="client-row${isNew?' is-new':''}" onclick="showClient(${c.id})">
        ${newDot}
        <div class="client-name">${c.name}</div>
        <div class="client-meta">
          <span class="badge badge-total">${c.total} تقديم</span>
          <span class="badge badge-ai">إيميل: ${c.ac}</span>
          <span class="badge badge-m">مباشر: ${c.mc}</span>
          ${newBadge}
        </div>
        <div class="progress"><div class="progress-fill" style="width:${c.pct}%"></div></div>
        <div class="progress-label" style="direction:rtl;text-align:right">${c.pct}% من هدف ${c.target}</div>
      </div>`;
    });
  }
  html+='<div class="bottom-space"></div>';
  dash.innerHTML=html;
}

function buildEntitiesText(id){
  const e=ENTITIES[String(id)];
  const c=DATA?DATA.clients.find(x=>x.id===id):null;
  const name=(c&&c.name)||(currentClient&&currentClient.name)||'';
  if(!e) return '';
  const portalTotal=(e.portal||[]).reduce((s,p)=>s+p.count,0);
  const total=(e.email||[]).length+portalTotal;
  const L=[];
  L.push('*تقرير الجهات — '+name+'*');
  L.push('الإجمالي: '+total+' تقديم  |  عبر الإيميل: '+(e.email||[]).length+'  |  عبر البورتالات: '+portalTotal);
  L.push('');
  if(e.email&&e.email.length){
    L.push('📧 *التقديم عبر الإيميل ('+e.email.length+')*');
    e.email.forEach((a,i)=>L.push((i+1)+'. '+(a.company||a.email)+' — '+a.email));
    L.push('');
  }
  if(e.portal&&e.portal.length){
    L.push('🏢 *التقديم عبر البورتالات — حسب الشركة*');
    e.portal.forEach(p=>{
      if(p.count>1){
        L.push('');
        L.push('▪️ *'+p.company+'* ('+p.count+' تقديمات):');
        (p.apps||[]).forEach((a,j)=>L.push('   '+(j+1)+') '+(a.title||'-')+' — '+a.platform));
      } else {
        const a=(p.apps&&p.apps[0])||{};
        L.push('▪️ *'+p.company+'* — '+(a.title||'-')+' ('+(a.platform||'')+')');
      }
    });
  }
  return L.join('\\n');
}

function renderEntities(id){
  // Real company names extracted from application emails + portal links at build
  // time (baked into ENTITIES), shown in two clear groups.
  const e = ENTITIES[String(id)];
  if(!e || (!e.email.length && !e.portal.length)) return '';
  const total = e.email.length + e.portal.length;
  let h = `<div class="entities-card"><div class="entities-head">🏢 الجهات التي تم التقديم عليها<span class="count-pill">${total}</span></div>`;
  if(e.email.length){
    h += `<div class="ent-sub">📧 عبر الإيميل</div><div class="entities">`;
    e.email.forEach((a,i)=>{
      const name = a.company || a.email;
      const sub  = a.company ? `<span class="ent-mail">${a.email}</span>` : '';
      h += `<div class="entity-chip"><span class="entity-num">${i+1}</span><span class="ent-name">${name}${sub}</span></div>`;
    });
    h += `</div>`;
  }
  if(e.portal.length){
    h += `<div class="ent-sub">🏢 عبر البورتالات / المواقع</div><div class="entities">`;
    e.portal.forEach((p,i)=>{
      const cnt = p.count>1 ? `<span class="ent-cnt">${p.count}×</span>` : '';
      h += `<div class="entity-chip"><span class="entity-num">${i+1}</span><span class="ent-name">${p.company}</span>${cnt}</div>`;
    });
    h += `</div>`;
  }
  return h + `</div>`;
}

function showClient(id){
  if(!DATA)return;
  const c=DATA.clients.find(x=>x.id===id);
  if(!c)return;
  currentClient=c;
  document.getElementById('dashboard').style.display='none';
  const det=document.getElementById('detail');
  det.style.display='block';
  const acc=c.acc||[];
  const manualCount=acc.length+(c.linkedin||[]).length+(c.indeed||[]).length+(c.website||[]).length;
  const days=daysSince(c.dateIn);
  const isNew=days<=10;
  let html=`
  <button class="back-link" onclick="renderDashboard()">← الرئيسية</button>
  <div class="client-header">
    <h1>${c.name}</h1>
    <span class="client-email">${c.email}</span>
    <div class="client-badges">
      <span class="badge badge-total">${c.total} تقديم</span>
      <span class="badge badge-ai">إيميل: ${c.ac}</span>
      <span class="badge badge-m">مباشر: ${manualCount}</span>
      ${isNew?`<span class="badge badge-new">جديد · منذ ${days===0?'اليوم':days+' يوم'}</span>`:''}
    </div>
    ${c.dateIn?`<div class="date-label" style="margin-top:8px;font-size:11px;color:var(--muted)">تاريخ الانضمام: ${c.dateIn}</div>`:''}
  </div>`;
  html+=renderEntities(c.id);
  if(c.ai&&c.ai.length){
    html+=`<div class="app-section"><div class="app-section-title">📧 التقديم عبر الإيميل<span class="count-pill">${c.ai.length}</span></div>`;
    c.ai.forEach(a=>{html+=`<div class="app-item"><div class="app-title">${a.company}</div><span class="app-sub">${a.email}</span></div>`;});
    html+='</div>';
  }
  if(acc.length){
    html+=`<div class="app-section"><div class="app-section-title">🔑 دخول حساب<span class="count-pill">${acc.length}</span></div>`;
    acc.forEach(e=>{html+=`<div class="app-item"><div class="app-title">${e.title}</div>${e.company?`<span class="app-sub">${e.company}</span>`:''}</div>`;});
    html+='</div>';
  }
  if(c.linkedin&&c.linkedin.length){
    html+=`<div class="app-section"><div class="app-section-title">💼 LinkedIn<span class="count-pill">${c.linkedin.length}</span></div>`;
    c.linkedin.forEach(e=>{html+=`<div class="app-item"><div class="app-title">${e.title}</div>${e.company?`<span class="app-sub">${e.company}</span>`:''}</div>`;});
    html+='</div>';
  }
  if(c.website&&c.website.length){
    html+=`<div class="app-section"><div class="app-section-title">🌐 Website<span class="count-pill">${c.website.length}</span></div>`;
    c.website.forEach(e=>{html+=`<div class="app-item"><div class="app-title">${e.title}</div>${e.company?`<span class="app-sub">${e.company}</span>`:''}</div>`;});
    html+='</div>';
  }
  if(c.indeed&&c.indeed.length){
    html+=`<div class="app-section"><div class="app-section-title">🔍 Indeed<span class="count-pill">${c.indeed.length}</span></div>`;
    c.indeed.forEach(e=>{html+=`<div class="app-item"><div class="app-title">${e.title}</div>${e.company?`<span class="app-sub">${e.company}</span>`:''}</div>`;});
    html+='</div>';
  }
  if(!c.total)html+='<div class="empty">لا توجد تقديمات بعد.</div>';
  html+=`<div class="bottom-space"></div>
  <div class="copy-bar">
    <button class="btn btn-blue" style="width:100%;margin-bottom:8px" onclick="copyText(buildEntitiesText(currentClient.id))">🏢 نسخ تقرير الجهات</button>
    <div class="copy-row">
      <button class="btn btn-mint" onclick="copyText(currentClient.copyText)">📋 نسخ الكل</button>
      <button class="btn btn-orange" onclick="copyToday(currentClient.id)">📋 نسخ اليوم</button>
    </div>
  </div>`;
  det.innerHTML=html;
  det.scrollTop=0;
  window.scrollTo(0,0);
}

function fetchData(){
  const lb=document.getElementById('liveBadge');
  const nb=document.getElementById('nowBadge');
  lb.textContent='● جاري التحديث...';
  lb.style.background='#fef3c7';
  lb.style.color='#92400e';
  fetch(API)
    .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})
    .then(function(d){
      DATA=d;
      const prevId=currentClient?currentClient.id:null;
      if(prevId){
        const updated=DATA.clients.find(x=>x.id===prevId);
        if(updated){currentClient=updated;}
      }
      const onDetail=document.getElementById('detail').style.display==='block';
      if(!onDetail){renderDashboard();}
      nb.textContent=d.now;
      lb.textContent='● LIVE';
      lb.style.background='#d1fae5';
      lb.style.color='#059669';
      if(refreshTimer)clearTimeout(refreshTimer);
      refreshTimer=setTimeout(fetchData,5*60*1000);
    })
    .catch(function(e){
      lb.textContent='● خطأ';
      lb.style.background='#fef2f2';
      lb.style.color='#991b1b';
      if(!DATA){
        document.getElementById('dashboard').innerHTML=
          '<div class="error-box">تعذّر الاتصال بالسيرفر<br><small>'+e.message+'</small></div>';
      }
      if(refreshTimer)clearTimeout(refreshTimer);
      refreshTimer=setTimeout(fetchData,30*1000);
    });
}

function copyAllTodayReports(){
  var parts=[];
  if(DATA){
    DATA.clients.forEach(function(c){
      var text=TODAY_COPY[String(c.id)];
      if(text && text.indexOf('\u0627\u0644\u0625\u062c\u0645\u0627\u0644\u064a: 0 ')===-1){
        parts.push(text);
      }
    });
  } else {
    Object.keys(TODAY_COPY).forEach(function(id){
      var text=TODAY_COPY[id];
      if(text && text.indexOf('\u0627\u0644\u0625\u062c\u0645\u0627\u0644\u064a: 0 ')===-1){
        parts.push(text);
      }
    });
  }
  if(parts.length===0){showToast('\u0644\u0627 \u062a\u0642\u062f\u064a\u0645\u0627\u062a \u0627\u0644\u064a\u0648\u0645');return;}
  copyText(parts.join('\n\n\u2015\u2015\u2015\u2015\u2015\u2015\u2015\u2015\n\n'));
  showToast('\u062a\u0645 \u0646\u0633\u062e ' + parts.length + ' \u062a\u0642\u0631\u064a\u0631 \u2713');
}

fetchData();
</script>
</body>
</html>"""

os.makedirs("docs", exist_ok=True)
with open("docs/index.html", "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"Done: docs/index.html generated (TODAY_COPY for {len(today_copy)} clients, built {build_label})")
