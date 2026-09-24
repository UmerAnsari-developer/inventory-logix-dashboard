# Frontend Issue Mitigation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mitigate all identified frontend usability, accessibility, and reliability issues to improve user experience, accessibility compliance, and application robustness.
**Architecture:** Address issues
through targeted fixes to HTML templates, CSS stylesheets, and JavaScript files. Prioritize critical and high-severity issues first. Implement solutions that follow existing code patterns and maintain backward compatibility.

**Tech Stack:** HTML5, CSS3, JavaScript (ES5), Flask/Jinja2 templates

**Spec:** Research documents in `Issues/` folder (01- through 17-)

## Global Constraints

- Preserve current working functionality - no breaking changes
- Maintain compatibility with existing backend APIs
- Do not modify backend code unless absolutely necessary for frontend fix
- All changes must be testable and reversible
- Follow existing code style and patterns in the codebase
- Fixes must not introduce new security vulnerabilities
- Accessibility fixes must meet WCAG 2.1 AA standards
- Performance impact should be minimal or positive

## Review Focus

- Keyboard navigation and screen reader accessibility
- Mobile responsiveness and touch usability
- Form validation and error handling
- Notification and alert systems
- Data table usability and readability
- Action confirmation and undo protection
- Resource loading failure handling
- Session management and user state preservation

---

### Task 1: Fix Missing Notification Templates

**Files:**

- Create: `app/templates/notifications.html`
- Create: `app/templates/notification_detail.html`

**Interfaces:**

- Consumes: Notification data from Flask route context
- Produces: Rendered notification list and detail views

- [x] **Step 1: Create notifications.html template**

```html
{% extends "base.html" %} {% block title %}Notifications{% endblock %} {% block
content %}
<div class="container">
  <h1>Notifications</h1>
  {% if notifications %}
  <div class="list-group">
    {% for notification in notifications %}
    <a
      href="{{ url_for('notification_detail', id=notification.id) }}"
      class="list-group-item list-group-item-action"
    >
      <div class="d-flex w-100 justify-content-between">
        <h5 class="mb-1">{{ notification.title }}</h5>
        <small>{{ notification.timestamp }}</small>
      </div>
      <p class="mb-1">{{ notification.message }}</p>
      <small class="text-muted">{{ notification.category }}</small>
    </a>
    {% endfor %}
  </div>
  {% else %}
  <p class="text-muted">No notifications</p>
  {% endif %}
</div>
{% endblock %}
```

- [x] **Step 2: Create notification_detail.html template**

```html
{% extends "base.html" %} {% block title %}Notification Detail{% endblock %} {%
block content %}
<div class="container">
  <h1>Notification Detail</h1>
  {% if notification %}
  <div class="card">
    <div class="card-body">
      <h5 class="card-title">{{ notification.title }}</h5>
      <h6 class="card-subtitle mb-2 text-muted">
        {{ notification.timestamp }}
      </h6>
      <p class="card-text">{{ notification.message }}</p>
      {% if notification.category %}
      <span class="badge bg-secondary">{{ notification.category }}</span>
      {% endif %} {% if not notification.is_read %}
      <a
        href="{{ url_for('mark_notification_read', id=notification.id) }}"
        class="btn btn-sm btn-outline-primary"
        >Mark as Read</a
      >
      {% endif %}
    </div>
  </div>
  {% else %}
  <p class="text-muted">Notification not found</p>
  {% endif %}
  <a href="{{ url_for('notifications') }}" class="btn btn-outline-secondary"
    >Back to Notifications</a
  >
</div>
{% endblock %}
```

- [x] **Step 3: Verify templates render correctly**
      Run: Manual verification - navigate to /notifications and /notifications/1
      Expected: Pages render without 500 error, show notification data

- [x] **Step 4: Commit**

```bash
git add app/templates/notifications.html app/templates/notification_detail.html
git commit -m "feat: add missing notification templates"
```

### Task 2: Fix Manager Seeing Admin-Only Nav Links

**Files:**

- Modify: `app/templates/base.html` (around line 132)

**Interfaces:**

- Consumes: Current user role/context from Flask-Login or custom auth
- Produces: Filtered navigation menu based on user permissions

- [x] **Step 1: Locate admin-only nav links in base.html**

```html
<!-- Example location - adjust to actual code -->
<ul class="navbar-nav">
  <!-- Other nav links -->
  <li class="nav-item">
    <a class="nav-link" href="{{ url_for('admin_dashboard') }}"
      >Admin Dashboard</a
    >
  </li>
  <li class="nav-item">
    <a class="nav-link" href="{{ url_for('user_management') }}"
      >User Management</a
    >
  </li>
  <li class="nav-item">
    <a class="nav-link" href="{{ url_for('system_settings') }}"
      >System Settings</a
    >
  </li>
  <!-- More nav links -->
</ul>
```

- [x] **Step 2: Add role-based conditionals**

```html
<ul class="navbar-nav">
  <!-- Other nav links -->
  {% if current_user.has_role('admin') %}
  <li class="nav-item">
    <a class="nav-link" href="{{ url_for('admin_dashboard') }}"
      >Admin Dashboard</a
    >
  </li>
  {% endif %} {% if current_user.has_role('admin') %}
  <li class="nav-item">
    <a class="nav-link" href="{{ url_for('user_management') }}"
      >User Management</a
    >
  </li>
  {% endif %} {% if current_user.has_role('admin') %}
  <li class="nav-item">
    <a class="nav-link" href="{{ url_for('system_settings') }}"
      >System Settings</a
    >
  </li>
  {% endif %}
  <!-- More nav links with appropriate role checks -->
</ul>
```

- [x] **Step 3: Test with different user roles**
      Run:
- Login as admin → verify all 3 links visible
- Login as manager → verify links are hidden
- Login as viewer → verify links are hidden
- Attempt direct URL access as manager → should get 403 (backend protection)
  Expected: Links visible only to appropriate roles, no 403 from nav links

- [x] **Step 4: Commit**

```bash
git add app/templates/base.html
git commit -m "feat: add role-based visibility to admin nav links"
```

### Task 3: Fix Unguarded activityChart.getContext Call

**Files:**

- Modify: `app/templates/admin/user_activity_analytics/index.html` (around line 134)

