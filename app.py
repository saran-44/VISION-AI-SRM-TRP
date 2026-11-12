from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
import os

app = Flask(__name__)
# Allow requests from any origin (e.g. file:// from the browser)
CORS(app)

# MongoDB Connection String from User (password escaped with %40)
MONGO_URI = "mongodb+srv://mdhemanathan_db_user:srmtrp%40123@cluster0.1yk3nbg.mongodb.net/transport_db?retryWrites=true&w=majority"

# Initialize MongoDB Client
client = MongoClient(MONGO_URI)
db = client['transport_db'] # Database name
drivers_collection = db['drivers'] # Collection name

@app.route('/api/drivers', methods=['GET'])
def get_drivers():
    try:
        # Fetch all drivers from MongoDB
        drivers = list(drivers_collection.find({}, {'_id': 0})) # Exclude the MongoDB ObjectId from the response
        return jsonify(drivers), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/drivers', methods=['POST'])
def add_driver():
    try:
        data = request.json
        
        # Basic validation
        if not data or 'name' not in data:
            return jsonify({"error": "Invalid payload"}), 400
            
        # Insert into MongoDB
        result = drivers_collection.insert_one(data)
        
        return jsonify({"message": "Driver added successfully", "id": str(result.inserted_id)}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Run the Flask app on localhost port 5000
    print("Starting Transport API Server on http://localhost:5000")
    app.run(debug=True, port=5000)
