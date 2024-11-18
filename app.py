#!/usr/bin/env python
# coding: utf-8

# In[1]:


from flask import Flask, request, jsonify
import requests
import logging
import math
import sqlite3
import os
import datetime
import psycopg2
from dotenv import load_dotenv
from sqlalchemy import create_engine

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

print("Environment:", os.getenv("FLASK_ENV"))

# Set Flask environment (development or production)
app.config['ENV'] = os.getenv('FLASK_ENV')

# Set the database URL (this could be SQLite in development, PostgreSQL in production)
app.config['DATABASE_URL'] = os.getenv('DATABASE_URL')

# Sample route to show environment
@app.route('/')
def index():
    response_text = f"Flask Server Running in {app.config['ENV']} mode with database at {app.config['DATABASE_URL']}"
    return jsonify({"status": "success", "response": response_text}), 200

@app.route('/health')
def health_check():
    return "Healthy", 200

def connect_db():
    #return sqlite3.connect('solar.db')

    database_url = os.getenv('DATABASE_URL')
    
    if 'sqlite' in database_url:
        # SQLite connection
        conn = sqlite3.connect(database_url.replace('sqlite:///', ''))
        return conn
    else:
        # For production (PostgreSQL, MySQL, etc.), use SQLAlchemy or appropriate driver
        engine = create_engine(database_url)
        return engine.connect()

def connect_db():
    # Get database URL from environment
    database_url = os.getenv('DATABASE_URL')
    
    if 'sqlite' in database_url:
        # SQLite connection using sqlite3
        conn = sqlite3.connect(database_url.replace('sqlite:///', ''))
        return conn
    elif 'postgresql' in database_url:
        # PostgreSQL connection using psycopg2 directly (if DATABASE_URL is in psycopg2 format)
        return psycopg2.connect(database_url)
    else:
        # For other databases, fallback to SQLAlchemy engine
        engine = create_engine(database_url)
        return engine.connect()  # SQLAlchemy connection object (no cursor)

# API Keys for OpenWeather and NREL
# Sample OpenWeather API hit: https://api.openweathermap.org/geo/1.0/zip?zip=302018,IN&appid=b85b4f3bc72115fd17559cfd0f4a89a4
OPENWEATHER_API_KEY = 'b85b4f3bc72115fd17559cfd0f4a89a4'
# Sample NREL API https://developer.nrel.gov/api/pvwatts/v6.json?api_key=fErquINi4UerOUSqSCaoGVR9hC1X8G7RY1oxSanc&lat=26.8468&lon=75.7924&system_capacity=5&module_type=1&losses=10&array_type=1&tilt=20&azimuth=180
NREL_API_KEY = 'fErquINi4UerOUSqSCaoGVR9hC1X8G7RY1oxSanc'
GUPSHUP_URL = 'https://api.gupshup.io/wa/api/v1/msg'
GUPSHUP_API_KEY = '2dvow1vgfzmtyyoekitrmeu0vtco0m4a'  # Replace with your actual API key


# Internal Error Codes 
# Error Code 10001: Could not fetch solar potential from NREL
# Error Code 10002: Incorrect PINCODE entered

# Temporary in-memory store for user data and conversation state
user_data = {}

# Function to get state from pincode using PostPincode API
def get_state_from_pincode(pincode):
    url = f"https://api.postalpincode.in/pincode/{pincode}"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        if data[0]['Status'] == 'Success':
            state = data[0]['PostOffice'][0]['State']
            app.logger.debug(f"User State received : {data[0]['Status']}, {data[0]['PostOffice'][0]['State']}") 
            return state
        else:
            return "Unknown in get_state_from_pincode"  # If pincode is not valid
    else:
        return "Error in get_state_from_pincode"  # Handle request failure

# Function to get lat/lon from pincode using OpenWeather API
def get_lat_lon_from_pincode(pincode):
    geo_url = f"https://api.openweathermap.org/geo/1.0/zip?zip={pincode},IN&appid={OPENWEATHER_API_KEY}"
    response = requests.get(geo_url)
    data = response.json()
    if response.status_code == 200 and data:
        return data['lat'], data['lon']
    else:
        return None, None