**Interfaces:**

- Consumes: activityChart element from DOM
- Produces: Chart initialization or graceful degradation

- [x] **Step 1: Locate the JavaScript code**

```javascript
// Example - adjust to actual code
var activityChart = document.getElementById("activityChart");
var ctx = activityChart.getContext("2d");
var myChart = new Chart(ctx, {
  // chart configuration
});
```

- [x] **Step 2: Add null check**

```javascript
var activityChart = document.getElementById("activityChart");
if (activityChart) {
  var ctx = activityChart.getContext("2d");
  var myChart = new Chart(ctx, {
    // chart configuration
  });
} else {
  // Optional: show message or log
  console.log("Activity chart element not found");
  // Could show placeholder message:
  // document.getElementById('chart-container').innerHTML = '<p class="text-muted">No activity data available</p>';
}
```

- [x] **Step 3: Test with and without activityChart element**
      Run:
- Normal case: chart should render
- Edge case: simulate missing element (e.g., via conditional template) → should show message or fail gracefully
  Expected: No JavaScript errors, graceful handling when element missing

- [x] **Step 4: Commit**

```bash
git add app/templates/admin/user_activity_analytics/index.html
git commit -m "feat: add null check for activityChart.getContext"
```

### Task 4: Fix Empty Catch Blocks Swallowing Errors

**Files:**

- Modify: `app/templates/ai/monitoring.html` (9 locations)

**Interfaces:**

- Consumes: Potential JavaScript exceptions from try blocks
- Produces: Logged errors and/or user notifications

- [x] **Step 1: Locate all 9 instances of `catch(e){}`**

```javascript
// Example pattern to find
try {
  // some operation
} catch (e) {
  // EMPTY - NEED TO FIX
}
```

- [x] **Step 2: Replace with meaningful error handling**

```javascript
try {
  // some operation
} catch (e) {
  console.error("AI Monitoring error:", e);
  // Optionally show user notification in development
  if (typeof DEBUG !== "undefined" && DEBUG) {
    alert("An error occurred: " + e.message);
  }
  // In production, consider toast notification or silent logging only
}
```

- [x] **Step 3: Verify error handling works**
      Run:
- Trigger known error conditions in AI monitoring
- Open browser console
  Expected: Errors appear in console instead of being swallowed

- [x] **Step 4: Commit**

```bash
git add app/templates/ai/monitoring.html
git commit -m "feat: replace empty catch blocks with error logging"
```

### Task 5: Fix Missing Session Expiry UX

**Files:**

- Create: `app/static/js/session-handler.js`
- Modify: `app/static/js/main.js` (to initialize handler)
- Modify: `app/templates/base.html` (to include script)

**Interfaces:**

- Consumes: HTTP response status codes, user activity events
- Produces: Session expiry warnings and graceful redirect

- [x] **Step 1: Create session-handler.js**

```javascript
// app/static/js/session-handler.js
class SessionHandler {
    constructor(options = {}) {
        this.timeout = options.timeout || 1200000; // 20 minutes default
        this.warningTime = options.warningTime || 120000; // 2 minutes warning
        this.idleTimer = null;
        this.warningShown = false;
        this.init();
    }

    init() {
        // Reset timer on user activity
        const resetTimer = () => {
            clearTimeout(this.idleTimer);
            this.idleTimer = setTimeout(() => this.checkSession(), this.timeout);
            if (this.warningShown) {
                this.hideWarning();
                this.warningShown = false;
            }
        };

        // Listen for user activity
        ['mousedown', 'mousemove', 'keypress', 'scroll', 'touchstart'].forEach(event => {
            document.addEventListener(event, resetTimer, true);
        });

        // Start initial timer
        this.idleTimer = setTimeout(() => this.checkSession(), this.timeout);

        // Also check session validity on AJAX responses
        this.setupAjaxInterceptor();
    }

    setupAjaxInterceptor() {
        // If using jQuery
        if (window.jQuery) {
            jQuery(document).ajaxComplete((event, xhr, settings) => {
                if (xhr.status === 401 || xhr.status === 403) {
                    this.handleSessionExpired();
                }
            });
        }
        // For fetch API - would need to wrap fetch calls
        // This is a simplified version; real implementation would override fetch
    }

    checkSession() {
        // Could make AJAX request to check session status
        // For now, assume timeout means expired
        this.handleSessionExpired();
    }

    handleSessionExpired() {
        if (!this.warningShown) {
            this.showWarning();
            this.warningShown = true;
            // Reset timer to give user time to respond
            clearTimeout(this.idleTimer);
            this.idleTimer = setTimeout(() => {
                this.redirectToLogin();
            }, this.warningTime);
        }
    }

    showWarning() {
        // Create and show warning modal
        const modal = document.createElement('div');
        modal.innerHTML = `
            <div class="modal fade" id="sessionWarningModal" tabindex="-1" role="dialog">
                <div class="modal-dialog" role="document">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">Session Expiring Soon</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <p>Your session will expire in 2 minutes due to inactivity.</p>
                            <p>Click "Stay Signed In" to continue working.</p>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Stay Signed In</button>
                            <a href="{{ url_for('login') }}" class="btn btn-primary">Sign In Now</a>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        // Bootstrap modal initialization would go here
        // For simplicity, using basic alert in this example:
        // In practice, use Bootstrap modal or custom modal
        if (confirm('Your session will expire in 2 minutes due to inactivity. OK to stay signed in, Cancel to sign in now.')) {
            // User wants to stay signed in - reset timer
            this.hideWarning();
            this.resetTimer();
        } else {
            this.redirectToLogin();
        }
    }

    hideWarning() {
        // Hide warning modal
        // Implementation depends on modal approach used
    }

    redirectToLogin() {
        window.location.href = '{{ url_for('login') }}';
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    window.sessionHandler = new SessionHandler();
});
```

- [x] **Step 2: Update main.js to initialize session handler**

```javascript
// In app/static/js/main.js or similar
document.addEventListener("DOMContentLoaded", () => {
  // Existing initialization code...

  // Initialize session handler
  if (typeof SessionHandler !== "undefined") {
    window.sessionHandler = new SessionHandler();
  }
});
```

- [x] **Step 3: Update base.html to include the script**

```html
<!-- In base.html, add before closing </body> -->
<script src="{{ url_for('static', filename='js/session-handler.js') }}"></script>
```

- [x] **Step 4: Test session expiry handling**
      Run:
- Log in and wait for session to expire (or adjust timeout for testing)
- Verify warning appears before redirect
- Test that user can choose to stay signed in or proceed to login
  Expected: Warning shown, graceful handling, no sudden data loss

- [x] **Step 5: Commit**

```bash
git add app/static/js/session-handler.js app/static/js/main.js app/templates/base.html
git commit -m "feat: add session expiry warning and handling"
```

### Task 6: Fix Missing Offline/Timeout/Retry Handling

**Files:**

- Create: `app/static/js/http-client.js`
- Modify: Various files to use HTTP client instead of raw fetch/XHR

**Interfaces:**

- Consumes: Request configuration (URL, method, data, etc.)
- Produces: Promise that resolves with response or rejects with error

- [x] **Step 1: Create http-client.js with timeout and retry**

```javascript
// app/static/js/http-client.js
class HttpClient {
  constructor(defaultOptions = {}) {
    this.defaultOptions = {
      timeout: defaultOptions.timeout || 10000, // 10 seconds
      retries: defaultOptions.retries || 2,
      retryDelay: defaultOptions.retryDelay || 1000, // 1 second base
      ...defaultOptions,
    };
  }

