from flask import Blueprint, jsonify, request
from pymongo import MongoClient
import requests
from datetime import datetime
from bson.objectid import ObjectId

# Import the JWT decorator from routes_users so we can protect routes
from routes_users import jwt_required

# Create the Blueprint
farms_bp = Blueprint('farms', __name__)

# Connect to the database
client = MongoClient("mongodb://127.0.0.1:27017")
db = client.smart_agri_db


# -------------------------------------------------------
# OWNERSHIP HELPER
# Called by every route that modifies or reads private data
# on a specific farm. A user is allowed through if they are
# either the owner of that farm OR an admin.
#
# Returns (farm, None)        if access is granted
# Returns (None, error_response) if access is denied
# -------------------------------------------------------

def get_farm_if_authorised(farm_id, current_user):
    # First make sure the ID is a valid MongoDB ObjectId
    try:
        oid = ObjectId(farm_id)
    except:
        return None, (jsonify({"message": "Invalid farm ID format"}), 400)

    # Try to find the farm in the database
    farm = db.farms.find_one({"_id": oid})
    if not farm:
        return None, (jsonify({"message": "Farm not found"}), 404)

    # Admins can access any farm regardless of ownership
    if current_user.get('role') == 'admin':
        return farm, None

    # For regular users, compare the farm's owner_id to the logged-in user's _id
    # Both need to be strings for a reliable comparison
    if str(farm['owner_id']) != str(current_user['_id']):
        return None, (
            jsonify({"message": "Access denied. You can only manage your own farms."}),
            403
        )

    # User is the owner - grant access
    return farm, None


# -------------------------------------------------------
# GET ALL FARMS - Public, no login needed
# Returns a summary list of every farm
# -------------------------------------------------------

@farms_bp.route('/api/farms', methods=['GET'])
def get_all_farms():
    farms_cursor = db.farms.find({})
    farms_list = []

    for farm in farms_cursor:
        farm['_id']      = str(farm['_id'])
        farm['owner_id'] = str(farm['owner_id'])
        farms_list.append(farm)

    return jsonify(farms_list), 200


# -------------------------------------------------------
# GET A SINGLE FARM - Public
# Anyone can view the details of a specific farm
# -------------------------------------------------------

@farms_bp.route('/api/farms/<farm_id>', methods=['GET'])
def get_single_farm(farm_id):
    try:
        farm = db.farms.find_one({"_id": ObjectId(farm_id)})
    except:
        return jsonify({"message": "Invalid farm ID format"}), 400

    if not farm:
        return jsonify({"message": "Farm not found"}), 404

    farm['_id']      = str(farm['_id'])
    farm['owner_id'] = str(farm['owner_id'])
    return jsonify(farm), 200


# -------------------------------------------------------
# CREATE A FARM - Requires login
# Any authenticated farmer can register a new farm.
# The farm is automatically linked to whoever is logged in.
# -------------------------------------------------------

@farms_bp.route('/api/farms', methods=['POST'])
@jwt_required
def create_farm(current_user):
    data = request.get_json()

    if not data or not data.get('farm_name'):
        return jsonify({"message": "Please provide at least a farm_name"}), 400

    # Tie this farm to the logged-in user so ownership is set from the start
    data['owner_id'] = current_user['_id']

    # Make sure all sub-document arrays exist even if the request didn't include them
    data.setdefault('sensors', [])
    data.setdefault('weather_logs', [])
    data.setdefault('alerts_history', [])
    data['created_at'] = datetime.now()

    result = db.farms.insert_one(data)

    # 201 Created is the correct status code when a new resource is made
    return jsonify({
        "message":  "Farm registered successfully!",
        "farm_id":  str(result.inserted_id)
    }), 201


# -------------------------------------------------------
# UPDATE A FARM - Requires login + must be owner or admin
# Farmers can only update their own farms.
# Admins can update any farm.
# -------------------------------------------------------