def get_tariff_for_state(state):
    conn = connect_db()
    cursor = conn.cursor()
    
    # Query for tariffs for the given state
    query = "SELECT min_slab, max_slab, fixed, variable, max_bill FROM tariffs WHERE state = %s"
    cursor.execute(query, (state,))
    
    tariffs = cursor.fetchall()
    conn.close()

    if not tariffs:  # If no data for the given state, use Rajasthan's tariffs
        app.logger.debug(f"No tariffs found for {state}. Using Rajasthan's tariffs as default.")
        state = "Rajasthan"  # Default state to Rajasthan
        conn = connect_db()
        cursor = conn.cursor()
        query = "SELECT min_slab, max_slab, fixed, variable, max_bill FROM tariffs WHERE state = %s"
        cursor.execute(query, (state,))
        tariffs = cursor.fetchall()
        conn.close()

    # Convert the fetched data to the required format
    result = []
    for row in tariffs:
        result.append({
            'min_slab': int(row[0]),
            'max_slab': int(row[1]),
            'fixed': float(row[2]),
            'variable': float(row[3]),
            'max_bill': float(row[4]) if row[4] is not None else None
        })
    
    return result


# Using NREL API to get solar generation for every month
def get_solar_generation(lat, lon, system_capacity=1):
    nrel_url = f"https://developer.nrel.gov/api/pvwatts/v6.json?api_key={NREL_API_KEY}&lat={lat}&lon={lon}&system_capacity={system_capacity}&module_type=1&losses=10&array_type=1&tilt=20&azimuth=180"
    response = requests.get(nrel_url)
    # Example response: { 'ac_monthly': [545, 600, 700, ...]
    data = response.json()
    if response.status_code == 200 and 'outputs' in data:
        return data['outputs']['ac_monthly'], data['outputs']['solrad_annual']
    else:
        return None, None

#def estimate_energy_consumption(bill_amount):
 #   avg_rate_per_kwh = 6  # Assuming an average rate of ₹6 per kWh
  #  return bill_amount / avg_rate_per_kwh

# Helper function to calculate system size based on energy consumption and rooftop area
def calculate_system_size(monthly_consumption, rooftop_area, ac_monthly):
    """
    Calculate the solar system size based on monthly energy consumption and solar generation (AC output).
    
    Parameters:
    monthly_consumption (dict): User's monthly energy consumption (in kWh).
    ac_monthly (list): Monthly AC output from the NREL API (in kWh per kW of system capacity).
    
    Returns:
    system_size (float): Estimated system size in kW.
    """
    # Total annual energy consumption by the user
    total_annual_consumption = sum(monthly_consumption)  # in kWh
    
    # Total annual solar generation (per kW of installed capacity)
    total_annual_generation_per_kw = sum(ac_monthly)  # in kWh
    
    # Calculate the required system size (in kW)
    system_size_by_energy = total_annual_consumption / total_annual_generation_per_kw

    sq_ft_per_kw = 120  # 1 kW requires 120 sq ft of area
    system_size_by_area = rooftop_area / sq_ft_per_kw    

    return min(system_size_by_energy, system_size_by_area)


# def calculate_system_size(energy_consumption, rooftop_area, solar_potential):
#     kwh_per_kw = solar_potential * 30  # Solar potential per month (kWh/m²/day)
#     sq_ft_per_kw = 100  # 1 kW requires 100 sq ft of area
#     system_size_by_energy = energy_consumption / kwh_per_kw
#     system_size_by_area = rooftop_area / sq_ft_per_kw
#     return min(system_size_by_energy, system_size_by_area)

# Helper function to get location tier for estimating cost
def get_location_tier_from_pincode(pincode):
    location_tier = "Tier-1" 
    return location_tier

# Helper function to calculate cost and subsidy
def calculate_cost_and_subsidy(system_size, location_tier):
    conn = connect_db()
    cursor = conn.cursor()
    
    # Query for tariffs for the given state
    query = "SELECT overall_cost FROM installation_costs WHERE location_tier = %s AND system_capacity_kW = %s"
    cursor.execute(query, (location_tier,system_size))
    
    overall_cost_queried = cursor.fetchone()
    conn.close()
    
    if overall_cost_queried is None:  # If no data for the given location & system size, use max cost
        app.logger.debug(f"MISSING DATA: No cost found for {location_tier} and {system_size}kW. Using Max Cost as default.")
        overall_cost = 1000000  # Set to default value
    else:
        overall_cost = overall_cost_queried[0]
        app.logger.debug(f"Final overall cost received for {location_tier} and {system_size}kW is {overall_cost}.")

    # Government subsidy logic
    if system_size >= 3:
        subsidy = 78000
    elif system_size == 2:
        subsidy = 60000
    else:
        subsidy = 30000
    
    # Net metering charges logic
    if system_size >= 3:
        net_metering = 25000
    elif system_size == 2:
        net_metering = 17500
    else:
        net_metering = 10000
    
    app.logger.debug(f"For {system_size}kW - Subsidy: ₹{subsidy}, Net Metering: ₹{net_metering}")
    
    # Final cost = Overall cost - Subsidy + Net Metering
    final_cost = overall_cost - subsidy + net_metering
    app.logger.debug(f"Cost breakdown - Overall: ₹{overall_cost}, Subsidy: ₹{subsidy}, Net Metering: ₹{net_metering}, Final: ₹{final_cost}")

    return final_cost

