from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
