from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def root():
    return {"message": "advisor backend is running"}
    
from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def root():
    return {"message": "advisor backend is running"}


@app.get("/advisor-clients")
def get_advisor_clients():
    return [
        {
            "client_name": "John Smith",
            "persona": "Income Seeker",
            "protected_income_fit": "high",
            "key_drivers": ["High Longevity Risk", "Low Income Stability"]
        },
        {
            "client_name": "Maria Lopez",
            "persona": "Cautious Planner",
            "protected_income_fit": "high",
            "key_drivers": ["High Longevity Risk", "High Market Risk"]
        },
        {
            "client_name": "David Chen",
            "persona": "Flexible Planner",
            "protected_income_fit": "medium",
            "key_drivers": ["Moderate Longevity Risk"]
        }
    ]