# Helper function to get previous month
def get_previous_month():
    # Get the current date
    current_date = datetime.datetime.now()
    
    # Subtract one month to get the previous month
    previous_month_date = current_date.replace(day=1) - datetime.timedelta(days=1)
    
    # Format the month to its first 3 letters (e.g., 'Jan', 'Feb', etc.)
    previous_month = previous_month_date.strftime("%b")  # 'Jan', 'Feb', 'Mar', etc.
    app.logger.debug(f"Previous Month is : {previous_month}")   
    return previous_month

def calculate_monthly_bills_for_year(recent_bill, num_acs, current_month, state):
    conn = connect_db()
    cursor = conn.cursor()
    
    # Fetch multiplier factors for the given state
    query = "SELECT month, multiplier FROM multipliers WHERE state = %s"
    cursor.execute(query, (state,))
    multipliers = cursor.fetchall()
    conn.close()

    if not multipliers:  # If no data for the given state, use Rajasthan's multipliers
        app.logger.debug(f"No multipliers found for {state}. Using Rajasthan's multipliers as default.")
        state = "Rajasthan"  # Default state to Rajasthan
        conn = connect_db()
        cursor = conn.cursor()
        query = "SELECT month, multiplier FROM multipliers WHERE state = %s"
        cursor.execute(query, (state,))
        multipliers = cursor.fetchall()
        conn.close()

    # Create a dictionary for multipliers, like {'Jan': 1.1, 'Feb': 1.05, ...}
    multipliers_dict = {month: multiplier for month, multiplier in multipliers}
    
    # Find the multiplier for the current month (month of the recent bill)
    current_month_multiplier = multipliers_dict[current_month]
    
    # Normalize the multipliers relative to the current month
    normalized_multipliers = {month: multiplier / current_month_multiplier for month, multiplier in multipliers_dict.items()}
    
    # Calculate bills for each month using the normalized multipliers
    monthly_bills = []
    i = 0
    for month, normalized_multiplier in normalized_multipliers.items():
        monthly_bills.append(recent_bill * float(normalized_multiplier))
        app.logger.debug(f"Multiplication executed successfully calculate_monthly_bills_for_year")        
        if i>1 and i<6:
            monthly_bills[i] += num_acs*3000
        i += 1

    app.logger.debug(f"Monthly bills are : {monthly_bills}")   
    return monthly_bills

# Helper function to calculate monthly consumption
def calculate_monthly_consumption(monthly_bills, tariffs):
    monthly_consumption = []
    for bill in monthly_bills:
        consumption, slab_used = estimate_energy_consumption_with_max_bill(bill, tariffs)
        monthly_consumption.append(consumption)
    return monthly_consumption

# Helper function to estimate energy consumption based on bill amount
def estimate_energy_consumption_with_max_bill(bill_amount, tariffs):
    for slab in tariffs:
        if slab['max_bill'] is None or bill_amount <= slab['max_bill']:
            fixed_charge = slab['fixed']
            variable_charges = bill_amount - fixed_charge
            units_consumed = variable_charges / slab['variable']
            app.logger.debug(f"Slab used is: {slab}")    
            return int(units_consumed), slab
    return 0, None  # If no slab is found

def calculate_yearly_savings(monthly_savings):
    total_savings = sum(monthly_savings)
    return total_savings

