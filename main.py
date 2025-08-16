import os
import uuid
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import gspread
import pandas as pd

# -----------------------------
# การตั้งค่า
# -----------------------------
SHEET_ID = os.getenv("16A5NmlSL40z72czwpqxQXRvnyVc9rsLK")  # ต้องใส่ค่าใน Environment Variables
CREDS_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
APP_PASSWORD = os.getenv("APP_PASSWORD", "default_password_123")

app = FastAPI()

# -----------------------------
# CORS
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Authentication
# -----------------------------
class AuthRequest(BaseModel):
    password: str

active_tokens = set()

@app.post("/login")
def login(auth: AuthRequest):
    if auth.password == APP_PASSWORD:
        token = str(uuid.uuid4())
        active_tokens.add(token)
        return {"token": token}
    else:
        raise HTTPException(status_code=401, detail="Invalid password")

def get_current_user(token: str):
    if token not in active_tokens:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return token

# -----------------------------
# Google Sheets
# -----------------------------
worksheet = None

@app.on_event("startup")
def startup_event():
    global worksheet
    try:
        if not SHEET_ID:
            raise RuntimeError("Missing SHEET_ID env var")

        gc = gspread.service_account(filename=CREDS_FILE)
        spreadsheet = gc.open_by_key(SHEET_ID)
        worksheet = spreadsheet.sheet1
        print("✅ เชื่อมต่อ Google Sheets สำเร็จ!")
    except Exception as e:
        print(f"❌ ไม่สามารถเชื่อมต่อ Google Sheets ได้: {e}")

# -----------------------------
# Models
# -----------------------------
class TaskUpdate(BaseModel):
    file_id: str
    translation: str
    status: str

# -----------------------------
# Routes
# -----------------------------
@app.get("/")
def serve_index():
    return FileResponse("translator_tool.html")

@app.get("/get-task")
def get_task(token: str = Depends(get_current_user)):
    try:
        # อ่านหัวคอลัมน์
        header = worksheet.row_values(1)
        required_cols = ['ชื่อไฟล์','ความยาว(วินาที)','คำแปล','file_id','สถานะ']

        # ถ้ายังไม่มีคอลัมน์ก็เพิ่ม
        for col in required_cols:
            if col not in header:
                header.append(col)
        worksheet.update('A1', [header])

        # โหลดข้อมูลใหม่
        df = pd.DataFrame(worksheet.get_all_records())

        if "สถานะ" not in df.columns:
            raise HTTPException(status_code=500, detail="ไม่พบคอลัมน์ 'สถานะ' ในชีต")

        # เลือกงานที่ยังไม่แปล
        pending = df[df['สถานะ'] == ""]
        if pending.empty:
            return {"task": None}

        row = pending.iloc[0].to_dict()
        return {"task": row}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/update-task")
def update_task(update: TaskUpdate, token: str = Depends(get_current_user)):
    try:
        df = pd.DataFrame(worksheet.get_all_records())

        if "file_id" not in df.columns:
            raise HTTPException(status_code=500, detail="ไม่พบคอลัมน์ file_id ในชีต")

        if update.file_id not in df['file_id'].astype(str).values:
            raise HTTPException(status_code=404, detail="ไม่พบไฟล์ในชีต")

        row_index = df.index[df['file_id'].astype(str) == update.file_id][0] + 2
        worksheet.update_cell(row_index, df.columns.get_loc("คำแปล") + 1, update.translation)
        worksheet.update_cell(row_index, df.columns.get_loc("สถานะ") + 1, update.status)

        return {"success": True}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------
# Static files (กันพังถ้าไม่มีโฟลเดอร์)
# -----------------------------
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
else:
    print("⚠️ ไม่มีโฟลเดอร์ static — ข้ามการ mount")
