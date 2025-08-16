import os
import gspread
import pandas as pd
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import secrets

# --- การตั้งค่า ---
SHEET_NAME = "translation_sheet.xlsx" 
CREDS_FILE = "credentials.json"
APP_PASSWORD = os.getenv("APP_PASSWORD", "default_password_123")

app = FastAPI()
worksheet = None

security = HTTPBearer()
active_tokens = set()

@app.on_event("startup")
def startup_event():
    global worksheet
    try:
        gc = gspread.service_account(filename=CREDS_FILE)
        spreadsheet = gc.open(SHEET_NAME)
        worksheet = spreadsheet.sheet1
        print("✅ เชื่อมต่อ Google Sheets สำเร็จ!")
    except Exception as e:
        print(f"❌ ไม่สามารถเชื่อมต่อ Google Sheets ได้: {e}")

class LoginRequest(BaseModel):
    password: str

class SaveRequest(BaseModel):
    filename: str
    translation: str
    interpreter_name: str

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.scheme != "Bearer" or credentials.credentials not in active_tokens:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    return credentials.credentials

@app.get("/health")
def health_check():
    return JSONResponse(content={"status": "ok"})

@app.post("/login")
def login(request: LoginRequest):
    if request.password == APP_PASSWORD:
        token = secrets.token_hex(16)
        active_tokens.add(token)
        return {"token": token}
    else:
        raise HTTPException(status_code=401, detail="Incorrect password")

@app.get("/get-task")
def get_task_for_interpreter(interpreter_name: str, token: str = Depends(verify_token)):
    if worksheet is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: ไม่สามารถเชื่อมต่อ Google Sheet")

    df = pd.DataFrame(worksheet.get_all_records())

    required_cols = ['ชื่อไฟล์', 'ความยาว(วินาที)', 'คำแปล', 'file_id', 'สถานะ']
    for col in required_cols:
        if col not in df.columns:
            # ถ้ายังไม่มีคอลัมน์ ให้สร้างขึ้นมาเลย
            worksheet.update_cell(1, len(df.columns) + 1, col)
            df[col] = ''
            print(f"เพิ่มคอลัมน์ '{col}' ใน Google Sheet")


    untranslated_rows = df[(df['คำแปล'] == '') & (df['สถานะ'] != 'กำลังแปล')]
    if untranslated_rows.empty:
        return {"message": "🎉 ยอดเยี่ยม! แปลครบทุกไฟล์แล้ว"}

    task_row = untranslated_rows.iloc[0]
    row_index_to_update = task_row.name + 2
    worksheet.update_cell(row_index_to_update, 5, f"กำลังแปลโดย {interpreter_name}")

    return {
        "filename": task_row['ชื่อไฟล์'],
        "duration": task_row['ความยาว(วินาที)'],
        "file_id": task_row['file_id'], # <<< ส่ง File ID ไปด้วย
        "total_files": len(df),
        "current_index": int(task_row.name)
    }

@app.post("/save-task")
def save_translation(request: SaveRequest, token: str = Depends(verify_token)):
    if worksheet is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: ไม่สามารถเชื่อมต่อ Google Sheet")
    try:
        cell = worksheet.find(request.filename, in_column=1)
        worksheet.update_cell(cell.row, 3, request.translation)
        worksheet.update_cell(cell.row, 5, f"แปลเสร็จแล้วโดย {request.interpreter_name}")
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def read_root():
    return FileResponse('translator_tool.html')