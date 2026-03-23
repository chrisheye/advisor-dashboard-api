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

# --- DEMO DATA ---
DEMO_CLIENTS = [
    {
        "id": "c1",
        "company_id": "company_a",
        "advisor_id": "advisor_1",
        "client_name": "John Smith",
        "completed_at": "March 15, 2026",
        "persona": "Income Seeker",
        "persona_description": "Focused on creating more reliable retirement income and reducing uncertainty.",
        "protected_income_fit": "high",
        "fit_label": "Strong Candidate",
        "fit_headline": "Strong Candidate for Protected Income Strategies",
        "fit_explanation": "Driven by high longevity risk and low income stability.",
        "risk_exposure": "Moderate–High",
        "readiness": "Ready for Discussion",
        "key_drivers": ["High Longevity Risk", "Low Income Stability"],
        "radar_scores": {
            "longevity": 84,
            "income_stability": 76,
            "market_risk": 58,
            "health": 52,
            "behavioral": 44
        },
        "radar_caption": "This profile shows elevated longevity risk and income instability, suggesting a need for more predictable income sources.",
        "talking_points": [
            {
                "label": "Open",
                "text": "How are you thinking about income over what could be a long retirement horizon?"
            },
            {
                "label": "Explore",
                "text": "How comfortable would you feel if markets were down for several years while you were drawing income?"
            },
            {
                "label": "Introduce",
                "text": "Would you be open to exploring ways to create more predictable income as part of your broader retirement plan?"
            }
        ],
        "playbook_intro": "This playbook is designed for clients with high longevity risk and low income stability, where predictability can reduce long-term uncertainty.",
        "playbook_steps": [
            "Introduce income stability as a planning priority.",
            "Explore comfort with market-based income.",
            "Present protected income as an option rather than a product pitch.",
            "Address likely concerns around liquidity and flexibility.",
            "Discuss timing and appropriate next steps."
        ]
    },
    {
        "id": "c2",
        "company_id": "company_a",
        "advisor_id": "advisor_2",
        "client_name": "Maria Lopez",
        "completed_at": "March 17, 2026",
        "persona": "Cautious Planner",
        "persona_description": "Values security and wants to reduce the risk of future income shortfalls.",
        "protected_income_fit": "high",
        "fit_label": "Strong Candidate",
        "fit_headline": "Strong Candidate for Protected Income Strategies",
        "fit_explanation": "Driven by high longevity risk and elevated market risk sensitivity.",
        "risk_exposure": "High",
        "readiness": "Needs Education",
        "key_drivers": ["High Longevity Risk", "High Market Risk"],
        "radar_scores": {
            "longevity": 88,
            "income_stability": 62,
            "market_risk": 79,
            "health": 57,
            "behavioral": 48
        },
        "radar_caption": "This profile reflects substantial concern about sustaining income through market volatility over a long retirement.",
        "talking_points": [
            {
                "label": "Open",
                "text": "What concerns you most about relying on investments alone to support retirement income?"
            },
            {
                "label": "Explore",
                "text": "How important is it for at least part of your income to feel stable no matter what markets do?"
            },
            {
                "label": "Introduce",
                "text": "Some clients in your position prefer to anchor a portion of income with more predictability. Is that worth discussing?"
            }
        ],
        "playbook_intro": "This playbook fits clients who place a high value on income stability and may be sensitive to market-driven uncertainty.",
        "playbook_steps": [
            "Frame income security as part of total retirement resilience.",
            "Explore emotional and behavioral reactions to volatility.",
            "Introduce predictable income options in plain language.",
            "Clarify trade-offs around flexibility and guarantees.",
            "Follow up with a focused education conversation."
        ]
    },
    {
        "id": "c3",
        "company_id": "company_b",
        "advisor_id": "advisor_3",
        "client_name": "David Chen",
        "completed_at": "March 19, 2026",
        "persona": "Flexible Planner",
        "persona_description": "Appears more comfortable with flexibility and may place less emphasis on guaranteed income sources.",
        "protected_income_fit": "medium",
        "fit_label": "Possible Fit",
        "fit_headline": "Possible Fit for Protected Income Strategies",
        "fit_explanation": "Driven by moderate longevity risk and a balanced view of income stability.",
        "risk_exposure": "Moderate",
        "readiness": "Monitor",
        "key_drivers": ["Moderate Longevity Risk", "Moderate Income Stability"],
        "radar_scores": {
            "longevity": 63,
            "income_stability": 52,
            "market_risk": 49,
            "health": 42,
            "behavioral": 39
        },
        "radar_caption": "This client shows some retirement income vulnerabilities, but the case for protected income may depend more on preferences and timing.",
        "talking_points": [
            {
                "label": "Open",
                "text": "How important is flexibility versus predictability in the way you expect to draw retirement income?"
            },
            {
                "label": "Explore",
                "text": "Would you want to revisit more stable income strategies later if your priorities shift over time?"
            },
            {
                "label": "Introduce",
                "text": "Protected income may not be a priority today, but it could still play a role in a broader plan. Would you like to discuss that briefly?"
            }
        ],
        "playbook_intro": "This playbook is better suited to exploration than immediate action, with emphasis on preferences and future optionality.",
        "playbook_steps": [
            "Assess how strongly the client values flexibility versus certainty.",
            "Explore future scenarios that could increase the appeal of stable income.",
            "Position protected income as one planning tool among several.",
            "Avoid overemphasizing urgency.",
            "Revisit the topic as goals and risk perceptions evolve."
        ]
    }
]

# --- ROUTES ---

@app.get("/")
def root():
    return {"message": "advisor backend is running"}


@app.get("/advisor-clients")
def get_advisor_clients(
    company_id: str | None = None,
    advisor_id: str | None = None
):
    filtered_clients = DEMO_CLIENTS

    if company_id is not None:
        filtered_clients = [
            client for client in filtered_clients
            if client["company_id"] == company_id
        ]

    if advisor_id is not None:
        filtered_clients = [
            client for client in filtered_clients
            if client["advisor_id"] == advisor_id
        ]

    return filtered_clients
    if company_id is None:
        return DEMO_CLIENTS

    filtered_clients = [
        client for client in DEMO_CLIENTS
        if client["company_id"] == company_id
    ]
    return filtered_clients