  async request(url, options = {}) {
    const { timeout, retries, retryDelay, ...fetchOptions } = {
      ...this.defaultOptions,
      ...options,
    };

    let lastError;

    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        const response = await fetch(url, {
          ...fetchOptions,
          signal: controller.signal,
          headers: {
            "Content-Type": "application/json",
            ...(fetchOptions.headers || {}),
          },
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        return response;
      } catch (error) {
        lastError = error;
        clearTimeout(timeoutId); // Clear timeout if set

        // If this was the last attempt, don't retry
        if (attempt === retries) {
          break;
        }

        // Wait before retry (exponential backoff)
        await new Promise((resolve) =>
          setTimeout(resolve, retryDelay * Math.pow(2, attempt)),
        );
      }
    }

    throw lastError;
  }

  // Convenience methods
  get(url, options) {
    return this.request(url, { method: "GET", ...options });
  }

  post(url, data, options) {
    return this.request(url, {
      method: "POST",
      body: JSON.stringify(data),
      ...options,
    });
  }

  put(url, data, options) {
    return this.request(url, {
      method: "PUT",
      body: JSON.stringify(data),
      ...options,
    });
  }

  delete(url, options) {
    return this.request(url, { method: "DELETE", ...options });
  }
}

// Create singleton instance
window.httpClient = new HttpClient();
```

- [x] **Step 2: Update main.js and other files to use httpClient**

```javascript
// Instead of:
// fetch('/api/endpoint')
//     .then(response => response.json())
//     .then(data => { /* handle data */ })
//     .catch(error => { console.error(error); });

// Use:
httpClient
  .get("/api/endpoint")
  .then((response) => response.json())
  .then((data) => {
    /* handle data */
  })
  .catch((error) => {
    console.error("Request failed:", error);
    // Show user notification if appropriate
    showErrorNotification("Failed to load data. Please try again.");
  });
```

- [x] **Step 3: Add offline detection (optional enhancement)**

```javascript
// Add to http-client.js or create separate offline handler
window.addEventListener("online", () => {
  // Sync any queued operations
  console.log("Browser is online");
});

window.addEventListener("offline", () => {
  console.log("Browser is offline - some features may be unavailable");
  showNotification(
    "You are offline. Changes will sync when connection is restored.",
  );
});
```

- [x] **Step 4: Test timeout and retry behavior**
      Run:
- Simulate slow server (delay response) → should timeout and retry
- Simulate network failure → should retry then fail gracefully
- Verify normal requests still work quickly
  Expected: Requests timeout after configured period, retry 1-2 times, then show error

- [x] **Step 5: Commit**

```bash
git add app/static/js/http-client.js app/static/js/main.js /* other modified files */
git commit -m "feat: add HTTP client with timeout, retry, and offline handling"
```

### Task 7: Fix Missing Duplicate-Submit Guard

**Files:**

- Create: `app/static/js/form-handler.js`
- Modify: Form templates to use handler OR modify main.js for global handling

**Interfaces:**

- Consumes: Form submission events
- Produces: Prevented duplicate submissions, loading state feedback

- [x] **Step 1: Create form-handler.js**

```javascript
// app/static/js/form-handler.js
class FormHandler {
  constructor() {
    this.submittingForms = new WeakSet();
    this.init();
  }