def calculate_monthly_savings_with_solar(monthly_consumption, monthly_generation, tariffs):
    monthly_savings = []
    i = 0
    for consumption in monthly_consumption:
        generation = int(monthly_generation[i])
        
        # Step 1: Calculate the reduced consumption (after solar generation)
        reduced_consumption = max(0, int(consumption) - generation)  # Ensure reduced consumption is not negative
        app.logger.debug(f"Reduced consumption for Month={i} is: {reduced_consumption}") 

        # Step 2: Calculate the original bill based on the original consumption
        original_bill = round(calculate_monthly_bill(int(consumption), tariffs))  # Round to integer
        app.logger.debug(f"original Bill Amount for Month={i} is: {original_bill}")                   
        
        # Step 3: Calculate the reduced bill based on reduced consumption
        reduced_bill = round(calculate_monthly_bill(reduced_consumption, tariffs))  # Round to integer
        app.logger.debug(f"reduced Bill Amount for Month={i} is: {reduced_bill}")                   
       
        # Step 4: Calculate savings (original bill - reduced bill)
        savings = round(original_bill - reduced_bill)  # Round to integer
        monthly_savings.append(savings)
        app.logger.debug(f"Monthly Savings for Month={i} is: {savings}")
        i+=1              
    
    return monthly_savings

def calculate_monthly_bill(units_consumed, tariffs):
    """
    Calculate the electricity bill based on slab tariffs.
    
    Parameters:
    units_consumed (float): The amount of electricity consumed in kWh.
    tariffs (list): The slab-based tariffs for the state.
    
    Returns:
    float: The calculated monthly bill.
    """
    bill = 0
    for slab in tariffs:
        
        slab_units = 0
        if units_consumed > slab['max_slab']:
            continue
        else:
            bill = units_consumed * slab['variable'] + slab['fixed']
            break
        
    return bill


def send_message(message, to_number):
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'apikey': GUPSHUP_API_KEY
    }
    
    # Payload format based on the cURL request
    payload = {
        'source': '917834811114',  # Replace with your WhatsApp sandbox number
        'destination': to_number,  # The recipient's phone number
        'message': message,
        'src.name': 'QuoteGenerator'  # Replace with your app name or bot name
    }

    # Sending the POST request to Gupshup API
    response = requests.post(GUPSHUP_URL, headers=headers, data=payload)
    app.logger.debug(f"Message sent: {response.status_code}, {response.text}")    
    
    return response.status_code, response.text

# @app.route('/webhook', methods=['POST'])
# def call_back_Set():
#     #rocess the incoming data for testing purpose
#     if incoming_data:
#         return jsonify({"status": "success"}), 200
#     else:
#         return jsonify({"status": "error"}), 400

def calculate_system_size_for_target_reduction(monthly_consumption, rooftop_area, ac_monthly, reduction_target=1.0):
    """
    Calculate system size considering monthly variations in consumption and generation.
    Uses peak monthly consumption to ensure adequate coverage.
    """
    
    # Calculate required size for each month
    monthly_sizes = []
    for i in range(12):
        if ac_monthly[i] > 0:  # Avoid division by zero
            # Size needed for this month = (consumption * reduction_target) / generation_per_kw
            size_needed = (monthly_consumption[i] * reduction_target) / ac_monthly[i]
            monthly_sizes.append(size_needed)
            app.logger.debug(f"Month {i+1}: Consumption={monthly_consumption[i]}, "
                           f"Generation per kW={ac_monthly[i]}, Size needed={size_needed}")
    
    # Use the maximum monthly size needed to ensure coverage in peak months
    system_size_by_energy = max(monthly_sizes)
    app.logger.debug(f"Maximum system size needed by energy: {system_size_by_energy}")
    
    # Calculate size limitation by area
    sq_ft_per_kw = 120
    system_size_by_area = rooftop_area / sq_ft_per_kw    
    app.logger.debug(f"System size limited by area: {system_size_by_area}")
    
    # Get final recommended size
    recommended_size = min(system_size_by_energy, system_size_by_area)
    app.logger.debug(f"Final recommended size for {reduction_target*100}% reduction: {recommended_size}")
    
    return recommended_size

