MEDICAL_DISCLAIMER = (
    "This AI system does not replace professional doctors. Use it for education "
    "and triage support only, and contact a licensed clinician for diagnosis or treatment."
)

DOMAINS = [
    {
        "id": "agriculture",
        "name": "Agriculture AI",
        "short_name": "Agri AI",
        "tagline": "Smarter decisions from seed to harvest.",
        "description": "Crop planning, plant inspection, farm operations, learning guides, and market intelligence for modern growers.",
        "tools": [
            {
                "id": "plant-health-inspector",
                "title": "Plant Health Inspector",
                "description": "Analyze leaf images for disease, nutrient deficiency, pests, and treatment plans.",
                "accepts": ["image"],
                "fields": [
                    {"name": "crop", "label": "Crop", "type": "text", "placeholder": "Tomato, wheat, rice..."},
                    {"name": "symptoms", "label": "Visible symptoms", "type": "textarea", "placeholder": "Yellow spots, curling leaves, powdery patches..."},
                    {"name": "location", "label": "Location", "type": "text", "placeholder": "State or district"},
                ],
                "output_hints": ["Possible disease", "Confidence score", "Treatment", "Fertilizers", "Prevention"],
            },
            {
                "id": "crop-recommendation",
                "title": "Crop Recommendation System",
                "description": "Find best crops by soil, pH, rainfall, irrigation, season, and state.",
                "fields": [
                    {"name": "soilType", "label": "Soil type", "type": "select", "options": ["Alluvial", "Black", "Red", "Laterite", "Sandy", "Clay"]},
                    {"name": "ph", "label": "pH value", "type": "number", "placeholder": "6.8"},
                    {"name": "irrigation", "label": "Irrigation availability", "type": "select", "options": ["Low", "Moderate", "High", "Rainfed"]},
                    {"name": "temperature", "label": "Temperature", "type": "number", "placeholder": "28"},
                    {"name": "rainfall", "label": "Rainfall", "type": "number", "placeholder": "850"},
                    {"name": "state", "label": "State/location", "type": "text", "placeholder": "Maharashtra"},
                    {"name": "season", "label": "Season", "type": "select", "options": ["Kharif", "Rabi", "Zaid", "Perennial"]},
                ],
                "output_hints": ["Best crops", "Expected yield", "Water requirement", "Profitability", "Duration"],
            },
            {
                "id": "smart-farming-assistant",
                "title": "Smart Farming Assistant",
                "description": "Ask farming questions and get seasonal, organic, pest, and scheme guidance.",
                "accepts": ["chat"],
                "fields": [{"name": "question", "label": "Farming question", "type": "textarea", "placeholder": "How do I manage aphids organically in okra?"}],
                "output_hints": ["Guidance", "Irrigation", "Seasonal tips", "Pest control", "Government schemes"],
            },
            {
                "id": "agriculture-tools",
                "title": "Agriculture Tools",
                "description": "Plan fertilizer, irrigation, harvest timing, seed choice, weather alerts, and pricing.",
                "fields": [
                    {"name": "toolNeed", "label": "Tool needed", "type": "select", "options": ["Fertilizer calculator", "Irrigation planner", "Weather alerts", "Harvest planning", "Seed recommendation", "Market price insights"]},
                    {"name": "farmSize", "label": "Farm size", "type": "text", "placeholder": "2 acres"},
                    {"name": "crop", "label": "Crop", "type": "text", "placeholder": "Sugarcane"},
                ],
                "output_hints": ["Calculator result", "Schedule", "Risk alerts", "Market notes"],
            },
            {
                "id": "agriculture-learning",
                "title": "Agriculture Learning Section",
                "description": "Generate tutorials, crop guides, lesson plans, video ideas, and PDF-ready guides.",
                "fields": [
                    {"name": "topic", "label": "Topic", "type": "text", "placeholder": "Organic paddy cultivation"},
                    {"name": "level", "label": "Learner level", "type": "select", "options": ["Beginner", "Intermediate", "Advanced"]},
                    {"name": "format", "label": "Output format", "type": "select", "options": ["Tutorial", "Step-by-step guide", "Lesson plan", "Video recommendations", "PDF guide"]},
                ],
                "output_hints": ["Lessons", "Steps", "Resources", "PDF-ready content"],
            },
        ],
    },
    {
        "id": "healthcare",
        "name": "Healthcare AI",
        "short_name": "Health AI",
        "tagline": "Clear health guidance with safety first.",
        "description": "Symptom triage, image-assisted skin analysis, report explanations, wellness coaching, and medicine safety support.",
        "tools": [
            {
                "id": "symptom-checker",
                "title": "Symptom Checker",
                "description": "Map symptoms to possible conditions, severity, doctor type, precautions, and emergency alerts.",
                "disclaimer": MEDICAL_DISCLAIMER,
                "fields": [
                    {"name": "symptoms", "label": "Symptoms", "type": "textarea", "placeholder": "Fever, cough, chest pain..."},
                    {"name": "duration", "label": "Duration", "type": "text", "placeholder": "3 days"},
                    {"name": "age", "label": "Age", "type": "number", "placeholder": "28"},
                ],
                "output_hints": ["Possible conditions", "Severity", "Doctor type", "Precautions", "Emergency signs"],
            },
            {
                "id": "skin-disease-analyzer",
                "title": "Skin Disease Analyzer",
                "description": "Upload a skin image for acne, rash, infection possibility, confidence, and precautions.",
                "accepts": ["image"],
                "disclaimer": MEDICAL_DISCLAIMER,
                "fields": [
                    {"name": "skinArea", "label": "Skin area", "type": "text", "placeholder": "Face, arm, back..."},
                    {"name": "details", "label": "Details", "type": "textarea", "placeholder": "Itchy, painful, spreading, recent exposure..."},
                ],
                "output_hints": ["Possible conditions", "Confidence", "Skincare precautions", "When to seek care"],
            },
            {
                "id": "medicine-suggestion",
                "title": "Medicine Suggestion System",
                "description": "Get common OTC options, warnings, side effects, and dosage-safety disclaimers.",
                "disclaimer": MEDICAL_DISCLAIMER,
                "fields": [
                    {"name": "condition", "label": "Condition", "type": "text", "placeholder": "Mild headache"},
                    {"name": "allergies", "label": "Allergies or conditions", "type": "textarea", "placeholder": "Asthma, pregnancy, kidney disease, drug allergies..."},
                ],
                "output_hints": ["OTC options", "Precautions", "Side effects", "Doctor advice"],
            },
            {
                "id": "health-chat-assistant",
                "title": "Health Chat Assistant",
                "description": "Nutrition, fitness, water intake, sleep, stress, and lifestyle recommendations.",
                "accepts": ["chat"],
                "disclaimer": MEDICAL_DISCLAIMER,
                "fields": [{"name": "question", "label": "Health question", "type": "textarea", "placeholder": "Create a simple sleep improvement plan."}],
                "output_hints": ["Wellness plan", "Nutrition", "Fitness", "Sleep", "Stress management"],
            },
            {
                "id": "health-report-analyzer",
                "title": "Health Report Analyzer",
                "description": "Upload blood report PDF/image and explain values in simple language.",
                "accepts": ["pdf", "image"],
                "disclaimer": MEDICAL_DISCLAIMER,
                "fields": [
                    {"name": "reportType", "label": "Report type", "type": "select", "options": ["CBC", "Lipid profile", "Liver function", "Kidney function", "Thyroid", "Other"]},
                    {"name": "notes", "label": "Known context", "type": "textarea", "placeholder": "Any doctor notes or symptoms..."},
                ],
                "output_hints": ["Extracted values", "Simple explanation", "Abnormal values", "Follow-up questions"],
            },
        ],
    },
    {
        "id": "education",
        "name": "Education AI",
        "short_name": "Edu AI",
        "tagline": "Create learning materials in minutes.",
        "description": "Notes, worksheets, MCQs, presentations, tutoring, grading, and YouTube study tools for teachers and learners.",
        "tools": [
            {
                "id": "lecture-material-generator",
                "title": "Lecture Material Generator",
                "description": "Generate notes, summaries, explanations, flashcards, and revision sheets.",
                "fields": [
                    {"name": "topic", "label": "Topic", "type": "text", "placeholder": "Photosynthesis"},
                    {"name": "classLevel", "label": "Class/level", "type": "text", "placeholder": "Class 8"},
                    {"name": "format", "label": "Format", "type": "select", "options": ["Notes", "Summary", "Explanation", "Flashcards", "Revision sheet"]},
                ],
                "output_hints": ["Notes", "Flashcards", "Revision points", "Examples"],
            },
            {
                "id": "mcq-generator",
                "title": "MCQ Generator",
                "description": "Create topic-based MCQs with difficulty levels, answer keys, and explanations.",
                "fields": [
                    {"name": "topic", "label": "Topic", "type": "text", "placeholder": "Indian Constitution"},
                    {"name": "difficulty", "label": "Difficulty", "type": "select", "options": ["Easy", "Medium", "Hard", "Mixed"]},
                    {"name": "count", "label": "Number of questions", "type": "number", "placeholder": "10"},
                ],
                "output_hints": ["MCQs", "Answer key", "Explanations"],
            },
            {
                "id": "worksheet-generator",
                "title": "Worksheet Generator",
                "description": "Create class-wise PDF-ready worksheets and practice questions.",
                "fields": [
                    {"name": "topic", "label": "Topic", "type": "text", "placeholder": "Fractions"},
                    {"name": "classLevel", "label": "Class", "type": "text", "placeholder": "Class 5"},
                    {"name": "questionTypes", "label": "Question types", "type": "text", "placeholder": "MCQ, fill blanks, word problems"},
                ],
                "output_hints": ["Worksheet", "Practice questions", "Teacher key"],
            },
            {
                "id": "ppt-generator",
                "title": "PPT Generator",
                "description": "Generate presentation outlines with slide copy, diagrams, and image prompts.",
                "fields": [
                    {"name": "topic", "label": "Topic", "type": "text", "placeholder": "Climate change"},
                    {"name": "slides", "label": "Slides", "type": "number", "placeholder": "8"},
                    {"name": "style", "label": "Style", "type": "select", "options": ["Classroom", "Corporate", "Visual", "Minimal"]},
                ],
                "output_hints": ["Slide outline", "Speaker notes", "Image prompts", "Download-ready structure"],
            },
            {
                "id": "ai-tutor-chat",
                "title": "AI Tutor Chat",
                "description": "Solve doubts with step-by-step explanations, personalization, and quizzes.",
                "accepts": ["chat"],
                "fields": [{"name": "question", "label": "Doubt", "type": "textarea", "placeholder": "Explain quadratic equations step by step."}],
                "output_hints": ["Explanation", "Worked examples", "Quiz"],
            },
            {
                "id": "essay-grader",
                "title": "Essay Grader",
                "description": "Check grammar, clarity, structure, score, and improvement suggestions.",
                "fields": [
                    {"name": "essay", "label": "Essay", "type": "textarea", "placeholder": "Paste essay here..."},
                    {"name": "rubric", "label": "Rubric", "type": "textarea", "placeholder": "Optional grading criteria..."},
                ],
                "output_hints": ["Score", "Grammar", "Clarity", "Suggestions"],
            },
            {
                "id": "youtube-learning-tool",
                "title": "YouTube Learning Tool",
                "description": "Paste a YouTube URL to generate notes, key points, and quizzes.",
                "fields": [
                    {"name": "url", "label": "YouTube URL", "type": "text", "placeholder": "https://youtube.com/watch?v=..."},
                    {"name": "goal", "label": "Study goal", "type": "select", "options": ["Notes", "Key points", "Quiz", "Revision plan"]},
                ],
                "output_hints": ["Notes", "Key points", "Quiz", "Timestamps"],
            },
        ],
    },
]


def all_tools():
    return [{**tool, "domain_id": domain["id"], "domain_name": domain["name"]} for domain in DOMAINS for tool in domain["tools"]]


def get_domain(domain_id):
    return next((domain for domain in DOMAINS if domain["id"] == domain_id), None)


def get_tool(domain_id, tool_id):
    domain = get_domain(domain_id)
    if not domain:
        return None
    return next((tool for tool in domain["tools"] if tool["id"] == tool_id), None)
