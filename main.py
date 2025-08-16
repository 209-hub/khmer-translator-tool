import os
import gspread
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# --- การตั้งค่า ---
SHEET_NAME = "translation_sheet.xlsx"
CREDS_FILE = "credentials.json"

app = FastAPI()
worksheet = None

# --- ฟังก์ชันสำหรับเชื่อมต่อ Google Sheets ตอนเริ่มต้น ---
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
        # โปรแกรมจะยังทำงานต่อ แต่จะแจ้ง Error เมื่อมีการเรียกใช้ API

# --- Models สำหรับรับส่งข้อมูล ---
class SaveRequest(BaseModel):
    filename: str
    translation: str
    interpreter_name: str

# --- API Endpoints ---

# <<< เพิ่ม Endpoint นี้เข้าไป >>>
@app.get("/health")
def health_check():
    # ประตูสำหรับให้ Render ตรวจสอบว่าเซิร์ฟเวอร์ทำงานอยู่
    return JSONResponse(content={"status": "ok"})

@app.get("/get-task")
def get_task_for_interpreter(interpreter_name: str):
    if worksheet is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: ไม่สามารถเชื่อมต่อกับ Google Sheet ได้ กรุณาตรวจสอบ Log")

    try:
        df = pd.DataFrame(worksheet.get_all_records())

        if 'สถานะ' not in df.columns:
            df['สถานะ'] = ''
            worksheet.update_cell(1, 4, 'สถานะ')

        untranslated_rows = df[(df['คำแปล'] == '') & (df['สถานะ'] != 'กำลังแปล')]

        if untranslated_rows.empty:
            return {"message": "🎉 ยอดเยี่ยม! แปลครบทุกไฟล์แล้ว"}

        task_row = untranslated_rows.iloc[0]
        row_index_to_update = task_row.name + 2

        worksheet.update_cell(row_index_to_update, 4, f"กำลังแปลโดย {interpreter_name}")

        return {
            "filename": task_row['ชื่อไฟล์'],
            "duration": task_row['ความยาว(วินาที)'],
            "total_files": len(df),
            "current_index": int(task_row.name)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาดในการอ่านข้อมูลจาก Sheet: {e}")


@app.post("/save-task")
def save_translation(request: SaveRequest):
    if worksheet is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: ไม่สามารถเชื่อมต่อกับ Google Sheet ได้")

    try:
        cell = worksheet.find(request.filename, in_column=1)
        worksheet.update_cell(cell.row, 3, request.translation)
        worksheet.update_cell(cell.row, 4, "แปลเสร็จแล้ว")
        return {"status": "success", "message": f"บันทึกไฟล์ {request.filename} เรียบร้อย"}
    except gspread.exceptions.CellNotFound:
        raise HTTPException(status_code=404, detail=f"ไม่พบไฟล์ {request.filename} ใน Sheet")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาดในการบันทึกข้อมูล: {e}")

# --- Serve Frontend ---
@app.get("/")
def read_root():
    return FileResponse('translator_tool.html')