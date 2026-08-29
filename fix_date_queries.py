"""Fix queries for Daily Ticket Creation and Daily Resolutions in Metabase."""
import urllib.request, json

login = json.dumps({"username": "admin@gmail.com", "password": "Admin@321#"}).encode()
req = urllib.request.Request("http://metabase:3000/api/session", data=login, headers={"Content-Type": "application/json"})
token = json.loads(urllib.request.urlopen(req).read())["id"]
headers = {"X-Metabase-Session": token, "Content-Type": "application/json"}

# 1. Update Daily Ticket Creation query (Cards 47, 64, 81)
q_creation = """
SELECT DATE(created_at) AS `Date`,
       COUNT(*) AS `Tickets Created`
FROM helpdesk_tickets
GROUP BY DATE(created_at)
ORDER BY DATE(created_at) ASC
"""

for card_id in [47, 64, 81]:
    try:
        req_c = urllib.request.Request("http://metabase:3000/api/card/%d" % card_id, headers=headers)
        card = json.loads(urllib.request.urlopen(req_c).read())
        ds = card["dataset_query"]
        for s in ds.get("stages", []):
            s["native"] = q_creation
        up_data = json.dumps({"dataset_query": ds}).encode()
        up_req = urllib.request.Request("http://metabase:3000/api/card/%d" % card_id, data=up_data, headers=headers, method="PUT")
        urllib.request.urlopen(up_req)
        print("Updated Card %d (Daily Ticket Creation)" % card_id)
    except Exception as e:
        print("Error updating card %d: %s" % (card_id, e))

# 2. Update Daily Resolutions query (Cards 48, 65, 82)
q_resolutions = """
SELECT DATE(updated_at) AS `Date`,
       COUNT(*) AS `Tickets Resolved`
FROM helpdesk_tickets
WHERE status = 'RESOLVED'
GROUP BY DATE(updated_at)
ORDER BY DATE(updated_at) ASC
"""

for card_id in [48, 65, 82]:
    try:
        req_c = urllib.request.Request("http://metabase:3000/api/card/%d" % card_id, headers=headers)
        card = json.loads(urllib.request.urlopen(req_c).read())
        ds = card["dataset_query"]
        for s in ds.get("stages", []):
            s["native"] = q_resolutions
        up_data = json.dumps({"dataset_query": ds}).encode()
        up_req = urllib.request.Request("http://metabase:3000/api/card/%d" % card_id, data=up_data, headers=headers, method="PUT")
        urllib.request.urlopen(up_req)
        print("Updated Card %d (Daily Resolutions)" % card_id)
    except Exception as e:
        print("Error updating card %d: %s" % (card_id, e))
