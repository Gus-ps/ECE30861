import os
import sys
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()

@app.get("/")
def read_root():
    return("Tester API Connection Successful")

@app.get("/report/")
def get_report():
    filepath = os.path.dirname(os.path.abspath(sys.argv[1])).replace("\\","/") + "/reports/report.md"

    return FileResponse(
        path = filepath,
        filename = "report.md",
        media_type = "application/md"
    )

@app.post("/setup/")
def setup_test():
    return("Test setup successful")

@app.post("/run/")
def run_test():
    return("Test run complete")