@farms_bp.route('/api/farms/<farm_id>', methods=['PUT'])
@jwt_required
def update_farm(current_user, farm_id):
    # Check the user actually owns this farm (or is admin) before touching it
    farm, err = get_farm_if_authorised(farm_id, current_user)
    if err:
        return err

    data = request.get_json()
    if not data:
        return jsonify({"message": "No update data provided"}), 400

    # Only allow changes to safe top-level fields.
    # Blocking owner_id, sensors etc. from being changed this way.
    allowed_fields = ['farm_name', 'crop_type', 'address', 'location']
    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if not updates:
        return jsonify({
            "message": f"No valid fields provided. Updatable fields are: {allowed_fields}"
        }), 400

    db.farms.update_one({"_id": ObjectId(farm_id)}, {"$set": updates})

    return jsonify({"message": "Farm updated successfully!"}), 200


# -------------------------------------------------------
# DELETE A FARM - Requires login + admin role only
# Ownership check still applies so an admin can't be spoofed
# by a farmer passing a valid token - the role check handles that.
# -------------------------------------------------------

@farms_bp.route('/api/farms/<farm_id>', methods=['DELETE'])
@jwt_required
def delete_farm(current_user, farm_id):
    # Only admins are allowed to permanently delete farm records
    if current_user.get('role') != 'admin':
        return jsonify({"message": "Admin access required to delete a farm"}), 403

    try:
        result = db.farms.delete_one({"_id": ObjectId(farm_id)})
    except:
        return jsonify({"message": "Invalid farm ID format"}), 400

    if result.deleted_count == 0:
        return jsonify({"message": "Farm not found, nothing was deleted"}), 404

    return jsonify({"message": "Farm deleted successfully"}), 200


# -------------------------------------------------------
# ADD A SENSOR - Requires login + must be owner or admin
# Uses MongoDB $push to append a new sensor sub-document
# to the farm's sensors array without replacing everything.
# -------------------------------------------------------

@farms_bp.route('/api/farms/<farm_id>/sensors', methods=['POST'])
@jwt_required
def add_sensor(current_user, farm_id):
    # Verify ownership before allowing any changes to this farm
    farm, err = get_farm_if_authorised(farm_id, current_user)
    if err:
        return err

    data = request.get_json()
    if not data or not data.get('sensor_id') or not data.get('type'):
        return jsonify({"message": "sensor_id and type are required"}), 400

    new_sensor = {
        "sensor_id": data['sensor_id'],
        "type":      data['type'],
        "status":    data.get('status', True),  # defaults to active
        "readings":  data.get('readings', [])                          # starts empty, readings come in over time
    }

    # $push appends to the array without overwriting the rest of the document
    db.farms.update_one(
        {"_id": ObjectId(farm_id)},
        {"$push": {"sensors": new_sensor}}
    )

    return jsonify({
        "message": "Sensor added to farm!",
        "sensor":  new_sensor
    }), 201


# -------------------------------------------------------
# ADVANCED FEATURE 1 - Complex Text Search
# Uses the compound text index on area_name + postcode
# to let users search across both fields at once
# -------------------------------------------------------

@farms_bp.route('/api/farms/search', methods=['GET'])
def search_farms():
    search_term = request.args.get('q')

    if not search_term:
        return jsonify({"message": "Please provide a search term using ?q="}), 400

    search_results = db.farms.find({"$text": {"$search": search_term}})

    farms_list = []
    for farm in search_results:
        farm['_id']      = str(farm['_id'])
        farm['owner_id'] = str(farm['owner_id'])
        farms_list.append(farm)

    return jsonify({
        "results_count": len(farms_list),
        "data":          farms_list
    }), 200


# -------------------------------------------------------
# ADVANCED FEATURE 2 - External Weather Sync
# Requires login + must be owner or admin.
# Calls Open-Meteo (free, no API key) using the farm's GPS
# coordinates and pushes the result into weather_logs.
# -------------------------------------------------------

