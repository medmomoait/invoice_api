import os
import uuid
import json
from flask import Flask, request, send_file, jsonify, render_template, redirect, url_for
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from dotenv import load_dotenv
import stripe
from datetime import datetime
from flask import render_template
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText


# Load environment variables
load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

app = Flask(__name__)

PDF_FOLDER = 'invoices'
KEY_FILE = 'keys.json'
USAGE_FILE = 'usage.json'
os.makedirs(PDF_FOLDER, exist_ok=True)

# Initialize keys.json
if not os.path.exists(KEY_FILE):
    with open(KEY_FILE, 'w') as f:
        json.dump([], f)

# Initialize usage.json
if not os.path.exists(USAGE_FILE):
    with open(USAGE_FILE, 'w') as f:
        json.dump({}, f)

def generate_api_key():
    return str(uuid.uuid4())

def save_api_key(new_key):
    with open(KEY_FILE, 'r') as f:
        keys = json.load(f)
    keys.append(new_key)
    with open(KEY_FILE, 'w') as f:
        json.dump(keys, f)

def is_valid_key(key):
    with open(KEY_FILE, 'r') as f:
        keys = json.load(f)
    return key in keys

def increment_usage(key):
    today = datetime.now().strftime('%Y-%m-%d')
    with open(USAGE_FILE, 'r') as f:
        usage = json.load(f)

    if key not in usage or usage[key].get('date') != today:
        usage[key] = {'date': today, 'count': 1}
    else:
        usage[key]['count'] += 1

    with open(USAGE_FILE, 'w') as f:
        json.dump(usage, f)

    return usage[key]['count']

# ------------------------
# Root Route
# ------------------------
@app.route('/')
def home():
    return render_template("index.html")

# ------------------------
# Health Check Route
# ------------------------
@app.route('/health')
def health():
    return "✅ API is running!"

# ------------------------
# Generate Invoice (Protected)
# ------------------------

@app.route('/generate-invoice', methods=['POST'])
def generate_invoice():
    api_key = request.headers.get('x-api-key')
    if not api_key or not is_valid_key(api_key):
        return jsonify({'error': 'Unauthorized. Missing or invalid API key.'}), 401

    count = increment_usage(api_key)
    if count > 10:
        return jsonify({'error': 'Daily limit reached (10 invoices per day).'}), 429

    data = request.json
    invoice_id = str(uuid.uuid4())
    filename = os.path.join(PDF_FOLDER, f"{invoice_id}.pdf")

    c = canvas.Canvas(filename, pagesize=A4)
    c.drawString(100, 800, f"Invoice #: {data['invoice_number']}")
    c.drawString(100, 780, f"Client: {data['client_name']}")
    c.drawString(100, 760, f"Email: {data['client_email']}")
    c.drawString(100, 740, f"Due Date: {data['due_date']}")

    y = 700
    total = 0
    for item in data['items']:
        line = f"{item['description']} - {item['quantity']} x ${item['unit_price']}"
        c.drawString(100, y, line)
        total += item['quantity'] * item['unit_price']
        y -= 20

    c.drawString(100, y - 20, f"Total: ${total}")
    c.save()

# ------------------------
# Demo Invoice (No API Key Needed)
# ------------------------
@app.route('/demo-invoice', methods=['POST'])
def demo_invoice():
    data = request.json
    invoice_id = str(uuid.uuid4())
    filename = os.path.join(PDF_FOLDER, f"demo_{invoice_id}.pdf")

    c = canvas.Canvas(filename, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(100, 800, f"DEMO Invoice #: {data['invoice_number']}")
    c.setFont("Helvetica", 12)
    c.drawString(100, 780, f"Client: {data['client_name']}")
    c.drawString(100, 760, f"Email: {data['client_email']}")
    c.drawString(100, 740, f"Due Date: {data['due_date']}")

    y = 700
    total = 0
    for item in data['items']:
        line = f"{item['description']} - {item['quantity']} x ${item['unit_price']}"
        c.drawString(100, y, line)
        total += item['quantity'] * item['unit_price']
        y -= 20

    c.setFont("Helvetica-Bold", 12)
    c.drawString(100, y - 20, f"Total: ${total}")
    c.setFillColorRGB(1, 0, 0)  # red
    c.setFont("Helvetica-Bold", 50)
    c.drawString(150, 400, "DEMO")
    c.save()

    return jsonify({
        'invoice_id': invoice_id,
        'pdf_url': f"/invoice/demo_{invoice_id}"
    })


# ------------------------
# Download Invoice
# ------------------------
@app.route('/invoice/<invoice_id>', methods=['GET'])
def get_invoice(invoice_id):
    filepath = os.path.join(PDF_FOLDER, f"{invoice_id}.pdf")
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return jsonify({'error': 'Invoice not found'}), 404

# ------------------------
# Stripe Checkout
# ------------------------
@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        # Generate a simple API key (you can use your own logic)
        import secrets
        generated_api_key = secrets.token_hex(16)

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            mode='payment',
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Invoice API Access',
                        'images': ['https://invoice-api-ztqg.onrender.com/static/favicon.png']
                    },
                    'unit_amount': 100  # $1.00
                },
                'quantity': 1
            }],
            metadata={
                'api_key': generated_api_key
            },
            success_url="https://invoice-api-ztqg.onrender.com/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url='https://invoice-api-ztqg.onrender.com/cancel'
        )

        return jsonify({'checkout_url': session.url})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/pay')
