import duckdb
import requests

db = r"e:\ecom_dashboard\ecom_dashboard\design_intelligence.duckdb"
con = duckdb.connect(db, read_only=True)
try:
    row = con.execute(
        "select design_key, niche, sub_niche from design_master where lower(niche) like '%dog%' limit 1"
    ).fetchone()
    if not row:
        row = con.execute(
            "select design_key, niche, sub_niche from design_master limit 1"
        ).fetchone()
finally:
    con.close()

design_key, niche, sub_niche = row
print("sample:", design_key, niche, sub_niche)

story = requests.get("http://127.0.0.1:5000/api/design/story", params={"design_key": design_key}, timeout=30)
extend = requests.get(
    "http://127.0.0.1:5000/api/design/extend_suggestions",
    params={"design_key": design_key, "limit": 5},
    timeout=30,
)

print("story_status:", story.status_code)
sj = story.json()
print("story_has_design:", bool(sj.get("design")))
print("sources_count:", len(sj.get("sources", [])))
print("context_count:", len(sj.get("context", [])))

print("extend_status:", extend.status_code)
ej = extend.json()
print("extend_niche:", ej.get("niche"))
print("suggestions_count:", len(ej.get("suggestions", [])))
if ej.get("suggestions"):
    print("first_suggestion:", ej["suggestions"][0])

