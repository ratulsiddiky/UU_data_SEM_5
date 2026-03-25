from flask import Flask, jsonify
from pymongo import MongoClient

app = Flask(__name__)

# Connect to MongoDB
client = MongoClient("mongodb://127.0.0.1:27017")
db = client.smart_agri_db

# Secret key for JWT Authentication
app.config['SECRET_KEY'] = 'your_super_secret_key_for_1st_class_grade'

# Register our blueprints here
from routes_users import users_bp
app.register_blueprint(users_bp)

from routes_farms import farms_bp
app.register_blueprint(farms_bp)


# A simple base route to test the server
@app.route('/', methods=['GET'])
def home():
    return jsonify({"message": "Welcome to the Smart Agriculture API!"}), 200

if __name__ == '__main__':
    app.run(debug=True, port=5001)