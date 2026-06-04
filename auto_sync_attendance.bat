@echo off
cd /d "C:\Users\Web\Desktop\Digilatics Portal"
".venv\Scripts\python.exe" manage.py sync_device_attendance >> logs\auto_sync.log 2>&1
