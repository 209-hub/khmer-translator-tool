import os
import uuid
import gspread
import pandas as pd
import logging
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks

# -----------------------------
# CONFIGURATION
# -----------------------------
SHEET_ID = "1UAuEPU-OIzumxsqIag5xyxOCYldaqgKK70CMkReyv9M"
CREDS_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")

APP_PASSWORD = {
    "lam1": os.getenv("PASSWORD_lam1"),
    "lam2": os.getenv("PASSWORD_lam2"),
    "lam3": os.getenv("PASSWORD_lam3"),
    "lam4": os.getenv("PASSWORD_lam4"),
}

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
# AUTHENTICATION
# -----------------------------
class AuthRequest(BaseModel):
    interpreter_name: str
    password: str

active_tokens = {}

@app.post("/login")
def login(auth: AuthRequest):
    auth_interpreter_name = auth.interpreter_name.strip()
    if auth_interpreter_name in APP_PASSWORD and auth.password == APP_PASSWORD[auth_interpreter_name]:
        token = str(uuid.uuid4())
        active_tokens[token] = auth_interpreter_name
        return {"token": token, "interpreter_name": auth_interpreter_name}
    else:
        raise HTTPException(status_code=401, detail="Invalid interpreter name or password")

def get_current_user(token: str):
    user = active_tokens.get(token)
    if not user:
        # In a real app, you might check a database. For now, this is fine.
        # This part of the logic seems to depend on a header, which the JS doesn't send.
        # Let's rely on the token lookup.
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user

# -----------------------------
# GOOGLE SHEETS
# -----------------------------
worksheet = None

@app.on_event("startup")
def startup_event():
    global worksheet
    try:
        gc = gspread.service_account(filename=CREDS_FILE)
        spreadsheet = gc.open_by_key(SHEET_ID)
        worksheet = spreadsheet.worksheet("Sheet1")
        logging.info("✅ Google Sheets connection successful!")
    except Exception as e:
        logging.error(f"❌ Failed to connect to Google Sheets: {e}")
        raise RuntimeError("Failed to connect to Google Sheets") from e

# -----------------------------
# MODELS
# -----------------------------
class SaveRequest(BaseModel):
    filename: str
    translation: str
    interpreter_name: str

# -----------------------------
# ROUTES
# -----------------------------
@app.get("/")
def serve_index():
    return FileResponse("translator_tool.html")

@app.get("/get-all-tasks")
def get_all_tasks(token: str = Depends(get_current_user)):
    interpreter_name = token
    try:
        df = pd.DataFrame(worksheet.get_all_records())
        # เพิ่มบรรทัดนี้เพื่อแปลงคอลัมน์ 'คำแปล' เป็น string เสมอ
        if 'คำแปล' in df.columns:
            df['คำแปล'] = df['คำแปล'].astype(str)
        # ...
        if 'ผู้แปล' in df.columns:
            df['ผู้แปล'] = df['ผู้แปล'].astype(str).str.strip()
        else:
            return JSONResponse(content={"tasks": []})
        interpreter_tasks = df[df['ผู้แปล'] == interpreter_name.strip()].to_dict('records')
        return JSONResponse(content={"tasks": interpreter_tasks})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load tasks: {e}")

@app.post("/save-task")
async def save_task(
    save_req: SaveRequest, 
    token: str = Depends(get_current_user), 
    background_tasks: BackgroundTasks = None
):
    try:
        # ฟังก์ชันที่จะทำงานในเบื้องหลัง (Background Thread)
        def save_to_google_sheet(save_req: SaveRequest, interpreter_name: str):
            try:
                all_data = worksheet.get_all_values()
                df = pd.DataFrame(all_data[1:], columns=all_data[0])
                
                if save_req.filename not in df['ชื่อไฟล์'].values:
                    # ในเบื้องหลัง เราไม่สามารถส่ง HTTPException กลับไปได้
                    # แต่สามารถ log ข้อผิดพลาดเพื่อตรวจสอบภายหลังได้
                    logging.error(f"File not found in the sheet: {save_req.filename}")
                    return
                
                row_index = df[df['ชื่อไฟล์'] == save_req.filename].index[0] + 2
                header = all_data[0]
                
                col_translation = header.index("คำแปล") + 1
                col_status = header.index("สถานะ") + 1
                col_interpreter = header.index("ผู้แปล") + 1
                
                new_status = "แปลแล้ว" if save_req.translation.strip() else ""
                
                worksheet.update_cell(row_index, col_translation, save_req.translation)
                worksheet.update_cell(row_index, col_status, new_status)
                worksheet.update_cell(row_index, col_interpreter, save_req.interpreter_name)
                
                logging.info(f"✅ Data for '{save_req.filename}' saved successfully.")

            except Exception as e:
                logging.error(f"❌ Failed to save data for '{save_req.filename}': {e}")
        
        # เพิ่มฟังก์ชัน save_to_google_sheet เข้าไปใน BackgroundTasks
        background_tasks.add_task(save_to_google_sheet, save_req, token)
        
        # ส่งคำตอบกลับทันที
        return {"success": True, "message": "Save process has started in the background."}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start save process: {e}")