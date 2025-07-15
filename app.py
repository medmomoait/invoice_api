import os
import uuid
import json
from flask import Flask, request, send_file, jsonify
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
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            mode='payment',
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': 'Invoice API Access',
                'images': ['https://invoice-api-ztqg.onrender.com/static/favicon.png']},
                    'unit_amount': 100  # $1.00
                },
                'quantity': 1
            }],
            success_url='https://invoice-api-ztqg.onrender.com/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='https://invoice-api-ztqg.onrender.com/cancel'
        )
        return jsonify({'checkout_url': session.url})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ------------------------
# Payment Success Page
# ------------------------
@app.route('/success')
def success():
    new_key = generate_api_key()
    save_api_key(new_key)
    return f"""
    ✅ Payment successful!<br><br>
    Your API key is:<br><br>
    <b>{new_key}</b><br><br>
    Save this key! You’ll need it to call <code>/generate-invoice</code>.<br>
    Include it in your request header like this:<br>
    <code>x-api-key: {new_key}</code>
    """

# ------------------------
# Payment Cancelled
# ------------------------
@app.route('/cancel')
def cancel():
    return "❌ Payment was cancelled."

# ------------------------
# API Documentation Route
# ------------------------
@app.route('/docs')
def docs():
    return render_template("docs.html")


@app.route('/dashboard')
def dashboard():
    return """
    <!DOCTYPE html>
    <html>
    <head>
      <title>Dashboard</title>
      <style>
        body { font-family: Arial, sans-serif; background: #f8f9fa; padding: 2rem; }
        h1 { color: #0d6efd; display: inline-block; margin-right: 1rem; }
        label { display: block; margin: 1rem 0 0.5rem; }
        input, textarea { width: 100%; padding: 0.5rem; margin-bottom: 1rem; border: 1px solid #ccc; border-radius: 4px; }
        button { padding: 0.75rem 1.5rem; background: #0d6efd; color: white; border: none; border-radius: 4px; }
        .note { font-size: 0.9rem; color: #555; margin-top: 2rem; }
        .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 2rem; }
        .logo { height: 40px; }
        .docs-link { text-decoration: none; color: #0d6efd; font-weight: bold; font-size: 1rem; }
      </style>
    </head>
    <body>
      <div class="header">
        <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/3/3f/Invoice_icon.svg/120px-Invoice_icon.svg.png" alt="Logo" class="logo">
        <a href="/docs" class="docs-link">📄 Documentation</a>
      </div>

      <h1>🧾 Invoice API Dashboard</h1>
      <p>Use the form below to test your invoice generation.</p>

      <form id="invoiceForm">
        <label>API Key:</label>
        <input type="text" id="apiKey" placeholder="Enter your API key here" required />

        <label>Invoice JSON:</label>
        <textarea id="jsonBody" rows="12" placeholder='{
  "invoice_number": "INV-001",
  "client_name": "John Doe",
  "client_email": "john@example.com",
  "due_date": "2025-07-31",
  "items": [
    { "description": "Design", "quantity": 1, "unit_price": 100 },
    { "description": "Hosting", "quantity": 1, "unit_price": 50 }
  ]
}'></textarea>

        <button type="submit">Generate Invoice</button>
      </form>

      <div class="note" id="responseNote"></div>

      <script>
        const form = document.getElementById('invoiceForm');
        form.addEventListener('submit', async (e) => {
          e.preventDefault();
          const key = document.getElementById('apiKey').value;
          const body = document.getElementById('jsonBody').value;

          const res = await fetch('/generate-invoice', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'x-api-key': key
            },
            body: body
          });

          const data = await res.json();
          const note = document.getElementById('responseNote');
          if (res.ok) {
            note.innerHTML = `<p>✅ Invoice generated! <a href="${data.pdf_url}" target="_blank">Download PDF</a></p>`;
          } else {
            note.innerHTML = `<p style="color: red;">❌ ${data.error}</p>`;
          }
        });
      </script>
    </body>
    </html>
    """




# ------------------------
# Run the App
# ------------------------
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
