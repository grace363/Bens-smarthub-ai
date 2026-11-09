
import os
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# API configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
META_APP_SECRET = os.getenv("META_APP_SECRET")

MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna")
GRAPH_VERSION = os.getenv("GRAPH_API_VERSION", "v26.0")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Temporary conversation memory for each customer
customer_chats = {}

BUSINESS_INSTRUCTIONS = """
You are Bens SmartHub AI, a friendly WhatsApp business assistant.

Your responsibilities:
- Welcome customers politely.
- Answer questions about products.
- Help customers place enquiries and orders.
- Be professional, friendly and concise.
- Use the language the customer uses.
- The business may sell eggs and other products.

Important rules:
- Never invent prices, stock availability or delivery charges.
- If you do not know something, tell the customer
  that the business owner will confirm.
- Never claim an order has been confirmed unless
  the owner has actually confirmed it.
- Keep replies suitable for WhatsApp.
"""

def get_ai_reply(phone, message):

    if not client:
        return "Sorry, our AI assistant is temporarily unavailable."

    history = customer_chats.get(phone, [])

    history.append({
        "role": "user",
        "content": message
    })

    try:
        response = client.responses.create(
            model=MODEL,
            instructions=BUSINESS_INSTRUCTIONS,
            input=history[-12:],
            max_output_tokens=300
        )

        answer = response.output_text.strip()

        if not answer:
            answer = "Sorry, I couldn't process that. Please try again."

        history.append({
            "role": "assistant",
            "content": answer
        })

        customer_chats[phone] = history[-12:]

        return answer[:4000]

    except Exception as error:
        print("AI error:", str(error))
        return "Sorry, I'm having trouble replying right now. Please try again shortly."


def send_whatsapp_message(phone, message):

    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("WhatsApp credentials are missing.")
        return False

    url = (
        f"https://graph.facebook.com/"
        f"{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {
            "body": message
        }
    }

    try:
        result = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=20
        )

        print("WhatsApp response:", result.status_code)
        print("WhatsApp result:", result.text)

        return result.ok

    except requests.RequestException as error:
        print("WhatsApp sending error:", str(error))
        return False


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "application": "Bens SmartHub AI",
        "status": "running"
    })


@app.route("/webhook", methods=["GET"])
def verify_webhook():

    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200

    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def receive_message():

    raw_body = request.get_data()

    # Verify Meta webhook signature when app secret is configured
    if META_APP_SECRET:
        signature = request.headers.get(
            "X-Hub-Signature-256", ""
        )

        expected = "sha256=" + hmac.new(
            META_APP_SECRET.encode(),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            return "Invalid signature", 403

    data = request.get_json(silent=True) or {}

    try:
        entries = data.get("entry", [])

        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})

                for item in value.get("messages", []):

                    # Only process incoming text messages
                    if item.get("type") != "text":
                        continue

                    phone = item.get("from")
                    message = item.get("text", {}).get("body", "")

                    if not phone or not message:
                        continue

                    reply = get_ai_reply(phone, message)

                    send_whatsapp_message(phone, reply)

    except Exception as error:
        print("Webhook processing error:", str(error))

    return jsonify({"status": "received"}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
