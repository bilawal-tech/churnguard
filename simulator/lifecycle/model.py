"""Churn ka dimaagh: sirf constants, koi file ya SQLite nahi.

Ye shuruati qeematein hain, Step 13 (180 din ki run) mein churn rate ~26.5% par tune hongi.
Roz ka churn chance = BASE_DAILY_CHURN * (1 + risk_score) * noise.
risk_score = price + network + usage + zero_balance adders ka jama.
"""

# --- status ---
ACTIVE = "ACTIVE"
SUSPENDED = "SUSPENDED"
CHURNED = "CHURNED"
REACTIVATED = "REACTIVATED"

# --- base chance ---
BASE_DAILY_CHURN = 0.0010        # prepaid, har ACTIVE customer, roz
POSTPAID_CHURN_FACTOR = 0.5
NOISE_SD = 0.25                  # chance par multiplicative noise

# --- price adder (arpu_band se) ---
PRICE_SENSITIVITY = {"low": 1.0, "mid": 0.5, "high": 0.2}
PRICE_WEIGHT = 0.6

# --- usage girawat: 7 din vs 28 din ka hafta-wari average ---
USAGE_WINDOW_DAYS = 7
HISTORY_DAYS = 28
USAGE_DROP_START = 0.5           # 7 din ka usage average ke 50% se kam ho to adder
USAGE_MAX_ADDER = 2.0            # usage 0 ho to ye adder

# --- network: 7 din ka dropped_calls / calls ratio ---
NETWORK_NORMAL_RATIO = 0.03
NETWORK_FULL_RATIO = 0.25
NETWORK_MAX_ADDER = 2.0

# --- zero balance (sirf prepaid) ---
ZERO_BALANCE_FULL_DAYS = 14
ZERO_BALANCE_MAX_ADDER = 1.5

# --- prepaid inactivity ---
INACTIVE_SUSPEND_DAYS = 14
INACTIVE_CHURN_DAYS = 30

# --- reactivation (sirf SUSPENDED) ---
REACTIVATE_CHANCE_PER_DAY = 0.03

# --- at-risk (chhupi state) ---
AT_RISK_THRESHOLD = 1.0          # risk_score is se upar ho to at_risk = 1
AT_RISK_CHURN_MULTIPLIER = 2.0
AT_RISK_RECOVER_DAYS = 14

# --- churn_reason (ground truth, model features mein kabhi nahi) ---
HIGH_PRICE = "HIGH_PRICE"
POOR_NETWORK = "POOR_NETWORK"
USAGE_DECLINE = "USAGE_DECLINE"
INACTIVITY = "INACTIVITY"
COMPETITOR_OFFER = "COMPETITOR_OFFER"
CHURN_REASONS = [HIGH_PRICE, POOR_NETWORK, USAGE_DECLINE, INACTIVITY, COMPETITOR_OFFER]
COMPETITOR_OFFER_SHARE = 0.10    # churners ka random hissa