# Add the new function here
def find_optimal_system_size(monthly_consumption, rooftop_area, ac_monthly, state_tariffs, location_tier):
    """
    Find optimal system size considering both ROI and savings.
    Picks between top 2 ROI options, favoring higher savings if ROIs are similar.
    """
    best_options = []  # List to store top 2 options
    max_possible_size = min(int(rooftop_area / 120), 10)  # Limited by area and practical max of 10kW, rounded down
    
    app.logger.debug(f"Starting optimal size calculation - Rooftop area: {rooftop_area} sq ft, Max possible size: {max_possible_size}kW")
    app.logger.debug(f"Monthly consumption pattern: {monthly_consumption}")
    app.logger.debug(f"Monthly generation per kW pattern: {ac_monthly}")
    
    # Test different system sizes in 1kW increments
    for size in range(1, max_possible_size + 1):
        app.logger.debug(f"\nTesting system size: {size}kW")
        
        # Calculate generation for this size
        monthly_generation = [g * size for g in ac_monthly]
        app.logger.debug(f"Monthly generation for {size}kW: {monthly_generation}")
        
        # Calculate savings
        monthly_savings = calculate_monthly_savings_with_solar(
            monthly_consumption,
            monthly_generation,
            state_tariffs
        )
        yearly_savings = calculate_yearly_savings(monthly_savings)
        app.logger.debug(f"Monthly savings for {size}kW: {monthly_savings}")
        app.logger.debug(f"Yearly savings for {size}kW: ₹{yearly_savings}")
        
        # Calculate cost
        system_cost = calculate_cost_and_subsidy(size, location_tier)
        app.logger.debug(f"System cost for {size}kW: ₹{system_cost}")
        
        # Calculate ROI
        roi = (yearly_savings / system_cost) * 100
        app.logger.debug(f"ROI for {size}kW: {roi}%")
        
        # Store option
        option = {
            'size': size,
            'roi': roi,
            'yearly_savings': yearly_savings,
            'system_cost': system_cost
        }
        
        # Keep track of top 2 options by ROI
        best_options.append(option)
        best_options.sort(key=lambda x: x['roi'], reverse=True)
        best_options = best_options[:2]  # Keep only top 2
        app.logger.debug(f"Current top options: {best_options}")
    
    if len(best_options) < 2:
        optimal_size = best_options[0]['size']
        app.logger.debug(f"Only one option available. Selecting size: {optimal_size}kW")
        return optimal_size
    
    # Compare top 2 options
    roi_difference = abs(best_options[0]['roi'] - best_options[1]['roi'])
    savings_ratio = best_options[1]['yearly_savings'] / best_options[0]['yearly_savings']
    
    app.logger.debug(f"\nComparing top 2 options:")
    app.logger.debug(f"Option 1: Size={best_options[0]['size']}kW, ROI={best_options[0]['roi']}%, Savings=₹{best_options[0]['yearly_savings']}")
    app.logger.debug(f"Option 2: Size={best_options[1]['size']}kW, ROI={best_options[1]['roi']}%, Savings=₹{best_options[1]['yearly_savings']}")
    app.logger.debug(f"ROI difference: {roi_difference}%, Savings ratio: {savings_ratio}")
    
    # If ROIs are within 5% of each other and second option has at least 20% more savings
    if roi_difference < 5 and savings_ratio > 1.2:
        optimal_size = best_options[1]['size']
        app.logger.debug(f"Selected second option due to significantly higher savings with similar ROI")
    else:
        optimal_size = best_options[0]['size']
        app.logger.debug(f"Selected first option due to better ROI")
    
    app.logger.debug(f"\nOptimal system size calculation complete:")
    app.logger.debug(f"Final optimal size: {optimal_size}kW")
    app.logger.debug(f"Selected option details:")
    app.logger.debug(f"ROI: {best_options[0]['roi'] if optimal_size == best_options[0]['size'] else best_options[1]['roi']}%")
    app.logger.debug(f"Yearly savings: ₹{best_options[0]['yearly_savings'] if optimal_size == best_options[0]['size'] else best_options[1]['yearly_savings']}")
    app.logger.debug(f"System cost: ₹{best_options[0]['system_cost'] if optimal_size == best_options[0]['size'] else best_options[1]['system_cost']}")
    
    return optimal_size

