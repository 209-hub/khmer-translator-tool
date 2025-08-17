import os
import uuid
import gspread
import pandas as pd
import logging
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# -----------------------------
# CONFIGURATION
# -----------------------------
SHEET_ID = "1UAuEPU-OIzumxsqIag5xyxOCYldaqgKK70CMkReyv9M"
CREDS_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
APP_PASSWORD = {
    "ล่าม1": "Mi88611",  # <--- แก้ไขชื่อและรหัสผ่านที่นี่
    "ล่าม2": "Mi88612",
    "ล่าม3": "Mi88613",
    "ล่าม4": "Mi88614",
}
INTERPRETER_NAMES = ["ล่าม1", "ล่าม2", "ล่าม3", "ล่าม4"] # <--- แก้ไขชื่อล่ามที่นี่

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

active_tokens = {} # Dictionary to store tokens {token: interpreter_name}

@app.post("/login")
def login(auth: AuthRequest):
    if auth.interpreter_name in APP_PASSWORD and auth.password == APP_PASSWORD[auth.interpreter_name]:
        token = str(uuid.uuid4())
        active_tokens[token] = auth.interpreter_name
        return {"token": token, "interpreter_name": auth.interpreter_name}
    else:
        raise HTTPException(status_code=401, detail="Invalid interpreter name or password")

def get_current_user(token: str):
    if token not in active_tokens:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return active_tokens[token]

# -----------------------------
# GOOGLE SHEETS
# -----------------------------
worksheet = None

@app.on_event("startup")
def startup_event():
    global worksheet
    try:
        if not os.path.exists(CREDS_FILE):
            raise RuntimeError(f"Missing credentials file: {CREDS_FILE}")
        gc = gspread.service_account(filename=CREDS_FILE)
        spreadsheet = gc.open_by_key(SHEET_ID)
        worksheet = spreadsheet.sheet1
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

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/get-all-tasks")
def get_all_tasks(token: str = Depends(get_current_user)):
    interpreter_name = active_tokens.get(token)
    try:
        if worksheet is None:
            raise HTTPException(status_code=503, detail="Service Unavailable: Not connected to Google Sheet")
        
        df = pd.DataFrame(worksheet.get_all_records())
        
        if df.empty:
            return {"message": "No files found in the sheet."}
        
        # Filter tasks for the logged-in interpreter
        interpreter_tasks = df[df['ผู้แปล'] == interpreter_name].to_dict('records')
        
        return JSONResponse(content={"tasks": interpreter_tasks})
        
    except Exception as e:
        logging.error(f"Error fetching tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load tasks: {e}")

@app.get("/get-task/{filename}")
def get_task_by_filename(filename: str, token: str = Depends(get_current_user)):
    try:
        if worksheet is None:
            raise HTTPException(status_code=503, detail="Service Unavailable: Not connected to Google Sheet")
        
        df = pd.DataFrame(worksheet.get_all_records())
        
        task_row = df[df['ชื่อไฟล์'] == filename].iloc[0]
        
        task = {
            "file_id": task_row.get("file_id"),
            "filename": task_row.get("ชื่อไฟล์"),
            "duration": task_row.get("ความยาว(วินาที)"),
            "translation": task_row.get("คำแปล", ""),
            "status": task_row.get("สถานะ", ""),
            "total_files": len(df)
        }
        
        return JSONResponse(content=task)

    except IndexError:
        raise HTTPException(status_code=404, detail="File not found in the sheet.")
    except Exception as e:
        logging.error(f"Error fetching task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load task: {e}")


@app.post("/save-task")
def save_task(save_req: SaveRequest, token: str = Depends(get_current_user)):
    try:
        if worksheet is None:
            raise HTTPException(status_code=503, detail="Service Unavailable: Not connected to Google Sheet")
            
        df = pd.DataFrame(worksheet.get_all_records())
        
        if save_req.filename not in df['ชื่อไฟล์'].values:
            raise HTTPException(status_code=404, detail="File not found in the sheet.")

        row_index = df.index[df['ชื่อไฟล์'] == save_req.filename][0] + 2

        # Update columns based on header names
        header = worksheet.row_values(1)
        
        col_translation = header.index("คำแปล") + 1
        col_status = header.index("สถานะ") + 1
        col_interpreter = header.index("ผู้แปล") + 1

        new_status = "แปลแล้ว" if save_req.translation.strip() else ""

        worksheet.update_cell(row_index, col_translation, save_req.translation)
        worksheet.update_cell(row_index, col_status, new_status)
        worksheet.update_cell(row_index, col_interpreter, save_req.interpreter_name)

        return {"success": True, "message": "Data saved successfully."}

    except ValueError as ve:
        raise HTTPException(status_code=500, detail=f"Missing a required column in Google Sheet: {ve}")
    except Exception as e:
        logging.error(f"Error saving task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save data: {e}")

# Static file mount points
app.mount("/audio_clips", StaticFiles(directory="audio_clips"), name="audio_clips")
app.mount("/static", StaticFiles(directory="static"), name="static")