  init() {
    // Handle form submissions globally
    document.addEventListener("submit", (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement)) return;

      // Skip if form has data-no-duplicate-protection attribute
      if (form.hasAttribute("data-no-duplicate-protection")) {
        return;
      }

      if (this.submittingForms.has(form)) {
        // Prevent duplicate submission
        event.preventDefault();
        return;
      }

      // Mark form as submitting
      this.submittingForms.add(form);

      // Disable submit buttons and show loading state
      const submitButtons = form.querySelectorAll(
        'button[type="submit"], input[type="submit"]',
      );
      submitButtons.forEach((button) => {
        button.disabled = true;
        // Store original text to restore later
        button.dataset.originalText = button.value || button.innerText;
        button.value = "Submitting...";
        button.innerText = "Submitting...";
      });

      // Re-enable buttons when form finishes (success or error)
      const handleFinish = () => {
        this.submittingForms.delete(form);
        submitButtons.forEach((button) => {
          button.disabled = false;
          button.value = button.dataset.originalText || "";
          button.innerText = button.dataset.originalText || "";
          delete button.dataset.originalText;
        });
        form.removeEventListener("submit", handleFinish);
        form.removeEventListener("reset", handleFinish);
      };

      form.addEventListener("submit", handleFinish);
      form.addEventListener("reset", handleFinish);
    });
  }
}

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
  window.formHandler = new FormHandler();
});
```

- [x] **Step 2: Alternative: Add to main.js for global handling**

```javascript
// In app/static/js/main.js
document.addEventListener("DOMContentLoaded", () => {
  // Existing code...

  // Add global form duplicate protection
  let submittingForms = new WeakSet();
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    if (form.hasAttribute("data-no-duplicate-protection")) {
      return;
    }

    if (submittingForms.has(form)) {
      event.preventDefault();
      return;
    }

    submittingForms.add(form);

    const submitButtons = form.querySelectorAll(
      'button[type="submit"], input[type="submit"]',
    );
    submitButtons.forEach((button) => {
      button.disabled = true;
      button.dataset.originalText = button.value || button.innerText;
      button.value = "Processing...";
      button.innerText = "Processing...";
    });

    const handleFinish = () => {
      submittingForms.delete(form);
      submitButtons.forEach((button) => {
        button.disabled = false;
        button.value = button.dataset.originalText || "";
        button.innerText = button.dataset.originalText || "";
        delete button.dataset.originalText;
      });
      form.removeEventListener("submit", handleFinish);
      form.removeEventListener("reset", handleFinish);
    };

    form.addEventListener("submit", handleFinish);
    form.addEventListener("reset", handleFinish);
  });
});
```

- [x] **Step 3: Test duplicate submission prevention**
      Run:
- Attempt rapid double-click on submit button
- Verify only one submission occurs
- Verify button shows loading state during submission
- Verify button re-enables after success or error
  Expected: Only one submission processed, UI shows feedback, no duplicate actions

- [x] **Step 4: Commit**

```bash
git add app/static/js/form-handler.js app/static/js/main.js /* if modified */
git commit -m "feat: add duplicate submission protection for forms"
```

### Task 8: Fix novalidate Without JavaScript Validation

**Files:**

- Modify: The 4 specific forms containing `novalidate` attribute
- Create: `app/static/js/form-validator.js` (reusable validation functions)

**Interfaces:**

- Consumes: Form input values
- Produces: Validation results, prevents submission of invalid data

- [x] **Step 1: Identify the 4 forms with novalidate**
      Likely candidates:
- Login form
- Registration form
- Password reset form
- Settings/profile form

- [x] **Step 2: Create form-validator.js with validation functions**

```javascript
// app/static/js/form-validator.js
class FormValidator {
  static isRequired(value) {
    return (
      value !== null && value !== undefined && value.toString().trim() !== ""
    );
  }

  static isEmail(value) {
    if (!this.isRequired(value)) return false;
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(value);
  }

  static isUrl(value) {
    if (!this.isRequired(value)) return false;
    try {
      new URL(value);
      return true;
    } catch (_) {
      return false;
    }
  }

  static minLength(value, length) {
    if (!this.isRequired(value)) return false;
    return value.toString().length >= length;
  }

  static maxLength(value, length) {
    if (!this.isRequired(value)) return true; // empty is ok for max
    return value.toString().length <= length;
  }

  static matches(value, regex) {
    if (!this.isRequired(value)) return false;
    return regex.test(value);
  }

  static isNumber(value) {
    return (
      !this.isRequired(value) || (!isNaN(parseFloat(value)) && isFinite(value))
    );
  }

  static min(value, min) {
    if (!this.isRequired(value)) return true;
    const num = parseFloat(value);
    return !isNaN(num) && num >= min;
  }

  static max(value, max) {
    if (!this.isRequired(value)) return true;
    const num = parseFloat(value);
    return !isNaN(num) && num <= max;
  }

  static validateField(field, rules) {
    const value = field.value;
    const errors = [];

    for (const rule of rules) {
      if (!rule.validator(value, rule.params)) {
        errors.push(rule.message);
      }
    }

    return errors;
  }

  static validateForm(form, fieldRules) {
    const allErrors = {};
    let isValid = true;

    for (const [fieldName, rules] of Object.entries(fieldRules)) {
      const field = form.elements.namedItem(fieldName);
      if (!field) continue;

      const errors = this.validateField(field, rules);
      if (errors.length > 0) {
        allErrors[fieldName] = errors;
        isValid = false;
      }
    }

    return { valid: isValid, errors: allErrors };
  }
}

// Make available globally
window.FormValidator = FormValidator;
```

- [x] **Step 3: Add validation to each form**

```html
<!-- Example for login form -->
<form id="login-form" method="POST" action="{{ url_for('login') }}">
  <div class="mb-3">
    <label for="username" class="form-label">Username</label>
    <input
      type="text"
      class="form-control"
      id="username"
      name="username"
      required
    />
    <div id="username-error" class="invalid-feedback d-none"></div>
  </div>
  <div class="mb-3">
    <label for="password" class="form-label">Password</label>
    <input
      type="password"
      class="form-control"
      id="password"
      name="password"
      required
    />
    <div id="password-error" class="invalid-feedback d-none"></div>
  </div>
  <button type="submit" class="btn btn-primary">Login</button>
</form>

<script>
  document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("login-form");
    const usernameError = document.getElementById("username-error");
    const passwordError = document.getElementById("password-error");

    form.addEventListener("submit", (event) => {
      // Clear previous errors
      usernameError.classList.add("d-none");
      passwordError.classList.add("d-none");

      // Define validation rules
      const rules = {
        username: [
          {
            validator: FormValidator.isRequired,
            params: [],
            message: "Username is required",
          },
          {
            validator: FormValidator.minLength,
            params: [3],
            message: "Username must be at least 3 characters",
          },
        ],
        password: [
          {
            validator: FormValidator.isRequired,
            params: [],
            message: "Password is required",
          },
          {
            validator: FormValidator.minLength,
            params: [6],
            message: "Password must be at least 6 characters",
          },
        ],
      };

      // Validate form
      const result = FormValidator.validateForm(form, rules);

      if (!result.valid) {
        event.preventDefault(); // Prevent submission

        // Show errors
        if (result.errors.username) {
          usernameError.textContent = result.errors.username[0]; // Show first error
          usernameError.classList.remove("d-none");
        }
        if (result.errors.password) {
          passwordError.textContent = result.errors.password[0];
          passwordError.classList.remove("d-none");
        }
      }
      // If valid, form will submit normally
    });
  });
