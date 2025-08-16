import os
import gspread
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

SHEET_NAME = "translation_sheet.xlsx"
CREDS_FILE = "credentials.json"

app = FastAPI()
worksheet = None

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

class SaveRequest(BaseModel):
    filename: str
    translation: str
    interpreter_name: str

@app.get("/health")
def health_check():
    return JSONResponse(content={"status": "ok"})

@app.get("/get-task")
def get_task_for_interpreter(interpreter_name: str):
    if worksheet is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: ไม่สามารถเชื่อมต่อ Google Sheet")

    try:
        df = pd.DataFrame(worksheet.get_all_records())

        required_cols = ['ชื่อไฟล์', 'ความยาว(วินาที)', 'คำแปล', 'file_id', 'สถานะ']
        for col in required_cols:
            if col not in df.columns:
                raise HTTPException(status_code=500, detail=f"ไม่พบคอลัมน์ '{col}' ใน Google Sheet")

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาด: {e}")

@app.post("/save-task")
def save_translation(request: SaveRequest):
    if worksheet is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: ไม่สามารถเชื่อมต่อ Google Sheet")

    try:
        cell = worksheet.find(request.filename, in_column=1)
        worksheet.update_cell(cell.row, 3, request.translation)
        worksheet.update_cell(cell.row, 5, f"แปลเสร็จแล้วโดย {request.interpreter_name}")
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาด: {e}")

@app.get("/")
def read_root():
    return FileResponse('translator_tool.html')