def pay():
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        mode='payment',
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {
                    'name': 'Invoice API Access',
                    'images': ['https://invoice-api-ztqg.onrender.com/static/favicon.png']
                },
                'unit_amount': 100  # $1.00
            },
            'quantity': 1
        }],
        success_url='https://invoice-api-ztqg.onrender.com/success?session_id={CHECKOUT_SESSION_ID}',
        cancel_url='https://invoice-api-ztqg.onrender.com/cancel'
    )
    return redirect(session.url, code=303)
    
# ------------------------
# Payment Success Page
# ------------------------
@app.route('/success')
def success():
    session_id = request.args.get("session_id")

    if not session_id:
        return "❌ No session ID provided.", 400

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        metadata = session.get("metadata", {})
        api_key = metadata.get("api_key", "Not found")

        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Payment Successful</title>
            <link rel="icon" href="{url_for('static', filename='favicon.png')}" type="image/png" />
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    text-align: center;
                    padding: 4rem;
                    background-color: #f4f4f4;
                }}
                h1 {{
                    color: #28a745;
                }}
                p {{
                    font-size: 1.2rem;
                    color: #333;
                }}
                .api-key {{
                    background: #e9ecef;
                    padding: 0.5rem 1rem;
                    border-radius: 5px;
                    display: inline-block;
                    font-family: monospace;
                    margin-top: 1rem;
                }}
                a {{
                    display: inline-block;
                    margin-top: 2rem;
                    text-decoration: none;
                    background-color: #007bff;
                    color: white;
                    padding: 0.75rem 1.5rem;
                    border-radius: 5px;
                }}
            </style>
        </head>
        <body>
            <h1>✅ Payment successful!</h1>
            <p>Your API key is:</p>
            <div class="api-key">{api_key}</div>
            <br>
            <a href="{url_for('home')}">Go Back to Home</a>
        </body>
        </html>
        """
    except Exception as e:
        return f"❌ Error retrieving session: {str(e)}", 500

# ------------------------
# Payment Cancelled
# ------------------------
@app.route('/cancel')
def cancel():
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Payment Cancelled</title>
        <link rel="icon" href="{url_for('static', filename='favicon.png')}" type="image/png" />
    </head>
    <body>
        <h1>❌ Payment cancelled</h1>
        <p>You can try again anytime.</p>
        <a href="{url_for('home')}">Go Back to Home</a>
    </body>
    </html>
    """


# ------------------------
# API Documentation Route
# ------------------------
@app.route('/docs')
def docs():
    return render_template("docs.html")

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = os.getenv('STRIPE_WEBHOOK_SECRET')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        return '⚠️ Invalid payload', 400
    except stripe.error.SignatureVerificationError:
        return '⚠️ Invalid signature', 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        customer_email = session.get('customer_email')

        if customer_email:
            # Generate and email the API key securely
            api_key = generate_api_key()  # Your function
            save_api_key(customer_email, api_key)  # Store it (e.g. in a file or database)
            send_api_key_email(customer_email, api_key)  # Send via email
            print(f"✅ Sent API key to {customer_email}")

    return '', 200

# ------------------------
# Run the App
# ------------------------
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
