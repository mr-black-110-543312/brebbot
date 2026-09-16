import os
import re
import json
import requests
import gspread
from flask import Flask, request
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# Environment variables
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
GOOGLE_SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')
GCP_SERVICE_ACCOUNT_ENV = os.environ.get('GCP_SERVICE_ACCOUNT')

def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if GCP_SERVICE_ACCOUNT_ENV:
        service_account_info = json.loads(GCP_SERVICE_ACCOUNT_ENV)
        credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    else:
        credentials = Credentials.from_service_account_file("service_account.json", scopes=scopes)
    return gspread.authorize(credentials)

def send_telegram_msg(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": {
            "keyboard": [
                [{"text": "📋 আমার মিটারসমূহ"}],
                [{"text": "ℹ️ সাহায্য / নির্দেশিকা"}]
            ],
            "resize_keyboard": True
        }
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Telegram Send Error:", e)

def fetch_meter_data(meter_no):
    api_url = f"https://api.brebprepaidportal.com/breb-customer/cust/basicElecConsumInfo?meterNo={meter_no}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(api_url, headers=headers, timeout=15)
        if res.status_code == 200:
            return res.json().get('data', {})
    except Exception as e:
        print(f"Error fetching meter {meter_no}:", e)
    return None

def format_meter_report(meter_no, data):
    if not data:
        return f"⚠️ *মিটার নং `{meter_no}`-এর কোনো ডাটা পাওয়া যায়নি।*"
    
    balance = float(data.get('remainingBalance', 0))
    used_unit = data.get('usedThisMonthUnit', 'N/A')
    used_taka = data.get('usedThisMonthTaka', 'N/A')
    r_time = data.get('readingTime', 'N/A')
    last_recharge = data.get('lastRecharge', 'N/A')

    msg = f"⚡ *মিটার তথ্য:* `{meter_no}`\n───────────────────\n"
    msg += f"💰 *অবশিষ্ট ব্যালেন্স:* *{balance} টাকা*\n"
    msg += f"📊 *এই মাসে ব্যবহার:* {used_unit} kWh ({used_taka} টাকা)\n"
    msg += f"💳 *শেষ রিচার্জ:* {last_recharge} টাকা\n"
    msg += f"🕒 *রিডিং সময়:* {r_time}\n"
    if balance < 200:
        msg += "\n⚠️ *জরুরি সতর্কতা: ব্যালেন্স ২০০ টাকার নিচে! রিচার্জ করুন।*"
    return msg

@app.route('/', methods=['POST', 'GET'])
def webhook():
    if request.method == 'POST':
        update = request.get_json()
        if 'message' in update and 'text' in update['message']:
            chat_id = str(update['message']['chat']['id'])
            text = update['message']['text'].strip()

            numbers_in_text = re.findall(r'\d{8,15}', text)
            
            gc = get_gspread_client()
            sheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
            records = sheet.get_all_records()

            if text in ["📋 আমার মিটারসমূহ", "লিস্ট", "মিটার", "/list"]:
                user_meters = [str(r['meter_no']) for r in records if str(r['chat_id']) == chat_id]
                if user_meters:
                    send_telegram_msg(chat_id, "⏳ আপনার মিটারগুলোর লাইভ ডাটা আনা হচ্ছে...")
                    for m in user_meters:
                        d = fetch_meter_data(m)
                        send_telegram_msg(chat_id, format_meter_report(m, d))
                else:
                    send_telegram_msg(chat_id, "ℹ️ আপনার কোনো মিটার যুক্ত করা নেই। মিটার নম্বরটি সরাসরি লিখে পাঠান।")

            elif text in ["ℹ️ সাহায্য / নির্দেশিকা", "/help", "/start"]:
                send_telegram_msg(chat_id, "👋 *পল্লী বিদ্যুৎ হেল্পারে স্বাগতম!*\n\n১. মিটার যোগ করতে সরাসরি মিটার নম্বর লিখে পাঠান।\n২. '📋 আমার মিটারসমূহ' এ ক্লিক করলে তাৎক্ষণিক ব্যালেন্স দেখাবে।")

            elif numbers_in_text and not text.startswith('/'):
                meter_no = numbers_in_text[0]
                exists = any(str(r['chat_id']) == chat_id and str(r['meter_no']) == meter_no for r in records)
                if not exists:
                    sheet.append_row([chat_id, meter_no])
                    send_telegram_msg(chat_id, f"✅ *মিটার নং `{meter_no}` সফলভাবে যুক্ত করা হয়েছে!*\n\nডাটা নিচে দেওয়া হলো:")
                
                d = fetch_meter_data(meter_no)
                send_telegram_msg(chat_id, format_meter_report(meter_no, d))

        return "OK", 200
    return "Server is running!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
