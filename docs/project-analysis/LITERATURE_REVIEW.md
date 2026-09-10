# InventoryLogix — Literature Review

## 1. Academic References

### 1.1 Economic Order Quantity (EOQ) Model

**Title:** "How Much to Make of What"
**Author:** Ford W. Harris
**Year:** 1913
**Source:** Factory, The Magazine of Management

**Problem:** Determining the optimal order quantity to minimize total inventory costs (ordering + holding).

**Approach:** Mathematical model balancing:
- Ordering cost (decreases with larger orders)
- Holding cost (increases with larger orders)
- Formula: EOQ = √(2DS/H)

**Relevance:** Core optimization model in EOQ calculator module. Used to calculate optimal order quantities for 118 products.

**Limitations:**
- Assumes constant demand
- Assumes constant lead time
- No quantity discounts
- No stockout costs

---

### 1.2 Facebook Prophet

**Title:** "Forecasting at Scale"
**Authors:** Sean J. Taylor, Ben Letham
**Year:** 2017
**Source:** The American Statistician, Vol. 71, No. 1
**URL:** https://peerj.com/ms/3190/

**Problem:** Time series forecasting with seasonal patterns and missing data.

**Approach:** Additive regression model with:
- Trend: Piecewise linear or logistic growth
- Seasonality: Fourier series (yearly, weekly, daily)
- Holidays: User-specified events

**Technology:** Python library (prophet)

**Relevance:** Primary forecasting model in ML module. Handles weekly seasonality for demand prediction.

**Findings:**
- Handles missing data well
- Automatic seasonality detection
- Interpretable components
- Works with small-to-medium datasets

**Limitations:**
- Requires 2+ years of data for yearly seasonality
- Slower than simpler models
- No real-time updating

---

### 1.3 ARIMA (AutoRegressive Integrated Moving Average)

**Title:** Time Series Analysis: Forecasting and Control
**Authors:** George E. P. Box, Gwilym M. Jenkins
**Year:** 1970
**Source:** Holden-Day

**Problem:** Time series forecasting with autoregressive patterns and non-stationarity.

**Approach:** Linear model combining:
- AR (AutoRegressive): Past values
- I (Integrated): Differencing for stationarity
- MA (Moving Average): Past errors
- Order (p,d,q): Parameters for each component

**Technology:** statsmodels library

**Relevance:** Secondary forecasting model in ML module. ARIMA(1,1,1) provides complementary predictions to Prophet.

**Findings:**
- Strong statistical foundation
- Handles non-stationary data
- Well-understood properties
- Fast computation

**Limitations:**
- Requires stationary data (achieved via differencing)
- No automatic seasonality handling
- Sensitive to outliers
- Requires manual parameter tuning

---

### 1.4 Isolation Forest

**Title:** "Isolation Forest"
**Authors:** Fei Tony Liu, Kai Ming Ting, Zhi-Hua Zhou
**Year:** 2008
**Source:** IEEE International Conference on Data Mining (ICDM)
**URL:** https://cs.nju.edu.cn/zhouzh/zhouzh.files/publication/icdm08b.pdf

**Problem:** Anomaly detection in high-dimensional data.

**Approach:** Unsupervised algorithm that:
- Isolates observations by random partitioning
- Anomalies require fewer partitions (shorter path length)
- Uses ensemble of isolation trees

**Technology:** scikit-learn library

**Relevance:** Primary anomaly detection model. Identifies unusual stock movements (spikes, drops).

**Findings:**
- Linear time complexity O(n)
- No distance computations needed
- Handles high-dimensional data
- Works with small datasets

**Limitations:**
- Requires contamination parameter
- No anomaly scoring explanation
- Sensitive to random seed
- May miss contextual anomalies

---

### 1.5 Statistical Process Control (SPC)

**Title:** "Economic Control of Quality of Manufactured Product"
**Author:** Walter A. Shewhart
**Year:** 1931
**Source:** D. Vanstrand Company

