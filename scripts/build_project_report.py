from pathlib import Path
import re
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.style import WD_STYLE_TYPE

ROOT = Path('/home/ubuntu/inventory-logix-dashboard')
DOCS = ROOT / 'docs' / 'project-analysis'
OUT = ROOT / 'docs' / 'InventoryLogix_Final_Project_Report.docx'


def set_cell_shading(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = tcPr.find(qn('w:shd'))
    if shd is None:
        shd = OxmlElement('w:shd')
        tcPr.append(shd)
    shd.set(qn('w:fill'), fill)


def set_cell_border(cell, **kwargs):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = tcPr.first_child_found_in('w:tcBorders')
    if tcBorders is None:
        tcBorders = OxmlElement('w:tcBorders')
        tcPr.append(tcBorders)
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        if edge in kwargs:
            tag = 'w:{}'.format(edge)
            element = tcBorders.find(qn(tag))
            if element is None:
                element = OxmlElement(tag)
                tcBorders.append(element)
            for key in ['sz', 'val', 'color', 'space']:
                if key in kwargs[edge]:
                    element.set(qn('w:{}'.format(key)), str(kwargs[edge][key]))


def add_page_number(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    fldChar1 = OxmlElement('w:fldChar')
    fldChar1.set(qn('w:fldCharType'), 'begin')
    instrText = OxmlElement('w:instrText')
    instrText.set(qn('xml:space'), 'preserve')
    instrText.text = 'PAGE'
    fldChar2 = OxmlElement('w:fldChar')
    fldChar2.set(qn('w:fldCharType'), 'end')
    run._r.append(fldChar1)
    run._r.append(instrText)
    run._r.append(fldChar2)


def add_placeholder(doc, title, route, purpose):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(f'{title}\n')
    r.bold = True
    r.font.size = Pt(15)
    r.font.color.rgb = RGBColor(35, 75, 90)
    r2 = p.add_run('\n[SCREENSHOT EVIDENCE PLACEHOLDER]\n')
    r2.bold = True
    r2.font.size = Pt(18)
    r2.font.color.rgb = RGBColor(125, 85, 35)
    r3 = p.add_run(f'Route or screen: {route}\n\n{purpose}\n\nThe repository contains the implemented route and template, but no captured image artifact. Insert an authenticated screenshot here after the application is run in the approved environment.')
    r3.font.size = Pt(10)
    p.paragraph_format.space_after = Pt(18)
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = table.cell(0, 0)
    cell.text = 'Screenshot area reserved for verified project output'
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    set_cell_shading(cell, 'F2F5F6')
    set_cell_border(cell, top={'val':'single','sz':'12','color':'9AAEB5'}, bottom={'val':'single','sz':'12','color':'9AAEB5'}, left={'val':'single','sz':'12','color':'9AAEB5'}, right={'val':'single','sz':'12','color':'9AAEB5'})
    for para in cell.paragraphs:
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_before = Pt(70)
        para.paragraph_format.space_after = Pt(70)
        for run in para.runs:
            run.font.size = Pt(12)
            run.font.italic = True
    doc.add_paragraph('Figure note: This is a documentation placeholder, not a fabricated screenshot.').italic = True


def add_md(doc, path, max_lines=None):
    text = Path(path).read_text(errors='replace')
    lines = text.splitlines()
    if max_lines:
        lines = lines[:max_lines]
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            i += 1
            continue
        if line.startswith('```'):
            code = []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                code.append(lines[i])
                i += 1
            p = doc.add_paragraph(style='Code')
            p.add_run('\n'.join(code))
            i += 1
            continue
        if line.startswith('|') and i + 1 < len(lines) and lines[i+1].startswith('|'):
            rows = []
            while i < len(lines) and lines[i].startswith('|'):
                if not re.match(r'^\|\s*-', lines[i]):
                    rows.append([x.strip() for x in lines[i].strip('|').split('|')])
                i += 1
            if rows:
                cols = max(len(r) for r in rows)
                table = doc.add_table(rows=0, cols=cols)
                table.style = 'Table Grid'
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                for ri, row in enumerate(rows):
                    cells = table.add_row().cells
                    for ci in range(cols):
                        cells[ci].text = row[ci] if ci < len(row) else ''
                        cells[ci].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                        if ri == 0:
                            set_cell_shading(cells[ci], 'DCE9ED')
                            for run in cells[ci].paragraphs[0].runs:
                                run.bold = True
                doc.add_paragraph()
            continue
        if line.startswith('# '):
            doc.add_heading(line[2:].strip(), level=1)
        elif line.startswith('## '):
            doc.add_heading(line[3:].strip(), level=2)
        elif line.startswith('### '):
            doc.add_heading(line[4:].strip(), level=3)
        elif line.startswith('#### '):
            doc.add_heading(line[5:].strip(), level=4)
        elif line.startswith('- ') or line.startswith('* '):
            p = doc.add_paragraph(style='List Bullet')
            p.add_run(line[2:].strip())
        elif re.match(r'^\d+\.\s+', line):
            p = doc.add_paragraph(style='List Number')
            p.add_run(re.sub(r'^\d+\.\s+', '', line))
        elif line.startswith('> '):
            p = doc.add_paragraph(style='Quote')
            p.add_run(line[2:])
        elif line == '---':
            p = doc.add_paragraph('')
            p.paragraph_format.space_after = Pt(2)
        else:
            clean = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', line)
            clean = clean.replace('**', '').replace('`', '')
            doc.add_paragraph(clean)
        i += 1


def add_section(doc, title, subtitle=None):
    doc.add_page_break()
    doc.add_heading(title, level=1)
    if subtitle:
        p = doc.add_paragraph(subtitle)
        p.style = doc.styles['Subtitle']


def add_heading_para(doc, heading, text):
    doc.add_heading(heading, level=2)
    doc.add_paragraph(text)


def build():
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Inches(0.8)
    sec.bottom_margin = Inches(0.75)
    sec.left_margin = Inches(0.9)
    sec.right_margin = Inches(0.75)
    sec.header_distance = Inches(0.35)
    sec.footer_distance = Inches(0.35)

    styles = doc.styles
    styles['Normal'].font.name = 'Aptos'
    styles['Normal']._element.rPr.rFonts.set(qn('w:eastAsia'), 'Aptos')
    styles['Normal'].font.size = Pt(10.5)
    styles['Normal'].paragraph_format.line_spacing = 1.08
    styles['Normal'].paragraph_format.space_after = Pt(5)
    styles['Title'].font.name = 'Aptos Display'
    styles['Title'].font.size = Pt(28)
    styles['Title'].font.bold = True
    styles['Heading 1'].font.name = 'Aptos Display'
    styles['Heading 1'].font.size = Pt(19)
    styles['Heading 1'].font.color.rgb = RGBColor(28, 74, 87)
    styles['Heading 2'].font.size = Pt(13)
    styles['Heading 2'].font.color.rgb = RGBColor(46, 92, 104)
    styles['Heading 3'].font.size = Pt(11)
    styles['Heading 3'].font.color.rgb = RGBColor(70, 90, 98)
    styles['Quote'].font.name = 'Aptos'
    styles['Quote'].font.italic = True
    styles['Quote'].font.color.rgb = RGBColor(70, 70, 70)
    if 'Code' not in styles:
        code_style = styles.add_style('Code', WD_STYLE_TYPE.PARAGRAPH)
        code_style.font.name = 'Consolas'
        code_style.font.size = Pt(8)
        code_style.font.color.rgb = RGBColor(45, 45, 45)
        code_style.paragraph_format.left_indent = Inches(0.25)
        code_style.paragraph_format.space_before = Pt(3)
        code_style.paragraph_format.space_after = Pt(6)
    for section in doc.sections:
        footer = section.footer.paragraphs[0]
        footer.text = 'InventoryLogix — Final Project Report'
        footer.runs[0].font.size = Pt(8)
        footer.runs[0].font.color.rgb = RGBColor(110, 110, 110)
        add_page_number(section.footer.add_paragraph())

    # Cover
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(100)
    r = p.add_run('INVENTORYLOGIX')
    r.bold = True; r.font.size = Pt(31); r.font.color.rgb = RGBColor(28,74,87)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run('Inventory Logistics Optimization Dashboard'); r.font.size = Pt(19); r.bold = True
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run('\nFinal Project Report\n\n').font.size = Pt(15)
    p.add_run('A full-stack inventory management and analytics application with demand forecasting, anomaly detection, EOQ optimization, reporting, and a PostgreSQL data warehouse.').font.size = Pt(12)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(90)
    p.add_run('Prepared from the implemented repository and its supporting evidence\n').font.size = Pt(11)
    p.add_run('Repository: UmerAnsari-developer/inventory-logix-dashboard\n').font.size = Pt(10)
    p.add_run('Evidence baseline: commit 9a37bff\n').font.size = Pt(10)
    doc.add_page_break()

    # Preliminary pages
    doc.add_heading('Declaration', level=1)
    doc.add_paragraph('This report describes the InventoryLogix project using the available source code, configuration, database artifacts, tests, Git history, and cited references. Project-specific claims are presented with appropriate evidence boundaries. Where the repository does not establish a fact, the report identifies the information as unknown or as an engineering interpretation.')
    doc.add_page_break()
    doc.add_heading('Acknowledgement', level=1)
    doc.add_paragraph('The report acknowledges the value of the open-source Python, Flask, PostgreSQL, statistical, machine-learning, visualization, testing, and deployment ecosystems used by the project. It also acknowledges the repository artifacts and test documentation that provide the basis for this report.')
    doc.add_page_break()
    doc.add_heading('Abstract', level=1)
    doc.add_paragraph('InventoryLogix is a web-based inventory logistics dashboard intended to bring operational inventory records, replenishment analysis, forecasting, anomaly detection, purchase-order workflows, warehouse reporting, and audit controls into one application. The implementation uses Flask and server-rendered templates on the application side, PostgreSQL for operational and analytical data, and a combination of Prophet, ARIMA, Isolation Forest, and statistical process control for analytical features. The project includes role-based access, CSRF protection, rate limiting, secure cookies, parameterized SQL, audit logging, reports, ETL, and a star-schema warehouse. Its strongest contribution is integration and transparency rather than a new forecasting algorithm. The report distinguishes implemented behavior from measured business outcomes, potential benefits, and unknown information.')
    doc.add_page_break()
    doc.add_heading('Table of Contents', level=1)
    doc.add_paragraph('This DOCX contains Word heading styles. Open the document in Microsoft Word or LibreOffice and update the Table of Contents field to generate page numbers automatically.')
    add_md(doc, DOCS/'FINAL_REPORT_INDEX.md', max_lines=180)
    doc.add_page_break()
    doc.add_heading('List of Figures', level=1)
    for x in ['Figure 1. System context and request flow','Figure 2. Application and database architecture','Figure 3. Operational and warehouse data flow','Figure 4. Authentication and security boundaries','Figure 5. Dashboard output screenshot placeholder','Figure 6. Inventory output screenshot placeholder','Figure 7. Reports output screenshot placeholder','Figure 8. Forecast and anomaly output screenshot placeholders','Figure 9. EOQ and monitoring output screenshot placeholders']:
        doc.add_paragraph(x, style='List Bullet')
    doc.add_page_break()
    doc.add_heading('List of Tables', level=1)
    for x in ['Table 1. Project technology stack','Table 2. Stakeholder roles and capabilities','Table 3. Functional requirements','Table 4. Non-functional requirements','Table 5. API catalogue','Table 6. Database entities','Table 7. Security controls','Table 8. Test results','Table 9. Limitations and improvements']:
        doc.add_paragraph(x, style='List Bullet')
    doc.add_page_break()
    doc.add_heading('List of Abbreviations and Glossary', level=1)
    glossary = [('AI','Artificial Intelligence'),('API','Application Programming Interface'),('ARIMA','AutoRegressive Integrated Moving Average'),('CSP','Content Security Policy'),('CSRF','Cross-Site Request Forgery'),('ETL','Extract, Transform, Load'),('EOQ','Economic Order Quantity'),('HTTP','Hypertext Transfer Protocol'),('ML','Machine Learning'),('RBAC','Role-Based Access Control'),('REST','Representational State Transfer'),('SCD','Slowly Changing Dimension'),('SPC','Statistical Process Control'),('SQL','Structured Query Language'),('TLS','Transport Layer Security'),('UI','User Interface'),('WSGI','Web Server Gateway Interface')]
    table = doc.add_table(rows=1, cols=2); table.style='Table Grid'; table.alignment=WD_TABLE_ALIGNMENT.CENTER
    table.rows[0].cells[0].text='Term'; table.rows[0].cells[1].text='Meaning'
    for c in table.rows[0].cells: set_cell_shading(c, 'DCE9ED')
    for a,b in glossary:
        row=table.add_row().cells; row[0].text=a; row[1].text=b

    # Chapters
    add_section(doc, 'Chapter 1 — Introduction')
    add_heading_para(doc, '1.1 Background', 'Inventory management sits between purchasing, warehouse operations, supplier coordination, and business reporting. When these activities are separated across spreadsheets or isolated tools, the organization can lose visibility into stock movements, reorder conditions, and demand changes. InventoryLogix addresses this operational setting by combining record management with analytical support in a single web application.')
    add_heading_para(doc, '1.2 Project Overview', 'InventoryLogix is a server-rendered Flask application with a REST API and PostgreSQL persistence. Its implemented scope includes products, suppliers, movements, purchase orders, warehouses, reports, EOQ calculations, forecasting, anomaly detection, monitoring, settings, authentication, and audit logging. The application also includes a data warehouse populated by an ETL pipeline.')
    add_heading_para(doc, '1.3 Problem Statement and Business Problem', 'The project targets operational problems that arise when inventory decisions depend on manual review: stockouts can be detected late, excess stock can remain unnoticed, demand variability can be difficult to interpret, and audit trails can be fragmented. The repository implements reorder queries, movement recording, demand forecasts, anomaly analysis, warehouse reporting, and audit records. The report does not claim measured cost savings or stockout reduction because those outcomes are not established by the available artifacts.')
    add_heading_para(doc, '1.4 Objectives', 'The primary objective is to unify inventory records and decision-support features. Secondary objectives include role-protected access, an API surface, reporting, warehouse analytics, security controls, and graceful analytical fallbacks. The objective evidence is drawn from the application modules, product documentation, routes, database procedures, tests, and deployment configuration.')
    add_heading_para(doc, '1.5 Scope, Users, and Report Organization', 'The implemented scope covers a single-organization inventory command center. Viewer users have read-only access, while managers and administrators have write access. The project does not evidence multi-tenant data isolation, barcode scanning, native mobile applications, ERP connectors, billing, or shipment-carrier integrations. The remainder of the report follows the final index and separates evidence from interpretation.')
    add_md(doc, DOCS/'PROJECT_ANALYSIS.md', max_lines=95)

    add_section(doc, 'Chapter 2 — Literature Review and Existing System Analysis')
    doc.add_paragraph('This chapter uses the existing literature review as a foundation and preserves its distinction between verified references, repository evidence, and engineering interpretation. It does not claim that InventoryLogix advances the state of the art. Its defensible contribution is the integration of established techniques in one transparent project.')
    add_md(doc, DOCS/'LITERATURE_REVIEW.md', max_lines=95)

    add_section(doc, 'Chapter 3 — Feasibility and Requirements Specification')
    add_heading_para(doc, '3.1 Project Category and Domain', 'The project is an inventory-management and logistics-optimization web application with operational, analytical, and reporting characteristics. It can be classified as a modular monolith because the implemented features run in one Flask application process while remaining separated into routes, services, repositories, machine-learning modules, and database artifacts.')
    add_heading_para(doc, '3.2 Feasibility', 'Technical feasibility is supported by the use of mature Python, Flask, PostgreSQL, statistical, visualization, and deployment components. Operational feasibility is supported by role-specific pages, reports, monitoring, and a first-run database bootstrap. Economic feasibility is a potential advantage of the open-source stack and low-cost deployment configuration, but no verified ROI is available. Schedule feasibility is partially supported by the tracked Git history, although the history begins after some work had already occurred.')
    add_heading_para(doc, '3.3 Requirements', 'Functional requirements include authentication, product and supplier management, movement recording, purchase-order workflows, reports, EOQ calculation, forecasting, anomaly detection, monitoring, and settings. Non-functional requirements include security, response safety, validation, maintainability, caching, data integrity, and deployability. The tests and route implementation provide the strongest evidence for these requirements.')
    add_md(doc, DOCS/'TECHNICAL_ARCHITECTURE.md', max_lines=50)
    add_heading_para(doc, '3.4 Requirements Traceability Summary', 'Each important requirement should be traced to at least one implementation artifact and one validation artifact. For example, role restrictions are implemented in the security decorators and tested in the role test suite; forecasting behavior is implemented in the ML module and exercised by machine-learning tests; report behaviors are specified in the testing documentation and implemented by the reports route and template.')

    add_section(doc, 'Chapter 4 — System Analysis and Design')
    add_heading_para(doc, '4.1 Architecture', 'The system is a server-rendered Flask application with browser-side JavaScript for charts, animation, interaction, and API calls. Routes pass requests to service-layer logic and repositories, while repositories use psycopg2 and PostgreSQL procedures. The database contains operational tables and analytical warehouse structures. This architecture is cohesive for a single deployment but has process-local cache and security state that constrain horizontal scaling.')
    add_heading_para(doc, '4.2 Request and Data Flow', 'A typical product or movement request begins in a browser form or API client. The Flask route checks authentication and permissions, validates the submitted data, invokes a service, and then calls a repository or database procedure. PostgreSQL applies constraints and triggers. Mutation events are audited and relevant caches are invalidated. The response is rendered as HTML or returned as JSON.')
    add_heading_para(doc, '4.3 Database and Module Design', 'The application separates concerns into routes, services, repositories, security helpers, machine-learning modules, utilities, templates, and static assets. PostgreSQL stores users, products, suppliers, movements, purchase orders, audit records, caches, settings, ETL state, dimensions, and facts. The warehouse uses historical dimension behavior and incremental processing.')
    add_heading_para(doc, '4.4 API Architecture', 'The API includes health, product, supplier, movement, EOQ, settings, dashboard, forecast, and anomaly endpoints. The API provides a machine-readable interface for browser code and potential future clients. Authentication and route-level authorization protect data access and mutation operations.')
    add_md(doc, DOCS/'CHAPTER_7_SYSTEM_ARCHITECTURE.md', max_lines=60)
    add_md(doc, DOCS/'TECHNICAL_ARCHITECTURE.md', max_lines=50)

    add_section(doc, 'Chapter 5 — Development and Implementation')
    add_heading_para(doc, '5.1 Development Methodology and Approach', 'The repository supports an iterative implementation narrative through its commits, tests, modules, and successive fixes. It does not prove that a formal institutional methodology such as Scrum or Waterfall was followed. Accordingly, this report describes the observable development approach rather than attributing an unverified methodology to the developer.')
    add_heading_para(doc, '5.2 Development Timeline and Challenges', 'Git history provides evidence of implementation changes and testing activity within the tracked period. It does not establish a complete day-by-day history because the repository includes a large initial import. Challenges visible in the implementation include analytical dependencies, database initialization, security state, report caching, ETL behavior, and deployment configuration.')
    add_heading_para(doc, '5.3 Source Code Implementation', 'The source code follows a route–service–repository arrangement. Flask blueprints expose the application surface. Services contain business rules such as authentication, EOQ, movements, products, suppliers, and settings. Repositories issue PostgreSQL operations. The machine-learning package contains forecasting and anomaly detection. The security package applies validators, role checks, headers, and CSP nonces. The database directory contains schema, procedures, triggers, warehouse definitions, seed logic, and ETL processing.')
    add_md(doc, DOCS/'TECHNICAL_ARCHITECTURE.md', max_lines=45)
    add_heading_para(doc, '5.4 Output Screenshots', 'The implementation includes output screens for the landing page, authentication, dashboard, inventory, reorder alerts, suppliers, purchase orders, warehouses, reports, EOQ, forecasting, anomaly detection, monitoring, settings, help, and contact. The repository does not include captured screenshot files, so the following pages reserve evidence locations rather than presenting fabricated images.')
    for title, route, purpose in [
        ('Dashboard output', '/', 'KPI cards, stock health, movement trends, reorder queue, warehouse profile, and analytical summaries.'),
        ('Inventory output', '/inventory', 'Searchable and paginated product inventory with export behavior.'),
        ('Reports output', '/reports', 'Executive, warehouse, procurement, sales, and inventory-health report sections.'),
        ('Forecast and anomaly output', '/ai/forecast and /ai/anomaly', 'Forecast charts, confidence intervals, anomaly results, and portfolio summaries.'),
        ('EOQ and monitoring output', '/eoq-calculator and /monitoring', 'Economic order quantity analysis, sensitivity output, database status, ETL state, and monitoring data.'),
    ]:
        add_placeholder(doc, title, route, purpose)
        doc.add_page_break()
    add_heading_para(doc, '5.5 Module-Wise Implementation and Integration', 'The modules operate as a connected workflow rather than as isolated screens. A user action enters through a route, is checked by security controls, is validated by a service, reaches a repository and database procedure, triggers audit or integrity behavior, and returns to the page or API client. Analytical features use historical data and may cache portfolio outputs. ETL transforms operational records into warehouse structures used by monitoring and reporting.')
    add_heading_para(doc, '5.6 Configuration, Quality, and Maintainability', 'Environment-driven configuration separates database, email, feature flags, security, and deployment settings from application code. The application factory supports development, production, and testing configurations. The code is organized into recognizable layers, although the single-process deployment, raw SQL distribution, process-local state, and unused declared dependencies remain maintainability and scalability considerations.')
    add_md(doc, DOCS/'BUSINESS_GUIDE.md', max_lines=45)

    add_section(doc, 'Chapter 6 — Testing, Security, and Validation')
    add_heading_para(doc, '6.1 Testing Strategy', 'The test documentation records coverage of API behavior, authentication, caching, ETL, machine learning, roles, security, and services. The recorded test run reports 97 passing tests. This is strong evidence for the tested behaviors, but it is not evidence that every browser, deployment, load, recovery, or user-acceptance scenario has been completed.')
    add_heading_para(doc, '6.2 Security and Validation', 'Security controls include Flask-Login, role restrictions, password hashing, CSRF protection, secure cookies, account lockout, rate limiting, parameterized SQL, audit logging, CSP nonces, and security headers. Input validators constrain identifiers, numbers, email addresses, usernames, passwords, and text. Database triggers provide an additional integrity boundary for movement data.')
    add_heading_para(doc, '6.3 Verification and Limitations', 'The evidence register should be used to distinguish direct code evidence from interpretation. The principal limitations are process-local security and rate-limit state, a single-worker deployment configuration, model-derived benefit values, and the lack of captured UI or production-performance evidence in the repository.')
    add_md(doc, DOCS/'EVIDENCE_REGISTER.md', max_lines=70)
    add_md(doc, ROOT/'docs'/'Testing.md', max_lines=80)

    add_section(doc, 'Chapter 7 — Deployment, Results, and Evaluation')
    add_heading_para(doc, '7.1 Deployment', 'The deployment configuration uses Render for a Python web service and PostgreSQL, with Gunicorn as the WSGI server and an API health-check path. Environment variables provide database and security settings. The project includes first-run schema, seed, and ETL behavior. The configured deployment is suitable for demonstration and small-scale use, while higher availability and distributed state would require additional infrastructure.')
    add_heading_para(doc, '7.2 Results and Performance Evaluation', 'Verified results include passing automated tests, implemented routes, functional database procedures, ETL behavior, machine-learning fallbacks, security-header tests, and role tests. The repository also documents caching and query-batching improvements. These are implementation and test results. They should not be presented as measured organizational ROI, confirmed stockout reduction, or independently validated forecast accuracy.')
    add_heading_para(doc, '7.3 Business and Operational Impact', 'Potential operational value includes better visibility, more consistent replenishment review, earlier anomaly investigation, and consolidated reporting. The value is plausible because corresponding functions are implemented, but the organization-level effect requires live deployment data and a before-and-after evaluation design.')
    add_md(doc, DOCS/'BUSINESS_GUIDE.md', max_lines=60)
    add_heading_para(doc, '7.4 Maintenance and Evaluation Plan', 'Maintenance should include dependency review, database backup and migration discipline, monitoring, cache review, security testing, and periodic model evaluation. A future evaluation should measure stockout frequency, inventory turns, carrying cost, order-cycle time, forecast error on holdout data, anomaly precision, and report response time under representative load.')

    add_section(doc, 'Chapter 8 — Limitations, Future Scope, and Conclusion')
    add_heading_para(doc, '8.1 Limitations', 'The project is a single-tenant application without an implemented organization boundary. It does not provide evidence of native mobile clients, barcode scanning, ERP integrations, billing, shipment integration, or multi-instance shared security state. Forecasting uses classical models and a fallback rather than a validated production forecasting program. The deployment has a narrow worker configuration and the repository does not include captured UI screenshots or independent production measurements.')
    add_heading_para(doc, '8.2 Future Scope', 'Priority improvements include centralized rate-limit and lockout state, stronger deployment configuration validation, clearer background-job observability, holdout-based forecast evaluation, stochastic replenishment models, richer integrations, expanded accessibility testing, automated screenshot capture, and a documented backup and recovery process.')
    add_heading_para(doc, '8.3 Conclusion', 'InventoryLogix is a substantial inventory-management mini-project that combines transactional workflows, analytical methods, data warehousing, reporting, and security controls. Its strongest technical quality is the integration of understandable components with explicit fallbacks and test coverage. Its maturity is best described as an advanced MVP or academic demonstration rather than an enterprise-ready product, because production-scale availability, distributed state, recovery, and measured business outcomes are not fully evidenced.')
    add_md(doc, DOCS/'EXECUTIVE_SUMMARY.md', max_lines=45)

    add_section(doc, 'Client, Sales, Interview, and Viva Preparation')
    add_md(doc, DOCS/'INTERVIEW_QA.md', max_lines=70)

    add_section(doc, 'Bibliography and References')
    add_md(doc, DOCS/'LITERATURE_REVIEW.md', max_lines=35)
    doc.add_paragraph('Repository evidence is cited by file path and function name throughout the report. External sources should be checked against the final institutional citation style before submission.')

    # Appendices
    for title, content_path, max_lines in [
        ('Appendix A — Project Requirements', DOCS/'FINAL_REPORT_INDEX.md', 180),
        ('Appendix B — Database Schema and ER Diagram', DOCS/'TECHNICAL_ARCHITECTURE.md', 35),
        ('Appendix C — API Documentation', DOCS/'PROJECT_ANALYSIS.md', 40),
        ('Appendix D — Important Source Code', DOCS/'TECHNICAL_ARCHITECTURE.md', 40),
        ('Appendix E — Test Cases and Test Results', ROOT/'docs'/'Testing.md', 45),
        ('Appendix F — Screenshot Evidence Register', None, None),
        ('Appendix G — Installation and Deployment Instructions', ROOT/'README.md', 45),
        ('Appendix H — Additional Technical Documentation', DOCS/'AGENT_TEAM.md', 35),
        ('Appendix I — Evidence and Document-Control Register', DOCS/'EVIDENCE_REGISTER.md', 50),
    ]:
        add_section(doc, title)
        if content_path:
            add_md(doc, content_path, max_lines=max_lines)
        else:
            doc.add_paragraph('The repository does not contain captured image files. This register identifies the screenshots that should be inserted after authenticated execution in an approved environment.')
            for x in ['Dashboard — /', 'Inventory — /inventory', 'Reports — /reports', 'Forecast — /ai/forecast', 'Anomaly — /ai/anomaly', 'EOQ — /eoq-calculator', 'Monitoring — /monitoring', 'Authentication and error states — /auth/*']:
                doc.add_paragraph(x, style='List Bullet')

    # References
    doc.add_page_break()
    doc.add_heading('References', level=1)
    refs = [
        ('[1]', 'https://flask.palletsprojects.com/', 'Flask Documentation'),
        ('[2]', 'https://www.postgresql.org/docs/', 'PostgreSQL Documentation'),
        ('[3]', 'https://scikit-learn.org/stable/modules/outlier_detection.html', 'Scikit-learn Outlier Detection'),
        ('[4]', 'https://facebook.github.io/prophet/', 'Prophet Documentation'),
        ('[5]', 'https://www.statsmodels.org/', 'Statsmodels Documentation'),
        ('[6]', 'https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP', 'MDN Content Security Policy'),
        ('[7]', 'https://owasp.org/www-project-cheat-sheets/', 'OWASP Cheat Sheet Series'),
        ('[8]', 'https://render.com/docs', 'Render Documentation'),
        ('[9]', 'https://doi.org/10.1080/07421222.2018.1437534', 'Taylor and Letham, Forecasting at Scale'),
        ('[10]', 'https://doi.org/10.1109/ICDM.2008.17', 'Liu, Ting, and Zhou, Isolation Forest'),
    ]
    for n,url,title in refs:
        doc.add_paragraph(f'{n} {title}. {url}')

    doc.save(OUT)
    print(OUT)

if __name__ == '__main__':
    build()
