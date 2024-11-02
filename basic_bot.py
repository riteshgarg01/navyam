#!/usr/bin/env python
# coding: utf-8

# In[1]:


from flask import Flask, request, jsonify
import requests
import logging

app = Flask(__name__)

# Root route to test the server
@app.route('/')
def hello():
    return "Flask server is running!"

logging.basicConfig(level=logging.DEBUG)

@app.route('/webhook', methods=['POST'])
def whatsapp_bot():
    try:
        incoming_data = request.json
        app.logger.debug(f"Received data: {incoming_data}")

        # #rocess the incoming data for testing purpose
        # if incoming_data:
        #     return jsonify({"status": "success"}), 200
        # else:
        #     return jsonify({"status": "error"}), 400
        
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
            if user_event_type in ['opted-in', 'opted-out']:
                app.logger.debug(f"User event of type {user_event_type}")
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
            #return jsonify({"status": "billing-event received"}), 200
            message = payload.get('payload', {}).get('text', '').lower()
            # sender = payload.get('sender',{}).get('phone', None)

            # Response logic
            if 'hello' in message:
                response_text = "Ki haal chaal twadde"
            elif 'bye' in message:
                response_text = "kal milaanga main"
            else:
                response_text = "time to move to chatGPT from Google"
            
            app.logger.debug(f"Response: {response_text}")

            send_message(response_text, payload['sender']['phone'])
            return jsonify({"status": "success", "response": response_text}), 200

        return jsonify({"status": "unknown event type"}), 400

    except Exception as e:
        app.logger.error(f"Error occurred: {e}")
        return jsonify({"status": "error", "message": str(e)}),500


# def send_message(message, to_number):
#     GUPSHUP_URL = 'https://api.gupshup.io/sm/api/v1/msg'
#     GUPSHUP_API_KEY = '2dvow1vgfzmtyyoekitrmeu0vtco0m4a'  # Add your Gupshup API key here
#     headers = {
#         'Content-Type': 'application/x-www-form-urlencoded',
#         'apikey': GUPSHUP_API_KEY
#     }
#     payload = {
#         'channel': 'whatsapp',
#         'source': '917834811114',  # Add your Gupshup Sandbox WhatsApp number here
#         'destination': to_number,
#         'message': message
#     }
#     response = requests.post(GUPSHUP_URL, headers=headers, data=payload)
#     print(f"Message sent: {response.status_code}, {response.text}")

def send_message(message, to_number):
    GUPSHUP_URL = 'https://api.gupshup.io/wa/api/v1/msg'
    GUPSHUP_API_KEY = '2dvow1vgfzmtyyoekitrmeu0vtco0m4a'  # Replace with your actual API key
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'apikey': GUPSHUP_API_KEY
    }
    
    # Payload format based on the cURL request
    payload = {
        'source': '917834811114',  # Replace with your WhatsApp sandbox number
        'destination': to_number,  # The recipient's phone number
        'message': '{"type":"text", "text": "' + message + '"}',
        'src.name': 'QuoteGenerator'  # Replace with your app name or bot name
    }

    # Sending the POST request to Gupshup API
    response = requests.post(GUPSHUP_URL, headers=headers, data=payload)
    
    # Debugging information to check the response
    print(f"Message sent: {response.status_code}, {response.text}")
    
    return response.status_code, response.text

if __name__ == '__main__':
    app.run(debug=True)
