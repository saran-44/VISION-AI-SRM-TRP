import json
import urllib.request

url = "https://api.github.com/repos/saran-44/VISION-AI-SRM-TRP/actions/runs?per_page=10"
req = urllib.request.Request(url, headers={"User-Agent": "Python"})
try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        runs = data.get("workflow_runs", [])
        for r in runs:
            print(f"Run ID: {r['id']}, Name: {r['name']}, Branch: {r['head_branch']}, Status: {r['status']}, Conclusion: {r['conclusion']}")
            print(f"  Commit: {r['head_sha'][:7]} - {r['head_commit']['message'].splitlines()[0] if r.get('head_commit') else ''}")
            
            # Fetch individual jobs for the latest run on fix/audit-remediation or main
            if r['head_branch'] in ('fix/audit-remediation', 'main'):
                jobs_url = r['jobs_url']
                j_req = urllib.request.Request(jobs_url, headers={"User-Agent": "Python"})
                with urllib.request.urlopen(j_req) as j_resp:
                    j_data = json.loads(j_resp.read().decode("utf-8"))
                    for j in j_data.get("jobs", []):
                        print(f"    Job: {j['name']} -> {j['conclusion']} ({j['status']})")
                print()
except Exception as e:
    print("Error querying GitHub API:", e)