**Problem:** Quality control through statistical methods.

**Approach:** Control charts with:
- Center Line (CL): Process mean
- Upper Control Limit (UCL): μ + 3σ
- Lower Control Limit (LCL): μ - 3σ
- Points beyond limits indicate special cause variation

**Relevance:** SPC z-score analysis in anomaly module. Provides interpretable control charts for stock movement monitoring.

**Findings:**
- Simple to implement and interpret
- Distinguishes common vs special cause variation
- Well-established in manufacturing
- No training required

**Limitations:**
- Assumes normal distribution
- Fixed control limits (no adaptation)
- May produce false alarms
- No root cause identification

---

## 2. Industry Solutions

### 2.1 SAP Integrated Business Planning (IBP)

**Type:** Enterprise Cloud Solution
**Technology:** SAP HANA, Cloud-native
**Features:**
- Demand forecasting (ML-powered)
- Inventory optimization
- Supply planning
- Sales and operations planning

**Comparison with InventoryLogix:**
| Aspect | SAP IBP | InventoryLogix |
|--------|---------|----------------|
| Cost | $$$$ (enterprise pricing) | Free (open-source) |
| Complexity | High (implementation team) | Low (single developer) |
| ML Capabilities | Advanced (custom models) | Basic (Prophet/ARIMA) |
| Scalability | Enterprise-grade | Single-instance |
| Deployment | Cloud-only | Cloud or on-premise |

**Relevance:** Shows enterprise-grade solution that InventoryLogix simplifies for SMBs.

---

### 2.2 Oracle SCM Cloud

**Type:** Enterprise Cloud Solution
**Technology:** Oracle Cloud Infrastructure
**Features:**
- Inventory management
- Demand management
- Supply planning
- Procurement

**Comparison:**
| Aspect | Oracle SCM | InventoryLogix |
|--------|------------|----------------|
| Target | Large enterprises | SMBs |
| Implementation | Months/years | Hours/days |
| Customization | Limited (configuration) | Full (source code) |
| Data Model | Complex (hundreds of tables) | Simple (12 tables) |

---

### 2.3 TradeGecko (QuickBooks Commerce)

**Type:** SMB Cloud Solution
**Technology:** Cloud-native SaaS
**Features:**
- Multi-channel inventory
- Order management
- B2B e-commerce
- Reporting

**Comparison:**
| Aspect | TradeGecko | InventoryLogix |
|--------|------------|----------------|
| ML Forecasting | No | Yes (Prophet/ARIMA) |
| Anomaly Detection | No | Yes (Isolation Forest) |
| EOQ Optimization | No | Yes (3D surface) |
| Customization | Limited | Full |
| Cost | $29-499/month | Free |

**Relevance:** Shows SMB solution that lacks ML capabilities.

---

### 2.4 inFlow Inventory

**Type:** SMB Desktop/Web Solution
**Technology:** Windows desktop + cloud sync
**Features:**
- Inventory tracking
- Purchase orders
- Sales orders
- Reporting

**Comparison:**
| Aspect | inFlow | InventoryLogix |
|--------|--------|----------------|
| Platform | Desktop-first | Web-first |
| ML | No | Yes |
| Data Warehouse | No | Yes (SCD Type 2) |
| API | Limited | Full REST API |
| Source Code | Closed | Open |

---

### 2.5 Odoo Inventory

**Type:** Open Source ERP Module
**Technology:** Python/PostgreSQL (similar stack)
**Features:**
- Inventory management
- Warehouse management
- Purchase management
- Manufacturing

**Comparison:**
| Aspect | Odoo | InventoryLogix |
|--------|------|----------------|
| Scope | Full ERP | Focused dashboard |
| ML | Limited (separate module) | Integrated |
| EOQ | No | Yes |
| Complexity | High (many modules) | Low (single purpose) |
| Customization | Module-based | Full source |

