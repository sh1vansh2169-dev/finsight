# FinSight specification (merged into MoneyOS)

This is the FinSight project specification supplied by the project owner on
2026-11-11 (sections 1–4 in full, sections 5–13 condensed without changing
their requirements). It was **merged into the MoneyOS plan, not adopted
wholesale**.
Decisions taken when merging:

| FinSight says | Decision |
| --- | --- |
| Name: FinSight | **Keep MoneyOS** (2026-11-11). **Changed 2026-11-13:** the visible name is now FinSight; internal identifiers stay `moneyos`. |
| React + TypeScript + Tailwind frontend | **Adopted.** Replaces Flutter. The UI/UX requirements in UI_UX.md still apply. |
| PostgreSQL, user accounts, JWT, password hashing, per-user isolation | **Adopted, timed with the frontend (Phase 8).** SQLite and single-user until then; the schema is already PostgreSQL-ready. PostgreSQL + Docker at deployment. |
| Refunds reduce the original expense | **Adopted.** Implemented as category-level netting (see ARCHITECTURE.md). |
| Preserve original imported records | **Adopted.** Raw cells are now kept for every imported row. |
| Credit-card bill payments are settlements; internal transfers are not income or spending | Already implemented (transfer type, excluded from income and spending). |
| Failed / pending / reversed handled separately | Already implemented. |
| Multi-currency only with exchange rates before combining | Already partly implemented: currencies are never combined. Exchange rates: planned. |
| Classification: TF-IDF + Logistic Regression, Random Forest, XGBoost | Adopted as candidates for Phase 6, compared against the keyword-rule baseline. |
| Forecasting: Linear Regression, Random Forest, XGBoost, ARIMA/SARIMA; MAE, RMSE, MAPE; uncertainty ranges | Adopted as candidates for Phase 6, alongside the MoneyOS baselines and exponential smoothing. MAPE only where actuals are never near zero. |
| Anomaly detection: Isolation Forest, LOF, z-score | Adopted as candidates for Phase 6. Flags are for review, never "fraud". |
| Recurring expense detection | Adopted, Phase 7 (feeds commitments and the what-if simulator). |
| Spending behaviour clustering (K-Means, hierarchical) | Adopted as a Phase 6 *research* item. With one user there is no population to cluster; it needs multiple synthetic profiles, or clustering months or merchants instead. |
| Rule-based recommendation engine | Adopted, Phase 7. |
| LLM assistant with tool calling | Already planned (Phase 10) with the same grounding rule. |
| CSV/Excel/PDF import | CSV done; Excel and supported PDF statements in Phase 9. |
| Plotly / Recharts | Recharts in the React app; Matplotlib stays for static reports. |
| Docker deployment | Phase 11. |
| Money Majra, financial digital twin, research question | Not in FinSight; **kept** from MoneyOS. |
| FinSight's 5-phase roadmap | Folded into the MoneyOS phases (README roadmap). |

---

## Original specification

### 1. Project Overview

FinSight is an AI-powered personal financial intelligence platform designed to help individuals understand, manage, analyse, and predict their financial activities through a unified interface.

People frequently use multiple payment platforms, such as Google Pay, PhonePe, Paytm, UPI, debit cards, credit cards, and bank accounts. However, their financial information remains distributed across different platforms, making it difficult to understand overall spending behaviour, track expenses, manage budgets, and plan future financial commitments.

FinSight aims to solve this problem by bringing financial transaction records from multiple sources into one unified system. It combines Data Science, Machine Learning, and Large Language Models (LLMs) to transform raw financial data into meaningful insights, predictive analysis, and personalised financial recommendations.

The primary objective is to move beyond traditional expense tracking and build an intelligent financial management system that understands a user's financial behaviour and helps them make better financial decisions.

### 2. Core Objectives

1. Unified Financial Management: Consolidate financial transaction records from multiple payment platforms, bank accounts, and cards into one interface.
2. Automated Expense Categorisation: Automatically classify transactions into categories such as food, shopping, travel, entertainment, education, bills, and healthcare.
3. Spending Behaviour Analysis: Analyse financial patterns to understand where, when, and why money is being spent.
4. Expense Prediction: Forecast future expenses using historical transaction data and machine learning models.
5. Budget Management: Help users establish budgets, monitor spending limits, and identify potential overspending.
6. Anomaly Detection: Identify unusual financial activities and unexpected changes in spending patterns.
7. Personalised Recommendations: Generate actionable suggestions to improve financial management and savings.
8. Conversational AI Assistant: Allow users to interact with their financial data through natural language queries.

### 3. Technology Stack

| Component | Technology |
| --- | --- |
| Frontend | React.js, TypeScript |
| UI Styling | Tailwind CSS |
| Backend | Python, FastAPI |
| Database | PostgreSQL |
| ORM | SQLAlchemy |
| Data Processing | Pandas, NumPy |
| Machine Learning | Scikit-learn, XGBoost |
| Deep Learning (Future Scope) | PyTorch |
| Time-Series Forecasting | SARIMA, XGBoost |
| LLM Integration | LLM API with tool/function calling |
| Data Visualisation | Plotly, Recharts |
| Authentication | JWT / secure session management |
| Deployment | Docker |

### 4. System Architecture

#### 4.1 Financial Data Integration Layer

Data sources: Google Pay, PhonePe, Paytm, bank account statements, debit and credit card statements, UPI transaction records, manual transaction entries.