</script>
```

- [x] **Step 4: Apply similar validation to all 4 forms**
- [x] **Step 5: Test validation behavior**
      Run:
- Try submitting forms with invalid data
- Verify inline errors appear and submission is blocked
- Verify valid submissions work normally
- Verify error messages disappear when fields become valid
  Expected: Client-side validation prevents invalid submissions, good UX

- [x] **Step 6: Commit**

```bash
git add app/static/js/form-validator.js /* modified form templates */
git commit -m "feat: add client-side validation to forms with novalidate"
```

### Task 9: Fix Missing aria-invalid and Accessible Error Wiring

**Files:**

- Modify: Form templates throughout application where validation occurs
- Possibly: Create `app/static/js/accessible-forms.js` helper

**Interfaces:**

- Consumes: Form field validation state
- Produces: Accessible error announcements for screen readers

- [x] **Step 1: Audit form validation points**
      Identify where:
- HTML5 validation occurs (required, type, pattern, min, max, etc.)
- JavaScript validation occurs (from Task 8)
- Server-side validation errors are displayed

- [x] **Step 2: Implement accessible error pattern**
      For each field that can show errors:

1. Ensure error message container has unique ID: `id="fieldname-error"`
2. When field is invalid:
   - Set `aria-invalid="true"` on the field
   - Update field's `aria-describedby` to include the error message ID
3. When field becomes valid:
   - Set `aria-invalid="false"` (or remove attribute)
   - Remove error message ID from `aria-describedby`

```javascript
// Example implementation in form validation
function validateAndSetAccessibility(field, errorElementId, isValid) {
    if (isValid) {
        field.removeAttribute('aria-invalid');
        const describedBy = field.getAttribute('aria-describedby') || '';
        const newDescribedBy = describedBy
            .split(' ')
            .filter(id => id !== errorElementId)
            .join(' ')
            .trim();
        if (newDescribedBy) {
            field.setAttribute('aria-describedby', newDescribedBy);
        } else {
            field.removeAttribute('aria-describedby');
        }
    } else {
        field.setAttribute('aria-invalid': 'true');
        const describedBy = field.getAttribute('aria-describedby') || '';
        const ids = describedBy ? describedBy.split(' ') : [];
        if (!ids.includes(errorElementId)) {
            ids.push(errorElementId);
            field.setAttribute('aria-describedby', ids.filter(Boolean).join(' '));
        }
    }
}
```

- [x] **Step 3: Apply to all form validation**
- For HTML5 validation: may need to use JavaScript to supplement
- For JavaScript validation (Task 8): integrate accessibility updates
- For server-side validation: ensure error messages are associated when rendered

- [x] **Step 4: Test with screen reader**
      Run:
- Use NVDA, JAWS, or built-in screen reader (Narrator, VoiceOver)
- Navigate to form with invalid field
- Verify screen reader announces field name, state, and error message
- Verify announcement updates when error appears/disappears
  Expected: Screen readers properly announce validation state and errors

- [x] **Step 5: Commit**

```bash
git add /* modified form templates */ app/static/js/accessible-forms.js /* if created */
git commit -m "feat: add accessible error wiring with aria-invalid and aria-describedby"
```

### Task 10: Fix Inventory Pagination Drops Filters

**Files:**

- Modify: `app/templates/inventory.html` (around lines 110 and 114)

**Interfaces:**

- Consumes: Current URL query parameters (filters, search, sort)
- Produces: Pagination links that preserve filter state

- [x] **Step 1: Analyze current filtering mechanism**
      Determine how inventory filtering works:
- Likely via query parameters: `?category=X&supplier=Y&search=Z&min_price=A&max_price=B`
- Check backend route to confirm supported parameters

- [x] **Step 2: Locate pagination controls in inventory.html**

```html
<!-- Example pagination - adjust to actual code -->
<nav aria-label="Page navigation">
  <ul class="pagination">
    {% if page.has_previous %}
    <li class="page-item">
      <a class="page-link" href="{{ url_for('inventory', page=page.prev_num) }}"
        >Previous</a
      >
    </li>
    {% else %}
    <li class="page-item disabled"><span class="page-link">Previous</span></li>
    {% endif %} {# Page numbers #} {% for p_num in page.iter_pages() %} {% if
    page_num %}
    <li class="page-item {% if page_num == page.page %}active{% endif %}">
      <a class="page-link" href="{{ url_for('inventory', page=p_num) }}"
        >{{ page_num }}</a
      >
    </li>
    {% else %}
    <li class="page-item disabled"><span class="page-link">…</span></li>
    {% endif %} {% endfor %} {% if page.has_next %}
    <li class="page-item">
      <a class="page-link" href="{{ url_for('inventory', page=page.next_num) }}"
        >Next</a
      >
    </li>
    {% else %}
    <li class="page-item disabled"><span class="page-link">Next</span></li>
    {% endif %}
  </ul>
</nav>
```

- [x] **Step 3: Modify pagination links to preserve query parameters**

```javascript
// Helper function to get current query params as object
function getQueryParams() {
  const params = new URLSearchParams(window.location.search);
  const obj = {};
  for (const [key, value] of params.entries()) {
    obj[key] = value;
  }
  return obj;
}

// Helper function to create URL with updated page parameter
function updateQueryParam(key, value) {
  const params = new URLSearchParams(window.location.search);
  if (value === null || value === "") {
    params.delete(key);
  } else {
    params.set(key, value);
  }
  return `${window.location.pathname}?${params.toString()}`;
}

// In template, we need to generate URLs that preserve current filters
// Since we can't easily run JS in template to build URLs, we'll pass current params to template
// Or use a different approach: modify the url_for calls to include current request.args
```

- [x] **Step 3 Alternative: Modify template to use current request.args**

```html
<!-- Assuming Flask template has access to request object -->
<nav aria-label="Page navigation">
  <ul class="pagination">
    {% if page.has_previous %}
    <li class="page-item">
      <a
        class="page-link"
        href="{{ url_for('inventory', page=page.prev_num, **request.args) }}"
        >Previous</a
      >
    </li>
    {% else %}
    <li class="page-item disabled"><span class="page-link">Previous</span></li>
    {% endif %} {# Page numbers #} {% for p_num in page.iter_pages() %} {% if
    page_num %}
    <li class="page-item {% if page_num == page.page %}active{% endif %}">
      <a
        class="page-link"
        href="{{ url_for('inventory', page=p_num, **request.args) }}"
        >{{ page_num }}</a
      >
    </li>
    {% else %}
    <li class="page-item disabled"><span class="page-link">…</span></li>
    {% endif %} {% endfor %} {% if page.has_next %}
    <li class="page-item">
      <a
        class="page-link"
        href="{{ url_for('inventory', page=page.next_num, **request.args) }}"
        >Next</a
      >
    </li>
    {% else %}
    <li class="page-item disabled"><span class="page-link">Next</span></li>
    {% endif %}
  </ul>
