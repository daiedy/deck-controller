# Code Review: 2026-05-07

## Issues

### 1. [High] Unhandled Exception in `src/controllers/userController.js` (lines 45-52)
**Description:**
The `getUserProfile` function does not handle the case where the user is not found, which may result in an unhandled exception.

**File:** `src/controllers/userController.js`
**Lines:** 45-52
**Severity:** High
**Recommended Fix:**
Add a check for a missing user and return a 404 response if not found.

**Snippet:**
```js
// src/controllers/userController.js (lines 45-52)
const user = await User.findById(req.params.id);
if (!user) {
  return res.status(404).json({ error: 'User not found' });
}
res.json(user);
```

---

### 2. [Medium] Hardcoded Secret in `src/config.js` (lines 10-10)
**Description:**
A JWT secret is hardcoded in the configuration file, which is a security risk.

**File:** `src/config.js`
**Lines:** 10-10
**Severity:** Medium
**Recommended Fix:**
Load secrets from environment variables instead of hardcoding them.

**Snippet:**
```js
// src/config.js (line 10)
const JWT_SECRET = 'mySuperSecretKey';
```

---

### 3. [Low] Deprecated API Usage in `src/services/paymentService.js` (lines 88-90)
**Description:**
The code uses a deprecated method `payment.process()`, which may be removed in future versions.

**File:** `src/services/paymentService.js`
**Lines:** 88-90
**Severity:** Low
**Recommended Fix:**
Update to use the recommended `payment.execute()` method.

**Snippet:**
```js
// src/services/paymentService.js (lines 88-90)
payment.process(amount, currency);
```

---

## Summary
- 3 issues found
- 1 high, 1 medium, 1 low severity
- See above for file paths, line ranges, and recommended fixes