**Relevance:** Most similar competitor. Shows that even open-source ERPs lack integrated ML + EOQ.

---

## 3. Research Gap

### 3.1 Current Landscape

Most inventory management solutions fall into two categories:

1. **Enterprise Solutions** (SAP, Oracle):
   - Comprehensive but expensive
   - Require implementation teams
   - Vendor lock-in

2. **SMB Solutions** (TradeGecko, inFlow):
   - Affordable but limited
   - No ML capabilities
   - No optimization models

### 3.2 Missing Combination

No existing solution combines:
- ✅ Open-source Flask + PostgreSQL stack
- ✅ Integrated ML forecasting (Prophet/ARIMA)
- ✅ Anomaly detection (Isolation Forest + SPC)
- ✅ EOQ optimization with 3D visualization
- ✅ Real transaction data grounding
- ✅ Data warehouse with SCD Type 2
- ✅ Single-developer implementation

### 3.3 InventoryLogix Positioning

InventoryLogix fills this gap by providing:
- **Accessible**: Free, open-source, single-developer friendly
- **Capable**: ML forecasting + anomaly detection + EOQ optimization
- **Grounded**: Real transaction data (DataCo dataset)
- **Modern**: Dark-mode UI with animations
- **Secure**: CSP, RBAC, parameterized SQL

---

## 4. Technology Comparison

### 4.1 ML Libraries

| Library | Purpose | Pros | Cons | Used In |
|---------|---------|------|------|---------|
| Prophet | Time series | Easy to use, handles seasonality | Slow, requires pandas | InventoryLogix |
| statsmodels | Statistical models | Fast, well-documented | No automatic seasonality | InventoryLogix |
| scikit-learn | ML algorithms | Comprehensive, fast | No deep learning | InventoryLogix |
| TensorFlow | Deep learning | State-of-the-art accuracy | Complex, GPU required | Not used |
| PyTorch | Deep learning | Flexible, research-friendly | Complex, GPU required | Not used |

**Decision:** Prophet + ARIMA chosen for simplicity and no GPU requirement.

### 4.2 Web Frameworks

| Framework | Language | Pros | Cons | Used In |
|-----------|----------|------|------|---------|
| Flask | Python | Lightweight, flexible | No admin, less batteries | InventoryLogix |
| Django | Python | Batteries included, admin | Heavier, less flexible | Not used |
| FastAPI | Python | Async, type hints | Newer, less mature | Not used |
| Express | JavaScript | Fast, large ecosystem | No Python ML libs | Not used |

**Decision:** Flask chosen for flexibility and Python ML ecosystem.

### 4.3 Databases

| Database | Type | Pros | Cons | Used In |
|----------|------|------|------|---------|
| PostgreSQL | Relational | JSONB, stored procedures, RLS | Complex setup | InventoryLogix |
| SQLite | Embedded | Simple, zero config | No concurrency, limited | Not used |
| MySQL | Relational | Fast, popular | No JSONB, weaker procedures | Not used |
| MongoDB | Document | Flexible schema | No ACID, no stored procs | Not used |

**Decision:** PostgreSQL chosen for stored procedures, JSONB, and RLS support.

---

## 5. Research Directions

### 5.1 Potential Improvements

1. **Deep Learning Forecasting**: LSTM/Transformer models for complex patterns
2. **Real-time Anomaly Detection**: Streaming algorithms for live data
3. **Reinforcement Learning**: Optimal reorder policies
4. **Natural Language Interface**: Chat-based inventory queries
5. **Computer Vision**: Automated stock counting via cameras

### 5.2 Open Questions

1. How does Prophet/ARIMA ensemble compare to deep learning models?
2. What is the optimal contamination parameter for Isolation Forest in inventory data?
3. How should EOQ be adapted for stochastic demand?
4. What is the cost-benefit of real-time vs batch anomaly detection?

---

*Generated: September 10, 2026*