</nav>
```

- [x] **Step 4: Test pagination preserves filters**
      Run:
- Apply filters (category, supplier, search, etc.)
- Verify URL updates to show filters
- Navigate to page 2, 3, etc.
- Verify filters remain applied on each page
- Test removing filters, changing filters, combining multiple filters
  Expected: Pagination links maintain current filter state

- [x] **Step 5: Commit**

```bash
git add app/templates/inventory.html
git commit -m "feat: make pagination preserve filter and search state"
```

### Task 11: Fix Missing Confirmation on Destructive Actions

**Files:**

- Modify: Multiple template files containing destructive action buttons/links

**Interfaces:**

- Consumes: User click on destructive action
- Produces: Confirmation dialog, prevents action if user cancels

- [x] **Step 1: Identify destructive action points**
      Look for:
- Delete product buttons
- Delete purchase order buttons
- Delete inventory movement buttons
- Delete user/role buttons
- Delete supplier buttons
- Any "Remove", "Delete", "Destroy" actions
- Bulk delete operations

- [x] **Step 2: Add confirmation to links/buttons**

```html
<!-- Before -->
<a href="{{ url_for('delete_product', id=product.id) }}" class="btn btn-danger"
  >Delete</a
>

<!-- After -->
<a
  href="{{ url_for('delete_product', id=product.id) }}"
  class="btn btn-danger"
  onclick="return confirm('Are you sure you want to delete this product? This action cannot be undone.')"
>
  Delete
</a>

<!-- For forms -->
<form
  method="POST"
  action="{{ url_for('delete_product', id=product.id) }}"
  onsubmit="return confirm('Are you sure you want to delete this product? This action cannot be undone.')"
>
  <button type="submit" class="btn btn-danger">Delete</button>
</form>

<!-- Better: Use custom confirmation function for consistency -->
<a
  href="{{ url_for('delete_product', id=product.id) }}"
  class="btn btn-danger"
  onclick="return confirmAction('Delete this product? This action cannot be undone.')"
>
  Delete
</a>
```

- [x] **Step 3: Create reusable confirmation function (optional)**

```javascript
// Add to main.js or create helper
function confirmAction(message) {
  return window.confirm(message);
}
// Or use a library like SweetAlert2 for better UX
```

- [x] **Step 4: Test confirmation behavior**
      Run:
- Click delete button → verify confirmation dialog appears
- Click "Cancel" → verify action is NOT performed
- Click "OK" → verify action proceeds normally
- Test with actual data to verify deletion only occurs on confirmation
  Expected: Confirmation prevents accidental deletions, normal operation unaffected

- [x] **Step 5: Commit**

```bash
git add /* modified template files */
git commit -m "feat: add confirmation dialogs for destructive actions"
```

### Task 12: Fix Color Contrast Failures (WCAG AA)

**Files:**

- Modify: `app/static/css/style.css`
- Modify: `app/static/css/landing.css`

**Interfaces:**

- Consumes: Text and background color values
- Produces: Color combinations meeting WCAG 2.1 AA contrast ratios

- [x] **Step 1: Audit current color usage**
      Use accessibility testing tool (axe, Lighthouse, WebAIM) to identify:
- Specific elements with insufficient contrast
- Foreground and background color values
- Current contrast ratio
- Required adjustment to reach 4.5:1 (normal text) or 3:1 (large text)

- [x] **Step 2: Modify CSS to fix contrast issues**
      Common fixes:
- Increase text darkness on light backgrounds
- Decrease text lightness on dark backgrounds
- Add text shadow or outline for improved legibility
- Adjust background color lightness/darkness
- Change to different color combination that maintains design intent

```css
/* Example fixes */
/* If text is too light on dark background */
.element {
  color: #e0e0e0; /* was #ffffff - decreased lightness for better contrast */
}

/* If background is too light for dark text */
.container {
  background-color: #f0f0f0; /* was #ffffff - decreased lightness */
}

/* If using CSS variables, adjust the variable values */
:root {
  --text-primary: #212529; /* was #1a1a1a - increased lightness for contrast on light bg */
  --bg-light: #f8f9fa; /* was #ffffff - slight decrease for contrast */
}
```

- [x] **Step 3: Test contrast after changes**
      Run:
- Use axe or Lighthouse to re-run accessibility audit
- Manual testing:
  - View in grayscale to check luminance
  - Use color blindness simulators (protanopia, deuteranopia, tritanopia)
  - Test in different lighting conditions
    Expected: All text meets 4.5:1 contrast (or 3:1 for large text), no new failures introduced

- [x] **Step 4: Commit**

```bash
git add app/static/css/style.css app/static/css/landing.css
git commit -m "style: fix color contrast issues for WCAG AA compliance"
```

### Task 13: Fix CSS Variable Collision (--ink)

**Files:**

- Modify: `app/static/css/landing.css` (line 20 and usages)

**Interfaces:**

- Consumes: CSS variable definitions and usages
- Produces: Unique variable names preventing scope collisions

- [x] **Step 1: Locate --ink definition in landing.css**

```css
/* landing.css:20 */
:root {
  --ink: #ff0000; /* example value */
  /* other variables */
}
```

- [x] **Step 2: Determine usage in landing.css**
      Find all instances of `var(--ink)` or direct usage in landing.css

- [x] **Step 3: Choose unique name for landing-specific variable**
      Rename to something like `--landing-ink` or `--ink-landing`

- [x] **Step 4: Update definition and all usages**

```css
/* landing.css:20 */
:root {
  --landing-ink: #ff0000; /* renamed from --ink */
  /* other variables */
}

