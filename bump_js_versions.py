import hashlib
import re

base = r"D:\MCA\3rd Sem\Mini Project\Inventory Logistics Optimization Dashboard"

# Bump dashboard-3d.js version in dashboard.html
h = hashlib.md5(open(base + r"\app\static\js\dashboard-3d.js", "rb").read()).hexdigest()[:8]
src = open(base + r"\app\templates\dashboard.html", encoding="utf-8").read()
src = re.sub(r"(js/dashboard-3d\.js\?v=)[0-9a-f]+", r"\g<1>" + h, src)
open(base + r"\app\templates\dashboard.html", "w", encoding="utf-8").write(src)
print("dashboard-3d.js ->", h)

# Bump auth-bg.js version in base.html + landing.html
h2 = hashlib.md5(open(base + r"\app\static\js\auth-bg.js", "rb").read()).hexdigest()[:8]
for tpl in [r"\app\templates\base.html", r"\app\templates\landing.html"]:
    src = open(base + tpl, encoding="utf-8").read()
    src = re.sub(r"(js/auth-bg\.js\?v=)[0-9a-f]+", r"\g<1>" + h2, src)
    open(base + tpl, "w", encoding="utf-8").write(src)
print("auth-bg.js ->", h2)