from pymongo import MongoClient
import random
from datetime import datetime, timedelta
import bcrypt

# Connect to local MongoDB
client = MongoClient("mongodb://127.0.0.1:27017")
db = client.smart_agri_db

# Clear existing collections to start fresh each time we run this
db.farms.drop()
db.users.drop()

print("Generating Smart Agriculture Dataset...")

# -------------------------------------------------------
# 1. GENERATE USERS
# One admin account and two regular farmer accounts
# All use "password123" as the password for easy testing
# -------------------------------------------------------

users_data = []
usernames = ["admin_user", "farmer_john", "farmer_mary"]
roles     = ["admin",      "user",        "user"]

for i in range(3):
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(b"password123", salt)
    
    users_data.append({
        "username":           usernames[i],
        "password":           hashed_password.decode('utf-8'),
        "role":               roles[i],
        "contact_preference": "email",
        "created_at":         datetime.now()
    })

inserted_users = db.users.insert_many(users_data)
user_ids = inserted_users.inserted_ids

print(f"  Created {len(user_ids)} users.")


# -------------------------------------------------------
# 2. GENERATE FARMS
# 50 farm plots spread across Northern Ireland
# Each farm has sensors with historical readings,
# weather logs, and a blank alerts history to start
# -------------------------------------------------------

crop_types = ["Wheat", "Corn", "Vineyard", "Soybeans", "Potatoes"]
areas      = ["Belfast", "Derry", "Lisburn", "Newry", "Armagh"]
postcodes  = ["BT7 1NN", "BT48 7NL", "BT28 1AB", "BT35 6PB", "BT60 1NT"]

# Rough centre of Northern Ireland for generating realistic coordinates
base_lat = 54.5
base_lng = -6.5

farms_data = []

for i in range(50):
    # Assign each farm to one of the two farmer accounts (not admin)
    owner_id   = random.choice(user_ids[1:])
    area_index = random.randint(0, 4)
    
    # Use a fixed base date so readings are reproducible and look historical
    # rather than being timestamped from whenever the script was last run
    base_date = datetime(2025, 1, 1) + timedelta(days=random.randint(0, 60))
    
    # Generate a set of IoT sensors for this farm
    sensors = []
    for j in range(random.randint(2, 5)):
        sensor_type = random.choice(["Soil Moisture", "Temperature", "pH Level"])
        
        # Each sensor has a week of historical readings
        readings = []
        for k in range(7):
            reading_time = base_date + timedelta(days=k)
            value        = round(random.uniform(10.0, 60.0), 2)
            readings.append({
                "timestamp": reading_time,
                "value":     value
            })
        
        sensors.append({
            "sensor_id": f"SEN-{i}-{j}",
            "type":      sensor_type,
            "status":    random.choice([True, True, False]),  # mostly active
            "readings":  readings
        })
    
    # Generate 3 historical weather log entries per farm
    weather_logs = []
    for w in range(3):
        log_time = base_date + timedelta(days=w)
        weather_logs.append({
            "timestamp":           log_time,
            "temperature_celsius": round(random.uniform(5.0, 25.0), 1),
            "windspeed":           round(random.uniform(5.0, 30.0), 1),
            "humidity_percent":    random.randint(40, 95),
            "conditions":          random.choice(["Clear", "Rain", "Cloudy", "Overcast"])
        })
    
    farm_document = {
        "farm_name": f"Farm Plot {i + 1}",
        "owner_id":  owner_id,
        "crop_type": random.choice(crop_types),
        "address": {
            "area_name": areas[area_index],
            "postcode":  postcodes[area_index]
        },
        "location": {
            "type": "Point",
            # Randomise coordinates slightly around Northern Ireland
            "coordinates": [
                round(base_lng + random.uniform(-1.0, 1.0), 4),
                round(base_lat + random.uniform(-0.5, 0.5), 4)
            ]
        },
        "sensors":        sensors,
        "weather_logs":   weather_logs,
        "alerts_history": []
    }
    farms_data.append(farm_document)

db.farms.insert_many(farms_data)
print(f"  Created 50 farms with sensors and weather logs.")


# -------------------------------------------------------
# 3. CREATE MONGODB INDEXES
# The 2dsphere index makes the geospatial queries work
# The text index powers the compound search endpoint
# -------------------------------------------------------

# Geospatial index - required for $geoWithin and $near queries
db.farms.create_index([("location", "2dsphere")])

# Compound text index - lets us search area name and postcode together
db.farms.create_index([
    ("address.area_name", "text"),
    ("address.postcode",  "text")
])

print("  Indexes created (2dsphere + compound text).")
print("\nDone! Login credentials for testing:")
print("  Admin:   username=admin_user  / password=password123")
print("  Farmer:  username=farmer_john / password=password123")
print("  Farmer:  username=farmer_mary / password=password123")