@farms_bp.route('/api/farms/<farm_id>/sync_weather', methods=['POST'])
@jwt_required
def sync_weather(current_user, farm_id):
    # Only the farm's owner or an admin should be able to trigger a weather sync
    farm, err = get_farm_if_authorised(farm_id, current_user)
    if err:
        return err

    # GeoJSON coordinates are stored as [longitude, latitude]
    lng = farm['location']['coordinates'][0]
    lat = farm['location']['coordinates'][1]

    weather_url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lng}&current_weather=true"
    )

    try:
        response        = requests.get(weather_url)
        weather_data    = response.json()
        current_weather = weather_data.get('current_weather', {})

        new_log = {
            "timestamp":           datetime.now(),
            "temperature_celsius": current_weather.get('temperature'),
            "windspeed":           current_weather.get('windspeed'),
            "conditions":          "Synced from Open-Meteo API"
        }

        db.farms.update_one(
            {"_id": ObjectId(farm_id)},
            {"$push": {"weather_logs": new_log}}
        )

        return jsonify({
            "message": "Weather synced successfully!",
            "new_log": new_log
        }), 200

    except Exception as e:
        return jsonify({
            "message": "Could not connect to the weather API",
            "error":   str(e)
        }), 500


# -------------------------------------------------------
# ADVANCED FEATURE 3 - Geospatial Disaster Alert Broadcast
# Admin only. Takes a GeoJSON polygon representing a danger
# zone and pushes an alert into every farm inside that area.
# -------------------------------------------------------

@farms_bp.route('/api/farms/alerts/broadcast', methods=['POST'])
@jwt_required
def broadcast_alert(current_user):
    # Emergency alerts should only be sent by admins
    if current_user.get('role') != 'admin':
        return jsonify({"message": "Admin access required to broadcast alerts"}), 403

    data = request.get_json()

    if not data or 'alert_type' not in data or 'danger_zone' not in data:
        return jsonify({
            "message": "Please provide alert_type and danger_zone (GeoJSON Polygon)"
        }), 400

    danger_zone = data['danger_zone']
    alert_type  = data['alert_type']

    # MongoDB $geoWithin finds every farm Point inside the polygon
    geo_query = {
        "location": {
            "$geoWithin": {
                "$geometry": danger_zone
            }
        }
    }

    affected_farms = list(db.farms.find(geo_query))

    alert_entry = {
        "alert_type": alert_type,
        "timestamp":  datetime.now(),
        "message":    f"EMERGENCY: {alert_type} warning issued for your area!",
        "issued_by":  current_user.get('username', 'admin')
    }

    # Update all matching farms in a single operation
    db.farms.update_many(geo_query, {"$push": {"alerts_history": alert_entry}})

    return jsonify({
        "message":        "Alert broadcast successfully!",
        "farms_notified": len(affected_farms),
        "alert_type":     alert_type
    }), 200


# -------------------------------------------------------
# HUMAN-CENTRED FEATURE 1 - Crop Insights Dashboard
# Requires login + must be owner or admin.
# Aggregation pipeline that calculates average temperature
# and windspeed from a farm's stored weather logs.
# -------------------------------------------------------

@farms_bp.route('/api/farms/<farm_id>/insights', methods=['GET'])
@jwt_required
def get_farm_insights(current_user, farm_id):
    # Private analytics - only the owner or admin should see this
    farm, err = get_farm_if_authorised(farm_id, current_user)
    if err:
        return err

    try:
        pipeline = [
            # Stage 1 - select only the farm we want
            {"$match": {"_id": ObjectId(farm_id)}},

            # Stage 2 - unpack weather_logs so each entry becomes
            # its own row we can run calculations on
            {"$unwind": "$weather_logs"},

            # Stage 3 - group back together and compute averages
            {"$group": {
                "_id":                 "$_id",
                "farm_name":           {"$first": "$farm_name"},
                "average_temp":        {"$avg": "$weather_logs.temperature_celsius"},
                "average_wind":        {"$avg": "$weather_logs.windspeed"},
                "total_logs_analysed": {"$sum": 1}
            }}
        ]

        result = list(db.farms.aggregate(pipeline))

        if not result:
            return jsonify({"message": "Not enough weather data to generate insights yet."}), 404

        insights        = result[0]
        insights['_id'] = str(insights['_id'])

        if insights.get('average_temp'):
            insights['average_temp'] = round(insights['average_temp'], 2)
        if insights.get('average_wind'):
            insights['average_wind'] = round(insights['average_wind'], 2)

        return jsonify({
            "message":        "Crop insights generated!",
            "dashboard_data": insights
        }), 200

    except Exception as e:
        return jsonify({"message": "Error generating insights", "error": str(e)}), 500


