import os
import re
import json
import requests
import gspread
from google.oauth2.service_account import Credentials

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

def send_telegram_msg(chat_id, message, show_buttons=True):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    if show_buttons:
        reply_markup = {
            "keyboard": [
                [{"text": "📋 আমার মিটারসমূহ"}],
                [{"text": "ℹ️ সাহায্য / নির্দেশিকা"}]
            ],
            "resize_keyboard": True,
            "one_time_keyboard": False
        }
        payload["reply_markup"] = json.dumps(reply_markup)

    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Telegram Send Error:", e)

def fetch_meter_data(meter_no):
    api_url = f"https://api.brebprepaidportal.com/breb-customer/cust/basicElecConsumInfo?meterNo={meter_no}"
    try:
        res = requests.get(api_url, timeout=15)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"Error fetching meter {meter_no}:", e)
    return None

def process_telegram_updates():
    try:
        gc = get_gspread_client()
        sheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
    except Exception as e:
        print("Google Sheet Connection Error:", e)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        res = requests.get(url, timeout=10).json()
    except Exception as e:
        print("Telegram GetUpdates Error:", e)
        return

    if not res.get('ok'):
        return

    records = sheet.get_all_records()

    for update in res.get('result', []):
        if 'message' in update and 'text' in update['message']:
            chat_id = str(update['message']['chat']['id'])
            text = update['message']['text'].strip()

            numbers_in_text = re.findall(r'\d{8,15}', text)

            if text in ["📋 আমার মিটারসমূহ", "লিস্ট", "মিটার", "/list"]:
                user_meters = [str(r['meter_no']) for r in records if str(r['chat_id']) == chat_id]
                if user_meters:
                    msg = "📋 *আপনার যুক্ত করা মিটারসমূহ:*\n\n"
                    for idx, m in enumerate(user_meters, 1):
                        msg += f"{idx}. `{m}`\n"
                    msg += "\n💡 *মিটার ডিলিট করতে লিখুন:* `রিমুভ [মিটার নং]`"
                    send_telegram_msg(chat_id, msg)
                else:
                    send_telegram_msg(chat_id, "ℹ️ আপনার কোনো মিটার নম্বর যুক্ত করা নেই।\n\nমিটার যোগ করতে শুধু মিটার নম্বরটি লিখে পাঠান।")

            elif text in ["ℹ️ সাহায্য / নির্দেশিকা", "/help"]:
                help_text = (
                    "💡 *কীভাবে ব্যবহার করবেন?*\n\n"
                    "১. *মিটার যোগ করতে:* শুধু মিটার নম্বরটি লিখে পাঠান (যেমন: `12345678901`)\n"
                    "২. *মিটার দেখতে:* '📋 আমার মিটারসমূহ' বাটনে ক্লিক করুন।\n"
                    "৩. *মিটার মুছতে:* লিখুন `রিমুভ 12345678901`"
                )
                send_telegram_msg(chat_id, help_text)

            elif ("রিমুভ" in text.lower() or "delete" in text.lower() or "/remove" in text.lower()) and numbers_in_text:
                meter_no = numbers_in_text[0]
                cell = sheet.find(meter_no)
                if cell:
                    if str(sheet.cell(cell.row, 1).value) == chat_id:
                        sheet.delete_rows(cell.row)
                        send_telegram_msg(chat_id, f"🗑️ *মিটার নং `{meter_no}` রিমুভ করা হয়েছে।*")
                    else:
                        send_telegram_msg(chat_id, "⚠️ এই মিটারটি অপসারণ করার অনুমতি নেই।")
                else:
                    send_telegram_msg(chat_id, f"⚠️ মিটার নং `{meter_no}` তালিকায় পাওয়া যায়নি।")

            elif numbers_in_text and not text.startswith('/'):
                meter_no = numbers_in_text[0]
                exists = any(str(r['chat_id']) == chat_id and str(r['meter_no']) == meter_no for r in records)
                if not exists:
                    sheet.append_row([chat_id, meter_no])
                    send_telegram_msg(chat_id, f"✅ *মিটার নং `{meter_no}` সফলভাবে যুক্ত করা হয়েছে!*")
                else:
                    send_telegram_msg(chat_id, f"⚠️ এই মিটার নম্বরটি (`{meter_no}`) ইতিমধ্যেই আপনার তালিকায় রয়েছে।")

            elif text == "/start":
                welcome_msg = "👋 *পল্লী বিদ্যুৎ হেল্পারে স্বাগতম!*\n\nআপনার মিটার নম্বরটি লিখে পাঠান (যেমন: `12345678901`)।"
                send_telegram_msg(chat_id, welcome_msg)

def send_daily_reports():
    try:
        gc = get_gspread_client()
        sheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
        records = sheet.get_all_records()
    except Exception as e:
        print("Google Sheet Read Error:", e)
        return

    if not records:
        return

    user_data = {}
    for row in records:
        cid = str(row['chat_id'])
        m_no = str(row['meter_no'])
        if cid not in user_data:
            user_data[cid] = []
        user_data[cid].append(m_no)

    for chat_id, meters in user_data.items():
        msg = "⚡ *পল্লী বিদ্যুৎ ডেইলি অ্যালার্ট*\n───────────────────\n"
        for meter_no in meters:
            data = fetch_meter_data(meter_no)
            if data:
                balance = float(data.get('remBalance', 0))
                used = data.get('usedThisMonth', 'N/A')
                r_time = data.get('readingTime', 'N/A')

                msg += f"\n📍 *মিটার:* `{meter_no}`\n"
                msg += f"💰 *অবশিষ্ট ব্যালেন্স:* *{balance} টাকা*\n"
                msg += f"📊 *এই মাসে ব্যবহার:* {used} kWh\n"
                msg += f"🕒 *রিডিং সময়:* {r_time}\n"

                if balance < 200:
                    msg += "⚠️ *জরুরি সতর্কতা: ব্যালেন্স ২০০ টাকার নিচে! রিচার্জ করুন।*\n"
                msg += "───────────────────\n"

        send_telegram_msg(chat_id, msg)

if __name__ == "__main__":
    process_telegram_updates()
    send_daily_reports()