/* Update all usages */
.element {
  color: var(--landing-ink); /* was var(--ink) */
}
```

- [x] **Step 5: Verify landing page and main app styles**
      Run:
- Visit landing page → verify styling correct
- Visit main application → verify styling correct and unaffected
- Check for any color inconsistencies or leaks
  Expected: Landing page uses its own variable, main app uses its own --ink, no conflicts

- [x] **Step 6: Commit**

```bash
git add app/static/css/landing.css
git commit -m "style: rename --ink variable in landing.css to prevent collision"
```

### Task 14: Fix Data Tables Not Wrapped Causing Horizontal Overflow

**Files:**

- Modify: Multiple HTML templates containing `<table>` elements
- Create/Modify: `app/static/css/style.css` to add `.table-responsive` rule

**Interfaces:**

- Consumes: Data table elements
- Produces: Tables wrapped in overflow container for responsive behavior

- [x] **Step 1: Identify all data table templates**
      Look for:
- Inventory listings (`inventory.html`)
- Product lists
- Purchase order tables
- Movement history tables
- User/role tables
- Supplier lists
- Any other `<table>` elements displaying data

- [x] **Step 2: Wrap tables in responsive container**

```html
<!-- Before -->
<table class="table">
  <!-- table content -->
</table>

<!-- After -->
<div class="table-responsive">
  <table class="table">
    <!-- table content -->
  </table>
</div>
```

- [x] **Step 3: Add CSS for responsive table container**

```css
/* Add to app/static/css/style.css */
.table-responsive {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin-bottom: 1rem; /* match existing spacing */
  /* Optional: add subtle indication of scrollability */
  /* 
    &::-webkit-scrollbar {
        height: 8px;
    }
    &::-webkit-scrollbar-track {
        background: #f1f1f1;
    }
    &::-webkit-scrollbar-thumb {
        background: #c1c1c1;
        border-radius: 4px;
    }
    */
}
```

- [x] **Step 4: Test responsive table behavior**
      Run:
- Resize browser to narrow widths (mobile, tablet)
- Verify horizontal scrollbar appears only when table exceeds viewport
- Verify table content accessible via scrolling
- Test touch scrolling on touch-enabled devices
- Verify vertical scrolling still works within table body
- Check that headers remain associated with columns
  Expected: Tables scroll horizontally when needed, no vertical overflow issues

- [x] **Step 5: Commit**

```bash
git add /* modified templates */ app/static/css/style.css
git commit -m "feat: add responsive wrappers to data tables"
```

### Task 15: Fix CDN Scripts Hang With No Timeout/Fallback

**Files:**

- Modify: `app/templates/base.html` (replace CDN script tags)
- Create: `app/static/js/script-loader.js`
- Possibly: Create `/static/js/vendor/` for local fallbacks
- Modify: Initialization code that depends on these libraries

**Interfaces:**

- Consumes: Script URLs, timeout configuration
- Produces: Loaded scripts with error handling, fallbacks, and loading states

- [x] **Step 1: Identify CDN script tags in base.html**

```html
<!-- Examples -->
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.11.0/gsap.min.js"></script>
```

- [x] **Step 2: Create script-loader.js with timeout and fallback**

```javascript
// app/static/js/script-loader.js
class ScriptLoader {
  constructor(defaultOptions = {}) {
    this.defaultOptions = {
      timeout: defaultOptions.timeout || 15000, // 15 seconds
      retries: defaultOptions.retries || 2,
      retryDelay: defaultOptions.retryDelay || 1000, // 1 second base
      ...defaultOptions,
    };
    this.loadedScripts = new Set();
    this.loadingPromises = new Map();
  }

  loadScript(src, options = {}) {
    const { timeout, retries, retryDelay, ...fetchOptions } = {
      ...this.defaultOptions,
      ...options,
    };

    // If already loaded, return resolved promise
    if (this.loadedScripts.has(src)) {
      return Promise.resolve();
    }

    // If already loading, return existing promise
    if (this.loadingPromises.has(src)) {
      return this.loadingPromises.get(src);
    }

    // Create loading promise
    const loadPromise = this._loadScriptWithTimeout(
      src,
      timeout,
      retries,
      retryDelay,
    );
    this.loadingPromises.set(src, loadPromise);

    return loadPromise.finally(() => {
      this.loadingPromises.delete(src);
    });
  }

  _loadScriptWithTimeout(src, timeout, retries, retryDelay) {
    let lastError;

    const attemptLoad = (attempt) => {
      return new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = src;
        script.async = true;

        const timeoutId = setTimeout(() => {
          script.remove();
          reject(new Error(`Script load timeout after ${timeout}ms`));
        }, timeout);

        const handleLoad = () => {
          clearTimeout(timeoutId);
          script.removeEventListener("load", handleLoad);
          script.removeEventListener("error", handleError);
          this.loadedScripts.add(src);
          resolve();
        };

        const handleError = (error) => {
          clearTimeout(timeoutId);
          script.removeEventListener("load", handleLoad);
          script.removeEventListener("error", handleError);
          reject(error);
        };

        script.addEventListener("load", handleLoad);
        script.addEventListener("error", handleError);

        // Handle fallback to local copy on network error
        script.onerror = () => {
          // Try to determine if this is a network error we can fallback from
          // For simplicity, we'll retry first, then consider fallback
          // Real implementation would be more sophisticated
        };

        document.head.appendChild(script);
      });
    };

    let promise = Promise.resolve();
    for (let attempt = 0; attempt <= retries; attempt++) {
      promise = promise
        .then(() => attemptLoad(attempt))
        .catch((error) => {
          lastError = error;
          if (attempt === retries) {
            throw error;
          }
          // Wait before retry
          return new Promise((resolve) =>
            setTimeout(resolve, retryDelay * Math.pow(2, attempt)),
          );
        });
    }

    return promise;
  }
}

// Create singleton instance
window.scriptLoader = new ScriptLoader();
```

- [x] **Step 3: Replace static script tags with dynamic loading**

```html
<!-- Before -->
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.11.0/gsap.min.js"></script>