# -------------------------------------------------------
# HUMAN-CENTRED FEATURE 2 - Personalised Irrigation Check
# Requires login + must be owner or admin.
# Reads the most recent soil moisture sensor reading and
# tells the farmer whether irrigation is needed today.
# -------------------------------------------------------

@farms_bp.route('/api/farms/<farm_id>/irrigation_check', methods=['GET'])
@jwt_required
def check_irrigation(current_user, farm_id):
    # Sensor data is private to the farm owner
    farm, err = get_farm_if_authorised(farm_id, current_user)
    if err:
        return err

    try:
        moisture_level = None

        for sensor in farm.get('sensors', []):
            if sensor.get('type') == 'Soil Moisture':
                # Readings are stored as an array - we want the most recent one
                readings = sensor.get('readings', [])
                if readings:
                    moisture_level = readings[-1]['value']
                break

        if moisture_level is None:
            return jsonify({"message": "No soil moisture sensor found on this farm."}), 404

        # Below 20% means the soil is too dry and needs watering
        if moisture_level < 20.0:
            return jsonify({
                "status":          "WARNING",
                "moisture_level":  moisture_level,
                "action_required": "Soil moisture is critically low. Turn on irrigation immediately!"
            }), 200
        else:
            return jsonify({
                "status":          "OK",
                "moisture_level":  moisture_level,
                "action_required": "Moisture levels are healthy. No watering needed today."
            }), 200

    except Exception as e:
        return jsonify({"message": "Error checking irrigation status", "error": str(e)}), 500


# -------------------------------------------------------
# HUMAN-CENTRED FEATURE 3 - Regional Community Averages
# Public - aggregated community data doesn't expose any
# individual farm's private information so no auth needed.
# -------------------------------------------------------

@farms_bp.route('/api/farms/region/<region_name>/insights', methods=['GET'])
def get_regional_insights(region_name):
    try:
        pipeline = [
            # Stage 1 - only look at farms in the requested region
            {"$match": {"address.area_name": region_name}},

            # Stage 2 - unpack weather logs across all matched farms
            {"$unwind": "$weather_logs"},

            # Stage 3 - group everything together for community averages
            {"$group": {
                "_id":                 region_name,
                "community_avg_temp":  {"$avg": "$weather_logs.temperature_celsius"},
                "community_avg_wind":  {"$avg": "$weather_logs.windspeed"},
                # addToSet builds a unique list of farm IDs contributing to the average
                "unique_farms":        {"$addToSet": "$_id"}
            }},

            # Stage 4 - round the numbers and count how many farms contributed
            {"$project": {
                "community_avg_temp":   {"$round": ["$community_avg_temp", 2]},
                "community_avg_wind":   {"$round": ["$community_avg_wind", 2]},
                "total_farms_included": {"$size": "$unique_farms"}
            }}
        ]

        result = list(db.farms.aggregate(pipeline))

        if not result:
            return jsonify({
                "message": f"No weather data found for farms in {region_name}."
            }), 404

        return jsonify({
            "message":       f"Community averages for {region_name}",
            "regional_data": result[0]
        }), 200

    except Exception as e:
        return jsonify({"message": "Error generating regional insights", "error": str(e)}), 500