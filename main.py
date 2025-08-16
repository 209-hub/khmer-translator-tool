import os
import gspread
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# --- การตั้งค่า ---
SHEET_NAME = "translation_sheet.xlsx" # ชื่อ Google Sheet ของคุณ
CREDS_FILE = "credentials.json"       # ชื่อไฟล์ Key ที่ดาวน์โหลดมา

# --- เชื่อมต่อกับ Google Sheets ---
try:
    gc = gspread.service_account(filename=CREDS_FILE)
    spreadsheet = gc.open(SHEET_NAME)
    worksheet = spreadsheet.sheet1
    print("✅ เชื่อมต่อ Google Sheets สำเร็จ!")
except Exception as e:
    print(f"❌ ไม่สามารถเชื่อมต่อ Google Sheets ได้: {e}")
    worksheet = None

# --- FastAPI App ---
app = FastAPI()

# --- Models สำหรับรับส่งข้อมูล ---
class TaskRequest(BaseModel):
    interpreter_name: str

class SaveRequest(BaseModel):
    filename: str
    translation: str
    interpreter_name: str

# --- API Endpoints ---
@app.get("/get-task")
def get_task_for_interpreter(interpreter_name: str):
    if not worksheet:
        raise HTTPException(status_code=500, detail="ไม่สามารถเชื่อมต่อกับ Google Sheet")
    
    df = pd.DataFrame(worksheet.get_all_records())
    
    # หาแถวแรกที่ยังไม่มีคำแปล และยังไม่มีใครทำอยู่
    untranslated_rows = df[(df['คำแปล'] == '') & (df['สถานะ'] != 'กำลังแปล')]
    
    if untranslated_rows.empty:
        return {"message": "🎉 ยอดเยี่ยม! แปลครบทุกไฟล์แล้ว"}

    task_row = untranslated_rows.iloc[0]
    row_index_to_update = task_row.name + 2 # +2 เพราะ index ของ pandas เริ่มที่ 0 และ header คือแถวที่ 1

    # อัปเดตสถานะใน Sheet ว่ามีคนกำลังทำอยู่
    worksheet.update_cell(row_index_to_update, 4, f"กำลังแปลโดย {interpreter_name}")
    
    return {
        "filename": task_row['ชื่อไฟล์'],
        "duration": task_row['ความยาว(วินาที)'],
        "total_files": len(df),
        "current_index": int(task_row.name)
    }

@app.post("/save-task")
def save_translation(request: SaveRequest):
    if not worksheet:
        raise HTTPException(status_code=500, detail="ไม่สามารถเชื่อมต่อกับ Google Sheet")

    try:
        cell = worksheet.find(request.filename, in_column=1) # ค้นหาชื่อไฟล์ในคอลัมน์ที่ 1
        worksheet.update_cell(cell.row, 3, request.translation) # อัปเดตคำแปลในคอลัมน์ที่ 3
        worksheet.update_cell(cell.row, 4, "แปลเสร็จแล้ว") # อัปเดตสถานะในคอลัมน์ที่ 4
        return {"status": "success", "message": f"บันทึกไฟล์ {request.filename} เรียบร้อย"}
    except gspread.exceptions.CellNotFound:
        raise HTTPException(status_code=404, detail=f"ไม่พบไฟล์ {request.filename} ใน Sheet")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Serve Frontend ---
app.mount("/audio_clips", StaticFiles(directory="audio_clips"), name="audio_clips")

@app.get("/")
def read_root():
    return FileResponse('translator_tool.html')