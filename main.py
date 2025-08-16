import os
import uuid
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import gspread
import pandas as pd
import logging

# ตั้งค่า Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------
# การตั้งค่า
# -----------------------------
SHEET_ID = "16A5NmlSL40z72czwpqxQXRvnyVc9rsLK"
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
        if not os.path.exists(CREDS_FILE):
            logger.error(f"❌ ไม่พบไฟล์ Credentials: {CREDS_FILE}")
            raise RuntimeError(f"Missing credentials file: {CREDS_FILE}")

        gc = gspread.service_account(filename=CREDS_FILE)
        spreadsheet = gc.open_by_key(SHEET_ID)
        worksheet = spreadsheet.sheet1
        logger.info("✅ เชื่อมต่อ Google Sheets สำเร็จ!")
    except Exception as e:
        logger.error(f"❌ ไม่สามารถเชื่อมต่อ Google Sheets ได้: {e}")
        # Raise exception to prevent server from starting with a broken connection
        raise RuntimeError("Failed to connect to Google Sheets") from e

# -----------------------------
# Models
# -----------------------------
class SaveRequest(BaseModel):
    filename: str
    translation: str
    interpreter_name: str

# -----------------------------
# Routes
# -----------------------------
@app.get("/")
def serve_index():
    return FileResponse("translator_tool.html")

@app.get("/health")
def health_check():
    """Endpoint สำหรับตรวจสอบสถานะของแอปพลิเคชัน"""
    return {"status": "ok"}

@app.get("/get-task")
def get_task(interpreter_name: str, token: str = Depends(get_current_user)):
    try:
        # Check for worksheet connection before proceeding
        if worksheet is None:
            raise HTTPException(status_code=503, detail="Service Unavailable: Not connected to Google Sheet")

        header = worksheet.row_values(1)
        required_cols = ['ชื่อไฟล์', 'file_id', 'ความยาว(วินาที)', 'คำแปล', 'สถานะ', 'ผู้แปล']

        if not all(col in header for col in required_cols):
            new_header = [col for col in required_cols if col not in header]
            if new_header:
                worksheet.update('A1', [header + new_header])
            header = worksheet.row_values(1)

        df = pd.DataFrame(worksheet.get_all_records())

        if df.empty:
            return {"message": "ไม่มีไฟล์สำหรับแปลในชีต"}

        pending = df[df['สถานะ'] == ""]
        if pending.empty:
            return {"message": "ไม่มีไฟล์ที่ต้องแปลเหลือแล้ว"}

        task_row = pending.iloc[0]
        current_index = df.index[df['สถานะ'] == ""].tolist()[0]
        total_files = len(df)
        
        task = {
            "file_id": task_row.get("file_id"),
            "filename": task_row.get("ชื่อไฟล์"),
            "duration": task_row.get("ความยาว(วินาที)"),
            "current_index": current_index,
            "total_files": total_files
        }

        return JSONResponse(content=task)

    except Exception as e:
        logger.error(f"Error fetching task: {e}")
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาดในการโหลดงาน: {e}")

@app.post("/save-task")
def save_task(save_req: SaveRequest, token: str = Depends(get_current_user)):
    try:
        # Check for worksheet connection before proceeding
        if worksheet is None:
            raise HTTPException(status_code=503, detail="Service Unavailable: Not connected to Google Sheet")
            
        df = pd.DataFrame(worksheet.get_all_records())
        
        if save_req.filename not in df['ชื่อไฟล์'].values:
            raise HTTPException(status_code=404, detail="ไม่พบชื่อไฟล์ในชีต")

        row_index = df.index[df['ชื่อไฟล์'] == save_req.filename][0] + 2

        worksheet.update_cell(row_index, df.columns.get_loc("คำแปล") + 1, save_req.translation)
        worksheet.update_cell(row_index, df.columns.get_loc("สถานะ") + 1, "แปลแล้ว")
        worksheet.update_cell(row_index, df.columns.get_loc("ผู้แปล") + 1, save_req.interpreter_name)

        return {"success": True, "message": "บันทึกข้อมูลเรียบร้อย"}

    except Exception as e:
        logger.error(f"Error saving task: {e}")
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาดในการบันทึก: {e}")

# -----------------------------
# Static files (กันพังถ้าไม่มีโฟลเดอร์)
# -----------------------------
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
else:
    logger.warning("⚠️ ไม่มีโฟลเดอร์ static — ข้ามการ mount")