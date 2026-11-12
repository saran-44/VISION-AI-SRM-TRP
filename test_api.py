import requests
import json

url = 'http://localhost:5000/api/drivers'
headers = {'Content-Type': 'application/json'}
data = {
    "name": "Dwight Schrute",
    "phone": "999-888-7777",
    "allottedBus": "22",
    "busRegNo": "TN 45 XX 9999",
    "rcNumber": "RC999",
    "insurance": "Jan 2030",
    "notes": "Assistant (to the) Regional Manager",
    "photo": "https://ui-avatars.com/api/?name=Dwight+Schrute&background=2563eb&color=fff&size=80"
}

try:
    response = requests.post(url, headers=headers, data=json.dumps(data))
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")
