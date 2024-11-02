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
    
    if not overall_cost_queried:  # If no data for the given location & system size, use max cost
        app.logger.debug(f"MISSING DATA: No cost found for {location_tier} and {system_size}kW. Using Max Cost as default.")
        overall_cost_queried[0] = 1000000
    else:
        app.logger.debug(f"Final overall cost received for {location_tier} and {system_size}kW is {overall_cost_queried[0]}.")

    # Government subsidy logic
    if system_size >= 3:
        subsidy = 78000
    elif system_size == 2:
        subsidy = 60000
    else:
        subsidy = 30000
    
    final_cost = overall_cost_queried[0] - subsidy

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
        original_bill = calculate_monthly_bill(int(consumption), tariffs)
        app.logger.debug(f"original Bill Amount for Month={i} is: {original_bill}")                   
        
        # Step 3: Calculate the reduced bill based on reduced consumption
        reduced_bill = calculate_monthly_bill(reduced_consumption, tariffs)
        app.logger.debug(f"reduced Bill Amount for Month={i} is: {reduced_bill}")                   
       
        # Step 4: Calculate savings (original bill - reduced bill)
        savings = original_bill - reduced_bill
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
                # Final step: calculate and send cost estimation
                user_data[user_phone]['rooftop_area'] = int(message_text)
                user_data[user_phone]['step'] = 4                
                #bill_amount = user_data[user_phone]['recent_bill']
                rooftop_area = user_data[user_phone]['rooftop_area']
                monthly_ac_generation_per_kW = user_data[user_phone]['ac_monthly']
                monthly_energy_consumption = user_data[user_phone]['monthly_consumption']
                app.logger.debug(f"Received monthly consumption: {user_data[user_phone]['monthly_consumption'] }")                   
                
                # Estimate energy consumption
                # energy_consumption = estimate_energy_consumption(bill_amount)
                
                # Calculate system size and cost, get state tariffs and location tier to calculate savings
                user_data[user_phone]['recommended_system_size'] = math.floor(calculate_system_size(monthly_energy_consumption, rooftop_area, monthly_ac_generation_per_kW))
                state_tariffs = get_tariff_for_state(user_data[user_phone]['state'])
                app.logger.debug(f"Received Tariffs to calculate savings: {state_tariffs}")
                location_tier = get_location_tier_from_pincode(user_data[user_phone]['pincode'])
                app.logger.debug(f"Location Tier received: {location_tier}")      

                option_num = 1      
                sq_ft_per_kw = 120  # 1 kW requires 120 sq ft of area

                # calculate generation for recommended system size - 1
                if (user_data[user_phone]['recommended_system_size'] - 1 > 0):
                    user_data[user_phone]['monthly_ac_generation_minus_1'] = []
                    for generation_per_month in monthly_ac_generation_per_kW:
                        user_data[user_phone]['monthly_ac_generation_minus_1'].append(generation_per_month*(user_data[user_phone]['recommended_system_size']-1))
                    app.logger.debug(f"Received monthly ac generation _minus_1 : {user_data[user_phone]['monthly_ac_generation_minus_1'] }")                   

                    # Calculate monthly savings
                    user_data[user_phone]['monthly_savings_minus_1'] = calculate_monthly_savings_with_solar(monthly_energy_consumption, user_data[user_phone]['monthly_ac_generation_minus_1'], state_tariffs)
                    app.logger.debug(f"Received Monthly savings _minus_1: {user_data[user_phone]['monthly_savings_minus_1']}")                   
                    user_data[user_phone]['yearly_savings_minus_1'] = calculate_yearly_savings(user_data[user_phone]['monthly_savings_minus_1'])
                    app.logger.debug(f"Received Yearly savings _minus_1: {user_data[user_phone]['yearly_savings_minus_1']}")                   

                    # calculating overall cost, subsidy from location tier
                    recommended_final_cost_minus_1 = calculate_cost_and_subsidy((user_data[user_phone]['recommended_system_size']-1), location_tier)
                    app.logger.debug(f"Recommended final cost _minus_1 is : {recommended_final_cost_minus_1}")                   
                    
                    # Round estimated costs up to the nearest lakhs with two decimal places
                    final_cost_lakhs_minus_1 = round(recommended_final_cost_minus_1 / 100000, 1)
                    app.logger.debug(f"Step 1 completed")                   

                    final_saving_thousands_minus_1 = round(user_data[user_phone]['yearly_savings_minus_1'] / 1000, 1)
                    app.logger.debug(f"Step 2 completed")                   

                    #ROI
                    user_data[user_phone]['roi_minus_1'] = round((user_data[user_phone]['yearly_savings_minus_1'] / float(recommended_final_cost_minus_1))*100,1)
                    app.logger.debug(f"Step 3 completed")                   

                    #Terrace Coverage
                    user_data[user_phone]['terrace_coverage_minus_1'] = round(((user_data[user_phone]['recommended_system_size']-1) * sq_ft_per_kw)/( user_data[user_phone]['rooftop_area'])*100,1)
                    app.logger.debug(f"Step 4 completed")                   

                    response_text = (
                        f"Option : {option_num}\n"
                        f"System size: {(user_data[user_phone]['recommended_system_size']-1)} kW\n"
                        f"Estimated cost: Around ₹{final_cost_lakhs_minus_1} Lakhs after subsidy.\n"
                        f"Terrace Coverage: Around {user_data[user_phone]['terrace_coverage_minus_1']}%.\n"
                        f"Estimated yearly savings: ₹{final_saving_thousands_minus_1} Thousand.\n"
                        f"Estimated ROI: {user_data[user_phone]['roi_minus_1']}% every year.\n\n"
                    )

                    option_num += 1
                    app.logger.debug(f"Exited _minus_1 calcultion with option_num: {option_num}")

                # calculate generation for recommended system size
                user_data[user_phone]['monthly_ac_generation'] = []
                for generation_per_month in monthly_ac_generation_per_kW:
                    user_data[user_phone]['monthly_ac_generation'].append(generation_per_month*user_data[user_phone]['recommended_system_size'])
                app.logger.debug(f"Received monthly ac generation: {user_data[user_phone]['monthly_ac_generation'] }")                   

                # Calculate monthly savings                 
                user_data[user_phone]['monthly_savings'] = calculate_monthly_savings_with_solar(monthly_energy_consumption, user_data[user_phone]['monthly_ac_generation'], state_tariffs)
                app.logger.debug(f"Received Monthly savings: {user_data[user_phone]['monthly_savings']}")                   
                user_data[user_phone]['yearly_savings'] = calculate_yearly_savings(user_data[user_phone]['monthly_savings'])
                app.logger.debug(f"Received Yearly savings: {user_data[user_phone]['yearly_savings']}")                   

                # calculating overall cost, subsidy from location tier             
                recommended_final_cost = calculate_cost_and_subsidy(user_data[user_phone]['recommended_system_size'], location_tier)
                app.logger.debug(f"Recommended final cost is : {recommended_final_cost}")                   
                
                # Round estimated costs up to the nearest lakhs with two decimal places
                final_cost_lakhs = round(recommended_final_cost / 100000, 1)
                final_saving_thousands = round(user_data[user_phone]['yearly_savings'] / 1000, 1)

                #ROI
                user_data[user_phone]['roi'] = round((user_data[user_phone]['yearly_savings'] / float(recommended_final_cost))*100,1)

                user_data[user_phone]['terrace_coverage'] = round(((user_data[user_phone]['recommended_system_size']) * sq_ft_per_kw)/( user_data[user_phone]['rooftop_area'])*100,1)

                response_text += (
                    f"Option {option_num}: \n"
                    f"System size: {user_data[user_phone]['recommended_system_size']} kW\n"
                    f"Estimated cost: Around ₹{final_cost_lakhs} Lakhs after subsidy.\n"
                    f"Terrace Coverage: Around {user_data[user_phone]['terrace_coverage']}%.\n"
                    f"Estimated yearly savings: ₹{final_saving_thousands} Thousand.\n"
                    f"Estimated ROI: {user_data[user_phone]['roi']}% every year.\n\n"
                )
                option_num += 1

                # calculate generation for recommended system size + 1
                user_data[user_phone]['monthly_ac_generation_plus_1'] = []
                for generation_per_month in monthly_ac_generation_per_kW:
                    user_data[user_phone]['monthly_ac_generation_plus_1'].append(generation_per_month*(user_data[user_phone]['recommended_system_size']+1))
                app.logger.debug(f"Received monthly ac generation for plus 1: {user_data[user_phone]['monthly_ac_generation_plus_1'] }")                   

                # Calculate monthly savings
                user_data[user_phone]['monthly_savings_plus_1'] = calculate_monthly_savings_with_solar(monthly_energy_consumption, user_data[user_phone]['monthly_ac_generation_plus_1'], state_tariffs)
                app.logger.debug(f"Received Monthly savings for plus 1: {user_data[user_phone]['monthly_savings_plus_1']}")                   
                user_data[user_phone]['yearly_savings_plus_1'] = calculate_yearly_savings(user_data[user_phone]['monthly_savings_plus_1'])
                app.logger.debug(f"Received Yearly savings for plus 1: {user_data[user_phone]['yearly_savings_plus_1']}")                   

                # calculating overall cost, subsidy from location tier
                recommended_final_cost_plus_1 = calculate_cost_and_subsidy((user_data[user_phone]['recommended_system_size']+1), location_tier)
                app.logger.debug(f"Recommended final cost for plus 1 is : {recommended_final_cost_plus_1}")                   
                
                # Round estimated costs up to the nearest lakhs with two decimal places
                final_cost_lakhs_plus_1 = round(recommended_final_cost_plus_1 / 100000, 1)
                final_saving_thousands_plus_1 = round(user_data[user_phone]['yearly_savings_plus_1'] / 1000, 1)

                #ROI
                user_data[user_phone]['roi_plus_1'] = round((user_data[user_phone]['yearly_savings_plus_1'] / float(recommended_final_cost_plus_1))*100,1)

                user_data[user_phone]['terrace_coverage_plus_1'] = round(((user_data[user_phone]['recommended_system_size']+1) * sq_ft_per_kw)/( user_data[user_phone]['rooftop_area'])*100,1)

                response_text += (
                    f"Option {option_num}: \n"
                    f"System size: {(user_data[user_phone]['recommended_system_size']+1)} kW\n"
                    f"Estimated cost: Around ₹{final_cost_lakhs_plus_1} Lakhs after subsidy.\n"
                    f"Terrace Coverage: Around {user_data[user_phone]['terrace_coverage_plus_1']}%.\n"
                    f"Estimated yearly savings: ₹{final_saving_thousands_plus_1} Thousand.\n"
                    f"Estimated ROI: {user_data[user_phone]['roi_plus_1']}% every year.\n\n"
                )

                option_num += 1

                if (user_data[user_phone]['recommended_system_size'] - 1 == 0):
                    # calculate generation for recommended system size + 2
                    user_data[user_phone]['monthly_ac_generation_plus_2'] = []
                    for generation_per_month in monthly_ac_generation_per_kW:
                        user_data[user_phone]['monthly_ac_generation_plus_2'].append(generation_per_month*(user_data[user_phone]['recommended_system_size']+2))
                    app.logger.debug(f"Received monthly ac generation for plus 2: {user_data[user_phone]['monthly_ac_generation_plus_2'] }")                   

                    # Calculate monthly savings
                    user_data[user_phone]['monthly_savings_plus_2'] = calculate_monthly_savings_with_solar(monthly_energy_consumption, user_data[user_phone]['monthly_ac_generation_plus_2'], state_tariffs)
                    app.logger.debug(f"Received Monthly savings for plus 2: {user_data[user_phone]['monthly_savings_plus_2']}")                   
                    user_data[user_phone]['yearly_savings_plus_2'] = calculate_yearly_savings(user_data[user_phone]['monthly_savings_plus_2'])
                    app.logger.debug(f"Received Yearly savings for plus 2: {user_data[user_phone]['yearly_savings_plus_2']}")                   

                    # calculating overall cost, subsidy from location tier
                    recommended_final_cost_plus_2 = calculate_cost_and_subsidy((user_data[user_phone]['recommended_system_size']+2), location_tier)
                    app.logger.debug(f"Recommended final cost for plus 2 is : {recommended_final_cost_plus_2}")                   
                    
                    # Round estimated costs up to the nearest lakhs with two decimal places
                    final_cost_lakhs_plus_2 = round(recommended_final_cost_plus_2 / 100000, 1)
                    final_saving_thousands_plus_2 = round(user_data[user_phone]['yearly_savings_plus_2'] / 1000, 1)

                    #ROI
                    user_data[user_phone]['roi_plus_2'] = round((user_data[user_phone]['yearly_savings_plus_2'] / float(recommended_final_cost_plus_2))*100,1)
                    
                    user_data[user_phone]['terrace_coverage_plus_2'] = round(((user_data[user_phone]['recommended_system_size']+2) * sq_ft_per_kw)/( user_data[user_phone]['rooftop_area'])*100,1)

                    response_text += (
                        f"Option {option_num}: \n"
                        f"System size: {(user_data[user_phone]['recommended_system_size']+2)} kW\n"
                        f"Estimated cost: Around ₹{final_cost_lakhs_plus_2} Lakhs after subsidy.\n"
                        f"Terrace Coverage: Around {user_data[user_phone]['terrace_coverage_plus_2']}%.\n"
                        f"Estimated yearly savings: ₹{final_saving_thousands_plus_2} Thousand.\n"
                        f"Estimated ROI: {user_data[user_phone]['roi_plus_2']}% every year.\n\n"
                    )

                if (user_data[user_phone]['roi_minus_1'] is not None):
                    user_data[user_phone]['max_roi'] = max(user_data[user_phone]['roi_minus_1'], user_data[user_phone]['roi'], user_data[user_phone]['roi_plus_1'])
                    if user_data[user_phone]['max_roi'] == user_data[user_phone]['roi_minus_1']:
                        user_data[user_phone]['recommended_option'] = 1
                    elif user_data[user_phone]['max_roi'] == user_data[user_phone]['roi']:
                        user_data[user_phone]['recommended_option'] = 2
                    else:
                        user_data[user_phone]['recommended_option'] = 3
                else:
                    user_data[user_phone]['max_roi'] = max(user_data[user_phone]['roi'], user_data[user_phone]['roi_plus_1'], user_data[user_phone]['roi_plus_2'])                    
                    if user_data[user_phone]['max_roi'] == user_data[user_phone]['roi']:
                        user_data[user_phone]['recommended_option'] = 1
                    elif user_data[user_phone]['max_roi'] == user_data[user_phone]['roi_plus_1']:
                        user_data[user_phone]['recommended_option'] = 2
                    else:
                        user_data[user_phone]['recommended_option'] = 3

                response_text += (
                    f"Our recommendation is Option: {user_data[user_phone]['recommended_option']} \n"
                )


                app.logger.debug(f"Response: {response_text}")
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
    app.run(Debug=true)