Integration methods: CSV and Excel statement uploads; supported PDF statement extraction; manual transaction entry; authorised financial APIs where available; RBI Account Aggregator ecosystem integrations, subject to applicable eligibility, consent, and regulatory requirements.

The system will initially focus on manual entries and statement imports. Direct financial integrations will be introduced in later development phases.

#### 4.2 Data Processing and Management Layer

ETL pipeline: data extraction from uploaded files; data cleaning and validation; transaction normalisation; duplicate transaction detection; date and currency standardisation; merchant identification; transaction categorisation; internal transfer identification.

The processed records will be stored in a unified PostgreSQL database. Original imported records will also be preserved to maintain data traceability and support reprocessing.

#### 4.3 Financial Analytics Layer

Total income and expenses; monthly and weekly spending; category-wise expenditure; daily spending patterns; average transaction value; savings estimates; recurring expenses; budget utilisation; cash-flow trends; income-versus-expense comparisons. The analytics layer will provide reliable numerical results to the dashboard, machine learning models, and AI assistant.

### 5. Machine Learning and Data Science Models

**5.1 Transaction Classification.** Automatically identify the category of each transaction (e.g. "Swiggy Order" → Food). TF-IDF features; Logistic Regression baseline; Random Forest; XGBoost; NLP for merchant and description processing. Workflow: description → preprocessing → TF-IDF → classifier → category. Metrics: accuracy, precision, recall, F1, confusion matrix. Start with Logistic Regression and compare with Random Forest and XGBoost before selecting the best-performing model.

**5.2 Expense Prediction and Forecasting.** Predict future spending from historical patterns, frequency, monthly trends, recurring expenses and category spending. Linear Regression baseline; Random Forest Regressor; XGBoost Regressor; ARIMA/SARIMA. Metrics: MAE, RMSE, MAPE where appropriate. Predictions include uncertainty ranges rather than being presented as guaranteed future expenses.

**5.3 Anomaly Detection.** Isolation Forest; Local Outlier Factor; z-score. Example: a ₹8,000 food payment when ₹300–₹500 is normal. Suspicious patterns are flagged for user review rather than automatically declared fraudulent.

**5.4 Recurring Expense Detection.** Frequency-based pattern detection; date interval analysis; amount similarity; time-series pattern analysis. Example: ₹499 to the same service roughly every month.

**5.5 Spending Behaviour Clustering.** K-Means; hierarchical clustering. Features: average monthly expenditure, category ratios, transaction frequency, average transaction value, monthly savings rate, recurring expense ratio. Used to understand behavioural patterns, not to permanently label or judge users.

**5.6 Financial Recommendation Engine.** Initially rule-based (budget thresholds, spending trends, recurring expenses, savings goals); later ML-based ranking and personalisation. Example: recommend reviewing the entertainment budget when that spending rises sharply.

### 6. LLM Integration

Natural-language questions such as "Where did most of my money go this month?", "How much did I spend on food in the last 30 days?", "Am I spending more than I earned?", "How much am I likely to spend next month?", "Which expenses are increasing?", "How can I reduce unnecessary expenses?", "What recurring payments do I have?", "Am I likely to exceed my monthly budget?".

The LLM will not independently calculate financial figures or invent transaction records. Workflow: user query → LLM → intent identification → API / analytics tools → database and ML services → verified results → LLM response.

### 7. Dashboard and User Interface

Financial overview; transaction history; category analysis; spending trends; budget management; expense forecasting; financial insights; recurring payments; AI financial assistant; downloadable reports.

### 8. Database Architecture

PostgreSQL. Entities: users, financial accounts, data sources, transactions, transaction categories, merchants, import batches, raw transactions, transfers, budgets, predictions, financial insights, consent records, audit logs. Records isolated by user ownership. Monetary values use precise decimal types, not floating point.

### 9. Important Financial Logic

- Internal transfers between a user's accounts must not be counted as income or expenses.
- Credit card purchases should be counted as expenses.
- Credit card bill payments should be treated as settlements, not additional expenses.
- Refunds should reduce the original expense rather than be treated as ordinary income.
- Failed, pending, and reversed transactions must be handled separately from successful transactions.
- Multiple currencies must be supported, with appropriate exchange-rate information before calculating combined totals.

### 10. Security and Privacy

Secure authentication; password hashing; JWT or secure sessions; user-level access restrictions; encryption for sensitive data; secure file storage; consent-based integrations; audit logging; secure API communication; data deletion and consent revocation. FinSight will not request users' UPI PINs, banking passwords, or OTPs.

### 11. Development Roadmap (original; see README for the merged roadmap)

1. Core application: React frontend, FastAPI backend, PostgreSQL, authentication, transaction CRUD, account management, basic dashboard.
2. Financial data integration: CSV/Excel imports, PDF extraction, cleaning, normalisation, duplicate detection, categorisation, unified transaction management.
3. Data Science and ML: EDA, classification, spending analytics, forecasting, anomaly detection, recurring detection, clustering.
4. AI integration: LLM API, tool calling, financial Q&A, context-aware recommendations, AI-generated summaries.
5. Advanced features and deployment: authorised integrations, advanced forecasting, personalised recommendations, automated reports, performance, security testing, Docker deployment.

### 12–13. Expected Outcome and Summary

A functional AI-powered personal financial intelligence platform that consolidates records from multiple sources, categorises and analyses transactions, understands spending behaviour, predicts expenses and cash flow, identifies unusual activity, tracks budgets and recurring commitments, generates personalised recommendations, and answers questions through a conversational assistant. Vision: "Your Money. One Intelligence."
