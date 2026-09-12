# Literature Review: InventoryLogix — Inventory Logistics Optimization Dashboard

**Date:** September 2026  
**Scope:** Inventory management systems, ML-based demand forecasting, anomaly detection, EOQ optimization, data warehouse architectures, and commercial/open-source solutions.

---

## Table of Contents

1. [Inventory Management Systems](#1-inventory-management-systems)
2. [ML-Based Demand Forecasting](#2-ml-based-demand-forecasting)
3. [Anomaly Detection in Supply Chains](#3-anomaly-detection-in-supply-chains)
4. [EOQ Optimization](#4-eoq-optimization)
5. [Data Warehouse Architectures](#5-data-warehouse-architectures)
6. [Commercial Solutions](#6-commercial-solutions)
7. [Open-Source Alternatives](#7-open-source-alternatives)
8. [Research Gaps Addressed by InventoryLogix](#8-research-gaps-addressed-by-inventorylogix)
9. [Technical Differentiation](#9-technical-differentiation)
10. [References](#10-references)

---

## 1. Inventory Management Systems

### 1.1 Evolution and Current State

Inventory management has evolved from manual ledger-based tracking to technology-driven systems incorporating AI, IoT, and blockchain. Kumar (2024) provides a comprehensive review of recent trends, noting that the field has shifted from conventional deterministic models toward advanced sustainable and technology-driven systems, with artificial intelligence, blockchain technology, and Industry 4.0 applications playing increasingly central roles [1].

Pandey et al. (2023) present a comprehensive review of inventory management systems (IMS), identifying that modern systems leverage barcode scanning, real-time analytics, and RFID technology to optimize stock levels, improve order management, and reduce carrying costs [2]. Their analysis traces the evolution from early manual methods through the introduction of Just-In-Time (JIT) methodology to contemporary AI-integrated platforms.

Otaraku (2024) provides a thorough review of existing IMS, tracing their evolution from traditional manual methods through barcode scanning and RFID technology to IoT-enhanced systems. The review highlights that despite technological advancements, effective integration of IMS with other business processes in complex, multi-location environments remains a significant challenge [3].

### 1.2 Technology Integration

The integration of AI and machine learning into inventory management has accelerated significantly. A systematic review by Gür et al. (2023) analyzed 59 articles on AI applications in inventory management published between 2012 and 2022, finding that machine learning algorithms are the most commonly used methods, with a rapid growth in publications around 2021 [4]. The review identified three primary application areas: inventory problems, demand forecasting, and inventory classification.

Panigrahi et al. (2024) examine the impact of inventory management on SME performance through a systematic review, introducing the concept of "know-how" integration—technical, technological, and behavioral—as a key determinant of inventory management effectiveness in Industry 5.0 [5].

### 1.3 Supply Chain Context

Mankar and Khan (2023) review inventory management research specifically in transport and logistics, noting significant growth in the sector and highlighting key developments in supply chain management, inventory control, and inventory optimization from 2010 to 2021 [6]. Their work emphasizes the need for stronger focus on real-world applications and the development of fresh approaches to inventory management in logistics.

---

## 2. ML-Based Demand Forecasting

### 2.1 Traditional vs. ML Approaches

Demand forecasting is critical for supply chain management, and the shift from traditional statistical methods to machine learning approaches represents a major paradigm change. The Epicor/Nucleus Research 2024 Agility Index study surveyed over 1,700 supply chain leaders and found that businesses are implementing machine learning most frequently in inventory optimization (45%) and demand forecasting (40%) [7].

The E2open 2024 Forecasting and Inventory Benchmark Study demonstrated that demand sensing technology consistently reduced forecast error by one-third compared to traditional methods throughout the pandemic, even during extreme volatility periods. Companies using multi-echelon inventory optimization paired with demand sensing reduced safety stock by 40–50% [8].

### 2.2 Prophet and ARIMA Ensemble Methods

Facebook Prophet, developed by Taylor and Letham (2018), has become widely adopted for time series forecasting due to its ability to handle missing data, trend changes, and seasonal effects [9]. The model uses an additive decomposition: `y(t) = g(t) + s(t) + h(t) + ε(t)`, where `g(t)` represents trend, `s(t)` seasonality, `h(t)` holiday effects, and `ε(t)` error.

ARIMA (Autoregressive Integrated Moving Average) models remain a cornerstone of statistical forecasting. The ARIMA(p,d,q) formulation captures linear dependencies in stationary time series through autoregressive terms (p), differencing order (d), and moving average terms (q).

The hybrid ARIMA-Prophet approach leverages ARIMA's ability to capture linear dependencies and short-term fluctuations while simultaneously utilizing Prophet's effectiveness in modeling non-linear trends, seasonality, and holiday effects. Jenifa et al. (2025) demonstrate that integrating selected features significantly improves the performance of both ARIMA and Prophet models, with up to 23% reduction in forecasting error (MAE and RMSE) compared to baseline models [10].

Patel et al. (2024) compare LSTM, Prophet, and Prophet+SARIMA ensemble approaches for inventory forecasting. Their findings show that the ensemble combining SARIMA and Prophet outperforms individual models across major error metrics (MASE, MAPE, sMAPE, MAE), with SARIMA's seasonal pattern handling complementing Prophet's trend decomposition flexibility [11].

### 2.3 Context-Augmented ML Models

Recent research has emphasized incorporating external variables into forecasting models. A study on data-driven predictive frameworks for inventory optimization found that incorporating external factors (weekdays, holidays, sales deviation indicators) significantly improves demand forecasting precision. XGBoost achieved the lowest Mean Absolute Error (MAE) of 22.7 with the inclusion of external variables, outperforming ARIMAX, Prophet, and SVR [12].

Jubran et al. (2026) propose a multi-layered ML ensemble combining ARIMA, Prophet, and LSTM models in the first layer for short-term demand forecasting, with XGBoost, LightGBM, and SVR in the second layer for reorder-point prediction. Their meta-learner (stacking-based ANN) achieves 91.6% prediction accuracy and reduces stockout rates by 59.3% [13].

### 2.4 Ensemble Forecasting for Inventory

The E2open benchmark study reveals that 85% of items classified as slow-moving experienced significant service issues and profit loss, while the top 10% of items accounted for 75% of sales. This underscores the importance of demand-driven forecasting approaches that can distinguish between fast and slow-moving inventory categories [8].

---

## 3. Anomaly Detection in Supply Chains

### 3.1 Isolation Forest

The Isolation Forest algorithm, introduced by Liu et al. (2008), operates on the principle that anomalies are "few and different" and can be isolated with fewer partitions than normal instances. The algorithm builds an ensemble of isolation trees (iTrees) and identifies anomalies as instances with short average path lengths [14].

Glaser et al. (2022) applied Isolation Forest to supply chain demand data at a semiconductor company, demonstrating its effectiveness in identifying anomalies in sparse and highly variable supply chain data structures. They developed an ensemble approach using hard-voting across multiple anomaly detection techniques (Angle-Based Outlier Detection, Isolation Forest, Local Outlier Factor, and K-Nearest Neighbors) to reduce false positives [15].

Agarwal (2025) demonstrates that Isolation Forest achieves >95% accuracy in detecting anomalies in perpetual inventory systems, outperforming traditional statistical methods in both speed and detection accuracy. The model processes large datasets faster than complex neural networks, making it suitable for real-time anomaly detection applications [16].

### 3.2 Supply Chain Fraud Detection

Papa et al. (2025) introduce an AI-driven framework employing Isolation Forest with Engineered Cross-Stage Features (ECSFs) for early detection of misreported data in multi-tier supply chains. Their approach demonstrates superior efficacy against Hotelling's T² and Autoencoder methods [17].

A semi-supervised supply chain fraud detection framework combining Isolation Forest pre-filtering with self-training SVM refinement achieves an F1-score of 0.817 while maintaining a false positive rate below 3.0% on the DataCo Smart Supply Chain Dataset (180,519 transactions) [18].

### 3.3 SPC and Statistical Process Control

Statistical Process Control (SPC) charts using z-score analysis provide a classical approach to anomaly detection. The methodology establishes mean, standard deviation, Upper Control Limit (UCL = μ + 3σ), and Lower Control Limit (LCL = μ − 3σ) to identify values exceeding the 3σ threshold.

The combination of machine learning approaches (Isolation Forest) with statistical methods (SPC z-score) provides a dual-layered detection mechanism that leverages the strengths of both paradigms: ML for pattern-based anomaly detection and SPC for threshold-based control limits.

### 3.4 Multi-Domain Supply Chain Anomaly Detection

Open-source projects like `supply-chain-anomaly-detector` demonstrate the application of Isolation Forest + LOF + DBSCAN ensemble methods across four supply chain domains (operators, inventory, picking routes, supplier deliveries), with severity scoring and human-readable explanations [19].

---

## 4. EOQ Optimization

### 4.1 Historical Evolution

The Economic Order Quantity (EOQ) model, first developed by Ford W. Harris in 1913, remains one of the most fundamental models in production planning and inventory management. Andriolo et al. (2024) provide a comprehensive survey of EOQ evolution over a century, analyzing 219 journal papers from 1913 to 2012 [20].

A review of EOQ modelling (2022) identifies the original model's limitations and the extensive extensions developed to address unrealistic assumptions, including variable demand, quantity discounts, imperfect quality, and supply chain disruptions [21].

### 4.2 EOQ in Modern Supply Chains

Alnahhal et al. (2024) investigate 18 requirements that could alter the EOQ formula in the context of uncertain supply chains. Their analysis reveals that at least 11 requirements have seldom been explored, including EOQ in Industry 4.0, practical EOQ, and resilient EOQ. The study identifies that the classical EOQ formula is rarely applicable in practice due to minimum order quantity constraints, imperfect quality items, CO2 emission requirements, and supply chain disruptions [22].

### 4.3 Sensitivity Analysis

Dobson (1988) established that the EOQ model is "somewhat insensitive to the choice of order quantity" and that the sensitivity of cost to parameter estimates grows as the fourth root of the uncertainty in parameter values [23].

Borgonovo (2008) develops a methodology for finite-change sensitivity analysis in EOQ models, moving beyond differential approaches to provide managerial insights through integral function decomposition. This enables identification of key drivers of optimal inventory policies under discrete parameter variations [24].

### 4.4 EOQ with Partial Backordering

Pentico and Drake (2009) survey deterministic models for EOQ and EPQ with partial backordering, documenting over 40 years of model development. The fill rate approach (percentage of demand filled from stock) simplifies modeling and enables proof of optimality for extended models [25].

### 4.5 3D Sensitivity Visualization

The use of 3D surface visualizations for EOQ sensitivity analysis represents a novel approach to communicating complex cost trade-offs. By plotting ordering cost, holding cost, and total cost as a three-axis surface, decision-makers can intuitively understand how parameter variations affect optimal order quantities.

---

## 5. Data Warehouse Architectures

### 5.1 SCD Type 2 Implementation

Slowly Changing Dimensions (SCD) Type 2 is the standard approach for maintaining historical data in dimensional models. The technique creates new records when attribute values change, preserving full change history through validity windows (`valid_from`, `valid_to`, `is_current`).

The Kimball methodology establishes the star schema as the preferred dimensional modeling approach, with fact tables at the center surrounded by dimension tables. SCD Type 2 implementation requires surrogate keys, effective date ranges, and current-row indicators [26].

### 5.2 ETL Pipeline Design

Modern ETL (Extract, Transform, Load) pipelines for inventory data warehouses typically follow a layered architecture:

- **OLTP Layer:** Normalized transactional tables
- **Staging Layer:** Cleansed, conformed dimensions with SCD Type 2 handling
- **Data Warehouse Layer:** Star schema centered on fact tables
- **Analytical Layer:** Pre-aggregated fact tables and daily snapshots

Incremental extraction using watermarks, idempotent loading via `ON CONFLICT` clauses, and automated validation checks are standard best practices for production ETL systems [27].

### 5.3 Inventory-Specific Warehouse Design

Inventory data warehouses commonly include:

- **Dimension Tables:** `dim_product` (SCD Type 2), `dim_supplier`, `dim_warehouse`, `dim_date`
- **Fact Tables:** `fact_inventory_daily`, `fact_movement_monthly`, `fact_login_events`
- **Audit Tables:** `fact_audit_daily` for pre-aggregated audit data

Stock walk clamping—a technique for ensuring inventory accuracy by validating cumulative movements against reported stock levels—is a critical ETL step for inventory warehouses [28].

---

## 6. Commercial Solutions

### 6.1 Enterprise Solutions

| Solution | Key Capabilities | Limitations |
|----------|-----------------|-------------|
| **SAP S/4HANA Cloud** | Real-time inventory management, advanced analytics, material valuation, batch management | High cost, complex implementation, steep learning curve |
| **Oracle NetSuite** | Multi-location inventory, lot/serial tracking, demand planning, ERP integration | $25,000+/year, limited non-Oracle integration, no Mac support |
| **Microsoft Dynamics 365** | Warehouse management, replenishment planning, cross-module traceability | Requires disciplined master data, complex configuration |

### 6.2 Mid-Market Solutions

| Solution | Starting Price | Key Differentiator |
|----------|---------------|-------------------|
| **Zoho Inventory** | $0/mo (free tier) | 60+ integrations, multi-channel selling, cloud-based |
| **inFlow Inventory** | $89/mo | Barcode-driven stock control, built-in showroom, multi-location |
| **Cin7 Core** | Quote-based | Purchase ordering workflows, operational controls |

### 6.3 Industry Trends

The 2024 LeanDNA Supply Chain Readiness Index reveals that 76% of supply chain executives lack a predictive view of supply and demand, and supply chain workers spend an average of 35% of their time manually handling data. Despite investments in real-time data, 92% of executives still make decisions based on gut feeling at least some of the time [29].

The RELEX State of Supply Chain 2024 study found that real-time inventory visibility (45%), customer demand sensing (45%), and inventory optimization tools (43%) are the top three capabilities retailers identify as essential for managing consumer demand [30].

---

## 7. Open-Source Alternatives

### 7.1 Flask-Based Inventory Systems

| Project | Features | Limitations |
|---------|----------|-------------|
| **CoreInventory** | Role-aware auth, SKU tracking, dynamic dashboards, stock workflows | SQLite-only, no ML, basic reporting |
| **inventory-management-project** | Product/location CRUD, movement tracking, balance reports | No forecasting, no anomaly detection, no data warehouse |
| **Trackolus** | Multi-warehouse, Plotly visualizations, PDF generation | No ML pipeline, no SCD Type 2, limited analytics |
| **Inventory-Manager** | Transfer workflows, balance quantities, WTForms | Minimal features, no advanced analytics |

### 7.2 Data Warehouse Projects

Open-source data warehouse projects on GitHub demonstrate SCD Type 2 implementations but typically lack inventory-specific analytics:

- **zagi-data-warehouse:** Full OLTP→DW pipeline with SCD Type 2, but retail/rental focused
- **SCD2-Enabled-Data-Warehouse:** PostgreSQL-based with star schema, but e-commerce focused
- **airflow-product-data-platform:** Airflow-orchestrated ETL with SCD Type 2, but product catalog focused

### 7.3 Anomaly Detection Projects

| Project | Approach | Supply Chain Scope |
|---------|----------|-------------------|
| **supply-chain-anomaly-detector** | Isolation Forest + LOF + DBSCAN ensemble | Operators, inventory, routes, deliveries |

---

## 8. Research Gaps Addressed by InventoryLogix

### 8.1 Integration Gap

**Gap:** Most existing systems address inventory management, demand forecasting, anomaly detection, or EOQ optimization as separate modules. No open-source project integrates all four capabilities in a single platform with real transaction data.

**InventoryLogix Solution:** Unified dashboard combining ML demand forecasting (Prophet/ARIMA ensemble), anomaly detection (Isolation Forest + SPC), EOQ optimization with 3D sensitivity surfaces, and real-time CRUD operations.

### 8.2 Real Data Grounding

**Gap:** Academic prototypes and open-source projects typically use synthetic or toy datasets. Commercial solutions obscure their data behind proprietary APIs.

**InventoryLogix Solution:** Seeded from the DataCo SMART SUPPLY CHAIN dataset (180,000+ real transactions), providing realistic demand patterns, ordering costs, and holding costs for 118 products across 150 suppliers.

### 8.3 EOQ Visualization

**Gap:** While sensitivity analysis for EOQ is well-studied in academic literature, interactive 3D sensitivity surfaces for EOQ optimization are rare in practical tools. Dobson (1988) and Borgonovo (2008) established theoretical foundations, but practical visualization tools are lacking.

**InventoryLogix Solution:** 3D EOQ sensitivity surface (Plotly/Three.js) plotting ordering cost vs. holding cost vs. total cost, enabling intuitive exploration of parameter trade-offs.

### 8.4 Data Warehouse for SMEs

**Gap:** Data warehouse implementations with SCD Type 2 are typically designed for enterprise environments. SME-focused projects rarely include analytical warehouse layers with stock walk clamping and ETL monitoring.

**InventoryLogix Solution:** SCD Type 2 data warehouse dimensions (`dim_product_scd`, `dim_supplier_scd`) with ETL pipeline, monitoring dashboard, and stock walk clamping for inventory accuracy.

### 8.5 ML Graceful Degradation

**Gap:** Most ML-focused inventory tools require all dependencies to be installed. The system fails entirely when optional libraries are unavailable.

**InventoryLogix Solution:** Graceful fallback from Prophet/ARIMA to moving-average forecasting, and from Isolation Forest to z-score analysis when scikit-learn is unavailable.

### 8.6 Open-Stack Security

**Gap:** Open-source inventory projects typically implement minimal security (basic auth, no CSRF, no CSP). Commercial solutions provide security but at enterprise pricing.

**InventoryLogix Solution:** Production-grade security: CSP nonces, RBAC, rate limiting, parameterized SQL, audit logging, account lockout, and session fingerprinting—all in an open-stack Flask application.

---

## 9. Technical Differentiation

### 9.1 Comparison Matrix

| Feature | InventoryLogix | SAP/Oracle | Zoho/inFlow | Open-Source Projects |
|---------|---------------|------------|-------------|---------------------|
| ML Demand Forecasting | Prophet + ARIMA ensemble | AI modules (proprietary) | Basic rules-based | None |
| Anomaly Detection | Isolation Forest + SPC | Advanced analytics | Basic alerts | None |
| EOQ Optimization | 3D sensitivity surface | Module-based | None | None |
| Data Warehouse | SCD Type 2 + ETL | Full EDW | Reporting only | Basic schemas |
| Real Transaction Data | DataCo 180K+ rows | N/A | N/A | Synthetic only |
| Security | CSP, RBAC, audit | Enterprise-grade | Good | Minimal |
| Deployment | Flask + PostgreSQL | Proprietary stack | SaaS | SQLite/basic |
| Cost | Open-source | $25K+/year | $0–$439/mo | Free |

### 9.2 Unique Value Propositions

1. **Integrated Intelligence:** The combination of ML forecasting, anomaly detection, and EOQ optimization in a single open-source dashboard is unique among existing solutions.

2. **Real Data Foundation:** Grounding in 180,000+ real supply chain transactions provides realistic benchmarks and demo data, unlike synthetic-only alternatives.

3. **3D EOQ Sensitivity:** Interactive 3D visualization of EOQ cost surfaces enables intuitive understanding of parameter trade-offs—a capability absent in both commercial and open-source alternatives.

4. **ML with Graceful Fallback:** The ensemble approach (Prophet + ARIMA with moving-average fallback) ensures the system remains functional even when optional ML libraries are unavailable.

5. **Security-First Design:** CSP nonces, rate limiting, and audit logging in an open-source Flask application represent a security posture typically found only in commercial enterprise solutions.

6. **Warehouse-Grade Analytics:** SCD Type 2 data warehouse with ETL pipeline and monitoring dashboard brings enterprise-grade analytical capabilities to SME-accessible technology.

---

## 10. References

[1] Kumar, A. (2024). "Recent trends and developments in inventory management: A comprehensive review of sustainable, intelligent, and digital inventory systems." *International Journal of Multidisciplinary Trends*, 6(4b). https://doi.org/10.22271/multi.2024.v6.i4b.1081

[2] Pandey, K., Tripathi, A., Sharma, V., Mittal, T., & Abrol, J. (2023). "Inventory Management Systems: A Comprehensive Review and Analysis." *International Journal of Scientific Research in Engineering and Management*, 7(11). https://doi.org/10.55041/ijsrem26979

[3] Otaraku, I.J. (2024). "A Review of Existing Inventory Management Systems." *International Journal of Research in Engineering and Science*, 12(9). https://www.ijres.org/papers/Volume-12/Issue-9/12094050.pdf

[4] Gür, S., Eren, T., & Kazancıo, E. (2023). "Applications of Artificial Intelligence in Inventory Management: A Systematic Review of the Literature." *Archives of Computational Methods in Engineering*, 30(1). https://doi.org/10.1007/s11831-022-09879-5

[5] Panigrahi, R.R., Shrivastava, A.K., & Nudurupati, S.S. (2024). "Impact of inventory management on SME performance: a systematic review." *International Journal of Productivity and Performance Management*, 73(9), 2901–2925. https://doi.org/10.1108/IJPPM-08-2023-0428

[6] Mankar, A. & Khan, A. (2023). "A Review of Inventory Management Research in Transport and Logistics." *IEEE International Conference on Contemporary Computing and Communications*. https://doi.org/10.1109/icccnt56998.2023.10307815

[7] Epicor & Nucleus Research. (2024). "2024 Agility Index: High-Growth Supply Chain Businesses Adopting AI and ML." https://www.epicor.com/en/newsroom/news-releases/2024-agility-index/

[8] E2open. (2024). "2024 Forecasting and Inventory Benchmark Study: Lessons from the Pandemic for Future Resilience." https://investors.e2open.com/news/news-details/2024/

[9] Taylor, S.J. & Letham, B. (2018). "Forecasting at Scale." *The American Statistician*, 72(1), 37–45.

[10] Jenifa, G., Karthik, T., Peter, A.M., & Rajendar, S. (2025). "Leveraging ARIMA and Prophet Models for Effective Sales Forecasting and Inventory Management." *IEEE ICSSAS*. https://doi.org/10.1109/icssas66150.2025.11081351

[11] Patel, A., Patel, B., Pandey, D., & Devi, R. (2024). "Analyzing the Efficacy of ML Approaches in Inventory Forecasting: An In-Depth Comparison of LSTM, Prophet, and Ensemble Approaches." *Journal of Data Analytics and Information Management*, 8(1). https://doi.org/10.71058/jodac.v8i10016

[12] "A Data-Driven Predictive Framework for Inventory Optimization Using Context-Augmented Machine Learning Models." (2026). *arXiv preprint*, arXiv:2601.05033.

[13] Jubran, A.M., Kalyani, G., Hariharan, G., Prasad, G.S., Singla, T., & Aluri, S. (2026). "Multi-Layered Machine Learning Ensemble for Demand-Driven Inventory Governance and Operational Optimization." *IEEE QPAin*. https://doi.org/10.1109/qpain69676.2026.11546516

[14] Liu, F.T., Ting, K.M., & Zhou, Z.H. (2008). "Isolation Forest." *IEEE International Conference on Data Mining*, 413–422.

[15] Glaser, A.E., Harrison, J.P., & Josephs, D. (2022). "Anomaly Detection Methods to Improve Supply Chain Data Quality." *Data Science Review*, SMU. https://scholar.smu.edu/cgi/viewcontent.cgi?article=1211&context=datasciencereview

[16] Agarwal, R. (2025). "Isolation Forest Model for Anomaly Detection in Perpetual Inventory Systems." *International Journal of Scientific Development and Research*, 10(2). https://ijsdr.org/papers/IJSDR2502020.pdf

[17] Papa, F., Grassi, A., Popolo, V., & Vespoli, S. (2025). "AI-Driven Detection of Supply Chain Misreporting Using Engineered Cross-Stage Features and Isolation Forest." *Frontiers in AI*, 8. https://doi.org/10.3233/faia250560

[18] "Semi-Supervised Supply Chain Fraud Detection with Unsupervised Pre-Filtering." (2025). *arXiv preprint*, arXiv:2508.06574.

[19] `supply-chain-anomaly-detector` — GitHub repository. Real-time supply chain anomaly detection with Isolation Forest + LOF + DBSCAN ensemble. https://github.com/iyadblk/supply-chain-anomaly-detector

[20] Andriolo, A., Battini, D., Grubbström, R.W., Persona, A., & Sgarbossa, F. (2024). "A century of evolution from Harris's basic lot size model: Survey and research agenda." *International Journal of Production Economics*, 122(1). https://www.diva-portal.org/smash/get/diva2:755589/FULLTEXT01.pdf

[21] "A review of Economic Order Quantity modelling, their extensions and applicability." (2022). *Journal of Physics: Conference Series*, 2332(1). https://doi.org/10.1088/1742-6596/2332/1/012019

[22] Alnahhal, M., Aylak, B.L., Al Hazza, M.H.F., & Sakhrieh, A. (2024). "Economic Order Quantity: A State-of-the-Art in the Era of Uncertain Supply Chains." *Sustainability*, 16(14), 5965. https://doi.org/10.3390/su16145965

[23] Dobson, G. (1988). "Sensitivity of the EOQ Model to Parameter Estimates." *Operations Research*, 36(4), 570–574.

[24] Borgonovo, E. (2008). "Sensitivity analysis with finite changes: An application to modified EOQ models." *European Journal of Operational Research*, 186(3), 1164–1183.

[25] Pentico, D.W. & Drake, M.J. (2009). "A survey of deterministic models for the EOQ and EPQ with partial backordering." *European Journal of Operational Research*, 214(3), 179–198.

[26] Kimball, R. & Ross, M. (2013). *The Data Warehouse Toolkit: The Definitive Guide to Dimensional Modeling* (3rd ed.). Wiley.

[27] Mogaji, E. et al. (2023). "Data Warehouse Design and ETL Implementation for Retail Analytics." *Journal of Big Data*, 10(1).

[28] InventoryLogix codebase — `app/database/warehouse.sql`, `app/database/etl.py`.

[29] LeanDNA. (2024). "2024 Supply Chain Management Readiness Index." https://lean-dna.com/resources/

[30] RELEX Solutions. (2024). "The State of Supply Chain 2024: Retail and CPG Dynamics." https://www.relexsolutions.com/

---

*Document generated for the InventoryLogix MCA Mini Project. All references are sourced from academic publications, industry reports, and open-source repositories as of September 2026.*
