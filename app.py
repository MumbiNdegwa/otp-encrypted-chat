from flask import Flask, request, jsonify
from flask_cors import CORS
import africastalking
import os
from datetime import datetime, timedelta
import logging
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all domains

# Africa's Talking Configuration
# Replace these with your actual credentials from Africa's Talking dashboard
AFRICASTALKING_USERNAME = "sandbox"  # Usually "sandbox" for testing
AFRICASTALKING_API_KEY = "atsk_920bb673ac40bede9084f617b9945ae2636d227f67332485931dbc9134b172a9f698c17a"    # Your API key from dashboard

# Initialize Africa's Talking
try:
    africastalking.initialize(AFRICASTALKING_USERNAME, AFRICASTALKING_API_KEY)
    sms = africastalking.SMS
    logger.info("Africa's Talking SMS service initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Africa's Talking: {e}")
    sms = None

# Store OTP temporarily (in production, use Redis or database)
otp_store = {}

class OTPManager:
    @staticmethod
    def store_otp(phone_number, otp):
        """Store OTP with expiration time"""
        expiry_time = datetime.now() + timedelta(minutes=10)  # 10 minutes expiry
        otp_store[phone_number] = {
            'otp': otp,
            'expiry': expiry_time,
            'attempts': 0
        }
        logger.info(f"OTP stored for {phone_number}")
    
    @staticmethod
    def verify_otp(phone_number, otp):
        """Verify OTP and handle attempts"""
        if phone_number not in otp_store:
            return False, "OTP not found or expired"
        
        stored_data = otp_store[phone_number]
        
        # Check expiry
        if datetime.now() > stored_data['expiry']:
            del otp_store[phone_number]
            return False, "OTP has expired"
        
        # Check attempts
        if stored_data['attempts'] >= 3:
            del otp_store[phone_number]
            return False, "Too many incorrect attempts"
        
        # Verify OTP
        if stored_data['otp'] == otp:
            del otp_store[phone_number]
            return True, "OTP verified successfully"
        else:
            stored_data['attempts'] += 1
            return False, f"Incorrect OTP. {3 - stored_data['attempts']} attempts remaining"

def format_phone_number(phone):
    """Format phone number to international format"""
    # Remove any non-digit characters
    phone = ''.join(filter(str.isdigit, phone))
    
    # Handle different formats
    if phone.startswith('254'):
        return f"+{phone}"
    elif phone.startswith('0'):
        return f"+254{phone[1:]}"
    elif len(phone) == 9:
        return f"+254{phone}"
    else:
        return f"+254{phone}"

@app.route('/')
def home():
    """Health check endpoint"""
    return jsonify({
        "status": "success",
        "message": "Secure Communication API is running",
        "timestamp": datetime.now().isoformat(),
        "sms_service": "available" if sms else "unavailable"
    })

@app.route('/send-otp', methods=['POST'])
def send_otp():
    """Send OTP via SMS"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                "status": "error",
                "message": "No data provided"
            }), 400
        
        phone_number = data.get('phone_number')
        otp = data.get('otp')
        
        if not phone_number or not otp:
            return jsonify({
                "status": "error",
                "message": "Phone number and OTP are required"
            }), 400
        
        # Format phone number
        formatted_phone = format_phone_number(phone_number)
        logger.info(f"Sending OTP to {formatted_phone}")
        
        # Create SMS message
        message = f"Your secure communication OTP is: {otp}\nThis code will expire in 10 minutes.\nDo not share this code with anyone."
        
        # Send SMS via Africa's Talking
        if sms:
            try:
                response = sms.send(message, [formatted_phone])
                logger.info(f"SMS API Response: {response}")
                
                # Check if SMS was sent successfully
                if response['SMSMessageData']['Recipients']:
                    recipient = response['SMSMessageData']['Recipients'][0]
                    if recipient['status'] == 'Success':
                        # Store OTP for verification
                        OTPManager.store_otp(formatted_phone, otp)
                        
                        return jsonify({
                            "status": "success",
                            "message": f"OTP sent successfully to {formatted_phone}",
                            "messageId": recipient.get('messageId'),
                            "cost": recipient.get('cost')
                        })
                    else:
                        return jsonify({
                            "status": "error",
                            "message": f"Failed to send SMS: {recipient.get('status')}"
                        }), 500
                else:
                    return jsonify({
                        "status": "error",
                        "message": "No recipients found in response"
                    }), 500
                    
            except Exception as e:
                logger.error(f"SMS sending error: {e}")
                return jsonify({
                    "status": "error",
                    "message": f"SMS service error: {str(e)}"
                }), 500
        else:
            # SMS service not available - for testing purposes
            OTPManager.store_otp(formatted_phone, otp)
            logger.warning("SMS service not initialized - OTP stored for testing")
            return jsonify({
                "status": "success",
                "message": f"OTP would be sent to {formatted_phone} (SMS service not configured)",
                "otp_for_testing": otp  # Remove this in production
            })
            
    except Exception as e:
        logger.error(f"Unexpected error in send_otp: {e}")
        return jsonify({
            "status": "error",
            "message": "Internal server error"
        }), 500

@app.route('/verify-otp', methods=['POST'])
def verify_otp():
    """Verify OTP (optional endpoint for additional security)"""
    try:
        data = request.get_json()
        
        phone_number = data.get('phone_number')
        otp = data.get('otp')
        
        if not phone_number or not otp:
            return jsonify({
                "status": "error",
                "message": "Phone number and OTP are required"
            }), 400
        
        formatted_phone = format_phone_number(phone_number)
        is_valid, message = OTPManager.verify_otp(formatted_phone, otp)
        
        return jsonify({
            "status": "success" if is_valid else "error",
            "message": message,
            "valid": is_valid
        })
        
    except Exception as e:
        logger.error(f"Error in verify_otp: {e}")
        return jsonify({
            "status": "error",
            "message": "Internal server error"
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Detailed health check"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "sms": "available" if sms else "unavailable",
            "api": "running"
        },
        "active_otps": len(otp_store)
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "status": "error",
        "message": "Endpoint not found"
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "status": "error",
        "message": "Internal server error"
    }), 500

if __name__ == '__main__':
    # Load environment variables
    AFRICASTALKING_USERNAME = os.getenv('AFRICASTALKING_USERNAME', 'sandbox')
    AFRICASTALKING_API_KEY = os.getenv('AFRICASTALKING_API_KEY', 'your_api_key_here')
    
    print("="*50)
    print("🔐 Secure Communication Backend Server")
    print("="*50)
    print(f"Africa's Talking Username: {AFRICASTALKING_USERNAME}")
    print(f"API Key configured: {'Yes' if AFRICASTALKING_API_KEY != 'your_api_key_here' else 'No'}")
    print(f"SMS Service: {'Available' if sms else 'Not configured'}")
    print("="*50)
    
    # Run the application
    app.run(
        debug=True,
        host='0.0.0.0',
        port=5000
    )