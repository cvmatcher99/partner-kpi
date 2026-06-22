from flask import Flask, render_template, jsonify, abort
import psycopg2
import psycopg2.extras
from datetime import datetime

app = Flask(__name__)

DB = dict(host="77.243.85.225", database="tabashir",
          user="postgres", password="tabashir2025", connect_timeout=8)

def db():
    return psycopg2.connect(**DB, cursor_factory=psycopg2.extras.RealDictCursor)


def parse_title_company(job_title):
    """Split 'Title | Company' into (title, company)."""
    for sep in [" | ", " — ", " - "]:
        if sep in job_title:
            parts = job_title.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return job_title.strip(), ""


def categorize_link(link):
    if not link:
        return "other"
    l = link.lower()
    if "linkedin.com" in l:
        return "linkedin"
    if "indeed.com" in l:
        return "indeed"
    return "website"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    conn = db()
    cur  = conn.cursor()

    # KPI totals
    cur.execute("""
        SELECT
            COUNT(DISTINCT c.id)                                    AS total_clients,
            COALESCE(SUM(c.jobs_to_apply_number), 0)                AS total_target,
            COUNT(DISTINCT ma.id)                                   AS total_manual,
            COALESCE(SUM(ra.ai_count), 0)                          AS total_ai
        FROM clients c
        LEFT JOIN manual_applications ma ON ma.client_id = c.id
        LEFT JOIN (
            SELECT LOWER(email) AS em, COUNT(*) AS ai_count
            FROM rankings WHERE status = 'applied'
            GROUP BY LOWER(email)
        ) ra ON ra.em = LOWER(c.email)
        WHERE c.is_partner = TRUE
    """)
    kpi = dict(cur.fetchone())
    kpi["total_apps"] = int(kpi["total_manual"]) + int(kpi["total_ai"])

    # Per-client list
    cur.execute("""
        SELECT c.id, c.name, c.email,
               COUNT(DISTINCT ma.id)           AS manual_count,
               COALESCE(ra.ai_count, 0)        AS ai_count,
               c.jobs_to_apply_number          AS target
        FROM clients c
        LEFT JOIN manual_applications ma ON ma.client_id = c.id
        LEFT JOIN (
            SELECT LOWER(email) AS em, COUNT(*) AS ai_count
            FROM rankings WHERE status = 'applied'
            GROUP BY LOWER(email)
        ) ra ON ra.em = LOWER(c.email)
        WHERE c.is_partner = TRUE
        GROUP BY c.id, c.name, c.email, c.jobs_to_apply_number, ra.ai_count
        ORDER BY (COUNT(DISTINCT ma.id) + COALESCE(ra.ai_count, 0)) DESC, c.name
    """)
    clients = []
    for r in cur.fetchall():
        d = dict(r)
        total = int(d["manual_count"]) + int(d["ai_count"])
        target = int(d["target"] or 0)
        d["total_apps"] = total
        d["pct"] = min(100, int(total * 100 / target) if target > 0 else 0)
        clients.append(d)

    conn.close()
    return render_template("index.html", kpi=kpi, clients=clients,
                           now=datetime.now().strftime("%d %b %Y, %H:%M"))


@app.route("/client/<int:client_id>")
def client_detail(client_id):
    conn = db()
    cur  = conn.cursor()

    cur.execute("SELECT id, name, email FROM clients WHERE id=%s AND is_partner=TRUE",
                (client_id,))
    row = cur.fetchone()
    if not row:
        abort(404)
    client = dict(row)

    # AI email apps
    cur.execute("""
        SELECT r.job_title, r.job_application_email,
               COALESCE(j.company_name, '') AS company_name,
               r.date
        FROM rankings r
        LEFT JOIN jobs j ON r.job_id = j.id::text
        WHERE LOWER(r.email) = LOWER(%s) AND r.status = 'applied'
        ORDER BY r.date DESC, r.id DESC
    """, (client["email"],))
    ai_apps = [dict(r) for r in cur.fetchall()]

    # Manual apps
    cur.execute("""
        SELECT job_title, job_link, app_date, status
        FROM manual_applications
        WHERE client_id = %s
        ORDER BY app_date DESC, id DESC
    """, (client_id,))
    manual_raw = [dict(r) for r in cur.fetchall()]
    conn.close()

    linkedin, indeed, website, other = [], [], [], []
    for m in manual_raw:
        cat = categorize_link(m.get("job_link", ""))
        title, company = parse_title_company(m.get("job_title", ""))
        m["parsed_title"]   = title
        m["parsed_company"] = company
        if cat == "linkedin":
            linkedin.append(m)
        elif cat == "indeed":
            indeed.append(m)
        elif cat == "website":
            website.append(m)
        else:
            other.append(m)

    return render_template("client.html",
                           client=client,
                           ai_apps=ai_apps,
                           linkedin=linkedin,
                           indeed=indeed,
                           website=website,
                           other=other)


@app.route("/api/report/<int:client_id>")
def api_report(client_id):
    conn = db()
    cur  = conn.cursor()

    cur.execute("SELECT name, email FROM clients WHERE id=%s AND is_partner=TRUE",
                (client_id,))
    row = cur.fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    client = dict(row)

    cur.execute("""
        SELECT r.job_application_email,
               COALESCE(j.company_name, r.job_title) AS company_name
        FROM rankings r
        LEFT JOIN jobs j ON r.job_id = j.id::text
        WHERE LOWER(r.email) = LOWER(%s) AND r.status = 'applied'
        ORDER BY r.date DESC, r.id DESC
    """, (client["email"],))
    ai_apps = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT job_title, job_link
        FROM manual_applications
        WHERE client_id = %s
        ORDER BY app_date DESC
    """, (client_id,))
    manual_raw = [dict(r) for r in cur.fetchall()]
    conn.close()

    linkedin, indeed, website, other = [], [], [], []
    for m in manual_raw:
        cat = categorize_link(m.get("job_link", ""))
        title, company = parse_title_company(m.get("job_title", ""))
        entry = {"title": title, "company": company, "link": m.get("job_link", "")}
        if cat == "linkedin":
            linkedin.append(entry)
        elif cat == "indeed":
            indeed.append(entry)
        elif cat == "website":
            website.append(entry)
        else:
            other.append(entry)

    lines = []
    lines.append(f"*تقرير العميل:* *{client['name']}*")

    if ai_apps:
        lines.append("التقديم عبر الإيميلات")
        for a in ai_apps:
            lines.append(f"{a['company_name']} — {a['job_application_email']}")

    if linkedin:
        lines.append("التقديم عبر LinkedIn")
        for e in linkedin:
            line = e["title"]
            if e["company"]:
                line += f" — {e['company']}"
            lines.append(line)

    if indeed:
        lines.append("التقديم عبر Indeed")
        for e in indeed:
            line = e["title"]
            if e["company"]:
                line += f" — {e['company']}"
            lines.append(line)

    if website:
        lines.append("التقديم عبر الموقع الإلكتروني")
        for e in website:
            line = e["title"]
            if e["company"]:
                line += f" — {e['company']}"
            lines.append(line)

    if other:
        lines.append("تقديمات أخرى")
        for e in other:
            line = e["title"]
            if e["company"]:
                line += f" — {e['company']}"
            lines.append(line)

    total = len(ai_apps) + len(linkedin) + len(indeed) + len(website) + len(other)
    lines.append(f"\nالإجمالي: {total} تقديم | {datetime.now().strftime('%d/%m/%Y')}")

    return jsonify({"text": "\n".join(lines)})


if __name__ == "__main__":
    import os
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