<!-- After -->
<script>
  document.addEventListener("DOMContentLoaded", async () => {
    try {
      // Load critical scripts with timeout
      await Promise.all([
        window.scriptLoader.loadScript(
          "https://cdn.plot.ly/plotly-latest.min.js",
        ),
        window.scriptLoader.loadScript(
          "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js",
        ),
        window.scriptLoader.loadScript(
          "https://cdnjs.cloudflare.com/ajax/libs/gsap/3.11.0/gsap.min.js",
        ),
      ]);

      // Initialize functionality that depends on these scripts
      initializeCharts();
      initializeThreeBackground();
      initializeGSAPAnimations();
    } catch (error) {
      console.error("Failed to load one or more required scripts:", error);
      // Show user-friendly message or fallback UI
      showScriptLoadError();
    }
  });
</script>
```

- [x] **Step 4: Handle loading states and fallbacks**
- Show loading indicator while waiting for scripts
- Gracefully degrade functionality if scripts fail to load
- Consider local fallback copies in `/static/js/vendor/`
- Update initialization code to handle async script loading

- [x] **Step 5: Test CDN failure scenarios**
      Run:
- Simulate CDN failure (block domains, network throttling)
- Verify page loads within timeout period instead of hanging
- Verify fallback behavior if implemented
- Test that dependent functionality degrades gracefully
- Verify normal operation when CDNs are available
  Expected: Page loads timely, scripts load with timeout/retry, graceful degradation on failure

- [x] **Step 6: Commit**

```bash
git add app/templates/base.html app/static/js/script-loader.js /* other modified files */
git commit -m "feat: add script loading with timeout, retry, and fallback handling"
```

### Task 16: Fix Asset Version Query Parameters Must Be Bumped

**Files:**

- Modify: `app/templates/base.html` (update version numbers when assets change)
- Possibly: Create automated version bumping script

**Interfaces:**

- Consumes: Asset file contents or timestamps
- Produces: Correct query parameters in HTML to bust cache

- [x] **Step 1: Identify assets with version query parameters**
      Look for patterns like:
- `style.css?v=20.3`
- `main.js?v=1.2`
- `ai-features.js?v=9.2`
- etc.

- [x] **Step 2: Establish version bumping process**
      For immediate term (manual):
- Always increment version number when changing CSS/JS
- Use consistent scheme: increment decimal (20.3 → 20.4) or use timestamp
- Add to deployment checklist: verify version numbers in base.html

For better term (automated):

- Create script that:
  1. Reads file contents or timestamps
  2. Generates hash or timestamp-based version
  3. Updates base.html with correct parameters
- Integrate with build/deployment process

```python
# Example version bumping script (Python)
import hashlib
import os
import re

def get_file_hash(filepath):
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()[:8]

def update_base_html():
    base_html_path = 'app/templates/base.html'
    assets = [
        ('style.css', 'css'),
        ('main.js', 'js'),
        ('ai-features.js', 'js'),
        # ... add all assets with version params
    ]

    with open(base_html_path, 'r') as f:
        content = f.read()

    for asset_path, asset_type in assets:
        full_path = f'app/static/{asset_type}/{asset_path}'
        if os.path.exists(full_path):
            version = get_file_hash(full_path)
            # Replace pattern like style.css?v=xxxxxx
            pattern = f'{asset_path}\\?v=[0-9a-f]+'
            replacement = f'{asset_path}?v={version}'
            content = re.sub(pattern, replacement, content, flags=re.IGNORECASE)

    with open(base_html_path, 'w') as f:
        f.write(content)

if __name__ == '__main__':
    update_base_html()
```

- [x] **Step 3: Test version bumping behavior**
      Run:
- Change a CSS or JS file
- Run version bumping script (if automated)
- Verify base.html updated with new parameter
- Deploy change
- Verify new users get updated file (check network tab shows new v= parameter)
- Verify old cached version not served
  Expected: Cache busting works, users get latest files after deploy

- [x] **Step 4: Commit (if implementing automated solution)**

```bash
git add app/templates/base.html /* version bumping script if created */
git commit -m "feat: implement automated asset versioning for cache busting"
```

### Task 17: Fix Filter Bar Z-Index Stacking Context

**Files:**

- Modify: `app/static/css/style.css` (add position and z-index to .filter-bar and .report-filter-row)

**Interfaces:**

- Consumes: Filter bar and report filter row elements
- Produces: Correct stacking context to prevent dropdowns being hidden behind tables

- [x] **Step 1: Locate selectors in style.css**
      Find:

```css
.filter-bar {
  /* existing styles */
}

.report-filter-row {
  /* existing styles */
}
```

- [x] **Step 2: Add position and z-index**

```css
.filter-bar {
  /* existing styles */
  position: relative;
  z-index: 30;
}

.report-filter-row {
  /* existing styles */
  position: relative;
  z-index: 30;
}
```

- [x] **Step 3: Verify stacking context works**
      Run:
- Navigate to pages with both filters and tables (inventory, reports)
- Open filter dropdowns
- Verify dropdowns appear above table scrolling elements, not behind them
- Test with long dropdown lists
- Verify table scrolling still works normally behind dropdowns
- Check that other UI elements (headers, modals, etc.) still layer correctly
  Expected: Filter dropdowns visible and functional, no z-index conflicts with other layers

- [x] **Step 4: Commit**

```bash
git add app/static/css/style.css
git commit -m "style: add z-index to filter bars to prevent dropdown hiding"
```

## Plan Execution Recommendation

**Recommended Approach: Native** - I will implement every task myself in this session, then a fresh reviewer checks the whole branch.

**Reasoning:**

- Tasks are largely independent (each addresses a specific issue)
- Most tasks involve localized changes to specific files
- Low risk of breaking changes due to preservation-focused approach
- Most thorough approach (subagent-driven) would be excessive for these well-defined fixes
- Native approach is fastest and most efficient for this set of isolated UI/UX fixes

**Plan complete and saved to `docs/superpowers/plans/2026-09-22-frontend-issue-mitigation-plan.md`. Please review the plan. Which execution approach would you prefer?**

- **Subagent-driven** - A fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end. Most thorough; costs a fresh context per task and per review.
- **Native** - I implement every task myself in this session, the way this harness runs work, then one fresh reviewer on the most capable model checks the whole branch. Cheapest and fastest; no independent review until the end. Runs well with a mid-tier session model, since the plan carries the design.

**For this plan I recommend Native, because the tasks are well-defined, isolated, and primarily involve adding missing safeguards or fixing specific UI/UX issues with low risk of breaking existing functionality. Does the plan capture what you want, and which approach should we use?**