@app.route('/webhook', methods=['POST'])
def solar_cost_estimator():
    try:
        incoming_data = request.json
        app.logger.debug(f"Received data: {incoming_data}")
        
        # Ensure incoming data is valid
        if not incoming_data:
            app.logger.error("No data received")
            return jsonify({"status": "error", "message": "Invalid data"}), 400

        #Handling different event types here
        event_type = incoming_data.get('type', None)
        payload = incoming_data.get('payload', {})

        if event_type == 'message-event':
            # Handle message events like sent, delivered, read, failed, etc.
            message_type = payload.get('type', None)
            if message_type in ['sent', 'delivered', 'read', 'failed', 'enqueued']:
                app.logger.debug(f"Message event of type {message_type}")
                # Add logic based on message status (e.g., handle failure reasons)
                return jsonify({"status": "message-event received", "message_type": message_type}), 200

        elif event_type == 'user-event':
            # Handle user events like opted-in or opted-out
            user_event_type = payload.get('type', None)
            app.logger.debug(f"User event of type {user_event_type}")
            if user_event_type == 'sandbox-start':
                app.logger.debug(f"Received Gupshup Callback Set {user_event_type}")
                return jsonify({"status": "callback set successfully", "user_event_type": user_event_type}), 200
            elif user_event_type in ['opted-in', 'opted-out']:
                return jsonify({"status": "user-event received", "user_event_type": user_event_type}), 200

        elif event_type == 'system-event':
            # Handle system events
            app.logger.debug("System event received")
            return jsonify({"status": "system-event received"}), 200

        elif event_type == 'billing-event':
            # Handle billing events
            app.logger.debug("Billing event received")
            return jsonify({"status": "billing-event received"}), 200

        elif event_type == 'message':
            # Handle incooming messages 
            app.logger.debug("Message received")
            user_phone = payload.get('sender', {}).get('phone')

            if user_phone not in user_data:
                user_data[user_phone] = {'step': 0}
            
            # Retrieve the current state of the user conversation
            user_state = user_data[user_phone]
            user_step = user_state['step']
            message_text = payload.get('payload', {}).get('text', '').lower()
            
            if user_step == 0:
                # Send greeting and ask for pincode
                user_data[user_phone]['step'] = 1
                response_text = "Hello, I am NavyamBot. I can help you generate a cost estimate for installing rooftop solar. To begin, please enter your pincode."
                app.logger.debug(f"Response: {response_text}")
                send_message(response_text, user_phone)
                return jsonify({"status": "success", "response": response_text}), 200
            
            # Replace step where pincode is processed (user_step == 1)
            elif user_step == 1:
                # Get lat/lon from pincode
                user_data[user_phone]['pincode'] = message_text
                lat, lon = get_lat_lon_from_pincode(message_text)
                user_data[user_phone]['state'] = get_state_from_pincode(message_text)
                if lat is None or lon is None or user_data[user_phone]['state'] is None:
                    response_text = "Invalid pincode. Please try again."
                    send_message(response_text, user_phone)
                    return jsonify({"status": "error", "response": response_text}), 400

                user_data[user_phone]['step'] = 1.5

                # Fetch solar potential from NREL using lat/lon
                ac_monthly, solrad_annual = get_solar_generation(lat, lon)
                if ac_monthly is None or solrad_annual is None:
                    response_text = "[ERROR10001] We have encountered an issue. Please contact support@navyamhomes.com and share Error Code 10001."
                    send_message(response_text, user_phone)
                    return jsonify({"status": "error", "response": response_text}), 500

                # Proceed with asking for summer bill
                user_data[user_phone]['pincode'] = message_text      
                user_data[user_phone]['solar_potential'] = solrad_annual
                user_data[user_phone]['ac_monthly'] = ac_monthly
                app.logger.debug(f"Received Monthly generation units: {user_data[user_phone]['ac_monthly']}")   
                response_text = f"Solar potential for your location is {solrad_annual:.2f} kWh/m²/day. Now, please enter your most recent electricity bill."
                app.logger.debug(f"Response: {response_text}")
                send_message(response_text, user_phone)
                return jsonify({"status": "success", "response": response_text}), 200

            elif user_step == 1.5:
                # Save the recent bill and Ask for number of ACs
                user_data[user_phone]['recent_bill_month'] = get_previous_month()  # Get the previous month (based on current month)
                user_data[user_phone]['recent_bill'] = float(message_text)

                user_data[user_phone]['step'] = 2

                app.logger.debug(f"Received Monthly Bill in step {user_step}")   
                response_text = f"How many ACs do you use in your house?"
                app.logger.debug(f"Response: {response_text}")
                send_message(response_text, user_phone)
                return jsonify({"status": "success", "response": response_text}), 200                          

            elif user_step == 2:
                # Save number of ACs and Ask for rooftop area 
                user_data[user_phone]['num_acs'] = int(message_text)
                user_data[user_phone]['monthly_bills'] = calculate_monthly_bills_for_year(user_data[user_phone]['recent_bill'], user_data[user_phone]['num_acs'], user_data[user_phone]['recent_bill_month'], user_data[user_phone]['state'])

                # Load tariff data from SQLite
                state_tariffs = get_tariff_for_state(user_data[user_phone]['state'])
                app.logger.debug(f"Received Tarifs for: {user_data[user_phone]['state']}")   

                # Estimate energy consumption
                user_data[user_phone]['monthly_consumption'] = calculate_monthly_consumption(user_data[user_phone]['monthly_bills'], state_tariffs)
                app.logger.debug(f"calculated Monthly consumption units: {user_data[user_phone]['monthly_consumption']}")   
                user_data[user_phone]['step'] = 3
                
                response_text = f"Please enter your rooftop area (in square feet)"
                app.logger.debug(f"Response: {response_text}")
                send_message(response_text, user_phone)
                return jsonify({"status": "success", "response": response_text}), 200
            
            elif user_step == 3:
                app.logger.debug("Starting step 3 calculations")
                user_data[user_phone]['rooftop_area'] = int(message_text)
                user_data[user_phone]['step'] = 4
                
                monthly_ac_generation_per_kW = user_data[user_phone]['ac_monthly']
                monthly_energy_consumption = user_data[user_phone]['monthly_consumption']
                rooftop_area = user_data[user_phone]['rooftop_area']
                
                app.logger.debug(f"Input data - Rooftop area: {rooftop_area}, Monthly consumption: {monthly_energy_consumption}")

                # Calculate system sizes for all options
                app.logger.debug("Calculating full offset system size")
                full_offset_size = calculate_system_size_for_target_reduction(
                    monthly_energy_consumption, 
                    rooftop_area, 
                    monthly_ac_generation_per_kW, 
                    1.0
                )
                
                app.logger.debug("Calculating half offset system size")
                half_offset_size = calculate_system_size_for_target_reduction(
                    monthly_energy_consumption, 
                    rooftop_area, 
                    monthly_ac_generation_per_kW, 
                    0.5
                )

                # Get state tariffs and location tier for optimal calculation
                state_tariffs = get_tariff_for_state(user_data[user_phone]['state'])
                location_tier = get_location_tier_from_pincode(user_data[user_phone]['pincode'])
                app.logger.debug(f"State tariffs: {state_tariffs}, Location tier: {location_tier}")

                # Calculate optimal system size
                app.logger.debug("Calculating optimal system size")
                optimal_size = find_optimal_system_size(
                    monthly_energy_consumption,
                    rooftop_area,
                    monthly_ac_generation_per_kW,
                    state_tariffs,
                    location_tier
                )

                # Round sizes to nearest integer
                full_offset_size = round(full_offset_size)
                half_offset_size = round(half_offset_size)
                optimal_size = round(optimal_size)
                app.logger.debug(f"Rounded system sizes - Full: {full_offset_size}kW, Half: {half_offset_size}kW, Optimal: {optimal_size}kW")

                # Calculate generation for all options
                monthly_ac_generation_full = [g * full_offset_size for g in monthly_ac_generation_per_kW]
                monthly_ac_generation_half = [g * half_offset_size for g in monthly_ac_generation_per_kW]
                monthly_ac_generation_optimal = [g * optimal_size for g in monthly_ac_generation_per_kW]
                app.logger.debug(f"Monthly generation for full offset: {monthly_ac_generation_full}")
                app.logger.debug(f"Monthly generation for half offset: {monthly_ac_generation_half}")
                app.logger.debug(f"Monthly generation for optimal size: {monthly_ac_generation_optimal}")

                # Calculate savings for all options
                app.logger.debug("Calculating savings for full offset")
                monthly_savings_full = calculate_monthly_savings_with_solar(
                    monthly_energy_consumption, 
                    monthly_ac_generation_full, 
                    state_tariffs
                )
                yearly_savings_full = round(calculate_yearly_savings(monthly_savings_full) / 1000)
                app.logger.debug(f"Monthly savings full: {monthly_savings_full}, Yearly: {yearly_savings_full} Thousand")

                app.logger.debug("Calculating savings for half offset")
                monthly_savings_half = calculate_monthly_savings_with_solar(
                    monthly_energy_consumption, 
                    monthly_ac_generation_half, 
                    state_tariffs
                )
                yearly_savings_half = round(calculate_yearly_savings(monthly_savings_half) / 1000)
                app.logger.debug(f"Monthly savings half: {monthly_savings_half}, Yearly: {yearly_savings_half} Thousand")

                app.logger.debug("Calculating savings for optimal size")
                monthly_savings_optimal = calculate_monthly_savings_with_solar(
                    monthly_energy_consumption, 
                    monthly_ac_generation_optimal, 
                    state_tariffs
                )
                yearly_savings_optimal = round(calculate_yearly_savings(monthly_savings_optimal) / 1000)
                app.logger.debug(f"Monthly savings optimal: {monthly_savings_optimal}, Yearly: {yearly_savings_optimal} Thousand")

                # Calculate costs for all options
                final_cost_full = round(calculate_cost_and_subsidy(full_offset_size, location_tier) / 100000, 2)
                final_cost_half = round(calculate_cost_and_subsidy(half_offset_size, location_tier) / 100000, 2)
                final_cost_optimal = round(calculate_cost_and_subsidy(optimal_size, location_tier) / 100000, 2)
                app.logger.debug(f"Final costs - Full: ₹{final_cost_full} Lakhs, Half: ₹{final_cost_half} Lakhs, Optimal: ₹{final_cost_optimal} Lakhs")

                # Calculate ROI for all options
                roi_full = round((yearly_savings_full * 1000 / (final_cost_full * 100000)) * 100, 1)
                roi_half = round((yearly_savings_half * 1000 / (final_cost_half * 100000)) * 100, 1)
                roi_optimal = round((yearly_savings_optimal * 1000 / (final_cost_optimal * 100000)) * 100, 1)
                app.logger.debug(f"ROI calculations - Full: {roi_full}%, Half: {roi_half}%, Optimal: {roi_optimal}%")

                # Calculate terrace coverage for all options
                terrace_coverage_full = round((full_offset_size * 120) / rooftop_area * 100, 1)
                terrace_coverage_half = round((half_offset_size * 120) / rooftop_area * 100, 1)
                terrace_coverage_optimal = round((optimal_size * 120) / rooftop_area * 100, 1)
                app.logger.debug(f"Terrace coverage - Full: {terrace_coverage_full}%, Half: {terrace_coverage_half}%, Optimal: {terrace_coverage_optimal}%")

                # Format response with all three options
                response_text = (
                    f"Option 1 - Zero Electricity Bill:\n"
                    f"System size: {full_offset_size} kW\n"
                    f"Estimated cost: Around ₹{final_cost_full} Lakhs after subsidy\n"
                    f"Terrace Coverage: Around {terrace_coverage_full}%\n"
                    f"Estimated yearly savings: ₹{yearly_savings_full} Thousand\n"
                    f"Estimated ROI: {roi_full}% every year\n\n"
                    
                    f"Option 2 - Half Electricity Bill:\n"
                    f"System size: {half_offset_size} kW\n"
                    f"Estimated cost: Around ₹{final_cost_half} Lakhs after subsidy\n"
                    f"Terrace Coverage: Around {terrace_coverage_half}%\n"
                    f"Estimated yearly savings: ₹{yearly_savings_half} Thousand\n"
                    f"Estimated ROI: {roi_half}% every year\n\n"
                    
                    f"Option 3 - Maximum Returns:\n"
                    f"System size: {optimal_size} kW\n"
                    f"Estimated cost: Around ₹{final_cost_optimal} Lakhs after subsidy\n"
                    f"Terrace Coverage: Around {terrace_coverage_optimal}%\n"
                    f"Estimated yearly savings: ₹{yearly_savings_optimal} Thousand\n"
                    f"Estimated ROI: {roi_optimal}% every year\n"
                )

                app.logger.debug(f"Final response text: {response_text}")
                send_message(response_text, user_phone)
                return jsonify({"status": "success", "response": response_text}), 200

            else:
                response_text = "Sorry this is all that I can do for now. For further help & support with Solar roof top installation, please contact us on support@navyamhomes.com or 8884024446"
                app.logger.debug(f"Response: {response_text}")
                send_message(response_text, user_phone)
                del user_data[user_phone]
                return jsonify({"status": "success", "response": response_text}), 200

            # Clean up user data
            del user_data[user_phone]



        return jsonify({"status": "ERROR CODE: 10003 Unknown event type received from Gupshup"}), 400

    except Exception as e:
        app.logger.error(f"Error occurred: {e}")
        return jsonify({"status": "error", "message": str(e)}),500

if __name__ == '__main__':
    app.run()
