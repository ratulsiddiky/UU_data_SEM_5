from flask import Blueprint, request, jsonify, current_app
from pymongo import MongoClient
import bcrypt
import jwt
import datetime
from functools import wraps

# Create the Blueprint
users_bp = Blueprint('users', __name__)

# Connect to the database
client = MongoClient("mongodb://127.0.0.1:27017")
db = client.smart_agri_db


# -------------------------------------------------------
# JWT DECORATOR
# Protects any route it is applied to - taken from BE08 lecture
# and adapted to also pass the full user object through so we
# can check things like the user's role inside the route
# -------------------------------------------------------

def jwt_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Look for the token in the Authorization header
        # Format expected: "Bearer <token>"
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]
        
        if not token:
            return jsonify({'message': 'Token is missing! Please log in first.'}), 401
        
        try:
            # Decode the token using our secret key
            data = jwt.decode(
                token,
                current_app.config['SECRET_KEY'],
                algorithms=["HS256"]
            )
            # Fetch the full user document so routes can access role etc.
            current_user = db.users.find_one({"username": data['username']})
            
            if not current_user:
                return jsonify({'message': 'User account not found.'}), 401
        
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Your session has expired. Please log in again.'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Token is invalid!'}), 401
        
        return f(current_user, *args, **kwargs)
    return decorated


# -------------------------------------------------------
# REGISTER - Create a new user account
# Takes username, password and optional role in the request body
# -------------------------------------------------------

@users_bp.route('/api/users/register', methods=['POST'])
def register():
    data = request.get_json()
    
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'message': 'Username and password are required'}), 400
    
    # Check the username isn't already taken
    existing_user = db.users.find_one({'username': data['username']})
    if existing_user:
        return jsonify({'message': 'That username is already taken, please choose another'}), 409
    
    # Hash the password with bcrypt before storing - never store plain text
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(data['password'].encode('utf-8'), salt)
    
    new_user = {
        "username":           data['username'],
        "password":           hashed_password.decode('utf-8'),
        # Default role is 'user' unless admin is specified
        "role":               data.get('role', 'user'),
        "contact_preference": data.get('contact_preference', 'email'),
        "created_at":         datetime.datetime.utcnow()
    }
    
    db.users.insert_one(new_user)
    
    return jsonify({'message': f"Account created for {data['username']}!"}), 201


# -------------------------------------------------------
# LOGIN - Authenticate and get a JWT token back
# Uses HTTP Basic Auth (username + password in the headers)
# Token lasts 30 minutes then expires
# -------------------------------------------------------

@users_bp.route('/api/login', methods=['POST'])
def login():
    auth = request.authorization
    
    if not auth or not auth.username or not auth.password:
        return jsonify({'message': 'Missing username or password'}), 401
    
    # Look the user up in the database
    user = db.users.find_one({'username': auth.username})
    if not user:
        return jsonify({'message': 'User not found'}), 404
    
    # Compare the provided password against the stored bcrypt hash
    if bcrypt.checkpw(auth.password.encode('utf-8'), user['password'].encode('utf-8')):
        
        token = jwt.encode(
            {
                'username': user['username'],
                'role':     user['role'],
                'exp':      datetime.datetime.utcnow() + datetime.timedelta(minutes=30)
            },
            current_app.config['SECRET_KEY'],
            algorithm="HS256"
        )
        
        return jsonify({
            'message':  'Login successful!',
            'token':    token,
            'username': user['username'],
            'role':     user['role']
        }), 200
    
    return jsonify({'message': 'Incorrect password'}), 401


# -------------------------------------------------------
# GET ALL USERS - Admin only
# Useful for testing and admin dashboards
# Passwords are excluded from the response for security
# -------------------------------------------------------

@users_bp.route('/api/users', methods=['GET'])
@jwt_required
def get_all_users(current_user):
    if current_user.get('role') != 'admin':
        return jsonify({'message': 'Admin access required'}), 403
    
    users_cursor = db.users.find({}, {"password": 0})  # exclude password field
    users_list = []
    
    for user in users_cursor:
        user['_id'] = str(user['_id'])
        users_list.append(user)
    
    return jsonify({
        "count": len(users_list),
        "users": users_list
    }), 200