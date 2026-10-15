import os
import sys
import requests
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

CHUNK_SIZE = 8192

app = FastAPI()
product = "enter product url here"
basepath = os.path.dirname(os.path.abspath(sys.argv[1])).replace("\\","/")

def testFile(infile, filename):
    line = ""
    with open(infile, "rb") as file:
        line = line + filename
        ##  Check file for compliance
        ##  Fill line with result of test
        ##  ie, "FILENAME failed: color contrast below threshold"
        ##  ie, "FILENAME passed"
    file.close()
    return(line)

@app.get("/")
def read_root():
    return("Tester API Connection Successful")

@app.get("/report/")
def get_report():
    filepath = basepath + "/reports/report.md"

    return FileResponse(
        path = filepath,
        filename = "report.md",
        media_type = "application/md"
    )

@app.post("/setup/")
def setup_test():
    filepath = basepath + "/reports/report.md"
    with open(filepath, "w", encoding="utf-8") as file:
        file.write("")
    return("Test setup complete")

@app.post("/run/")
def run_test():
    filepath = Path(basepath + "/sheets/eval")
    pulledpath = basepath + "/sheets/pulled"
    reportpath = basepath + "/reports/report.md"
    report = open(reportpath, "w", encoding="utf-8")
    for item in filepath.iterdir():
        filename = item.name
        file = open(item, "rb")
        payload = {
            "filename":filename
        }
        files = {"file":file}
        file.close()
        response = requests.post(product, data=payload, files=files)
        if(response.status_code != 201):
            line = filename + " failed: unable to post to product\n"
            report.write(line)
        else:
            response = requests.get(product + "/" + filename, stream=True)
            if(response.status_code != 200):
                line = filename + " failed: unable to get file from product\n"
                report.write(line)
            else:
                newfilepath = pulledpath + filename
                with open(newfilepath, "wb") as file:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        file.write(chunk)
                file.close()
                line = testFile(newfilepath, filename)
                report.write(line)
    return("Test run complete")