
// ---------------- Password show/hide ----------------
document.querySelectorAll(".toggle-password").forEach((btn) => {
    btn.addEventListener("click", () => {
        const input = document.getElementById(btn.dataset.target);
        if (input.type === "password") {
            input.type = "text";
            btn.textContent = "🙈";
        } else {
            input.type = "password";
            btn.textContent = "👁️";
        }
    });
});

// ---------------- Mobile number: digits only, max 10 ----------------
const mobileInput = document.getElementById("mobile");
if (mobileInput) {
    mobileInput.addEventListener("input", () => {
        mobileInput.value = mobileInput.value.replace(/\D/g, "").slice(0, 10);
    });
}

// ---------------- Submit-time validation with popups ----------------
const signupForm = document.getElementById("signup-form");
if (signupForm) {
    signupForm.addEventListener("submit", (e) => {
        const mobile = mobileInput.value.trim();
        const email = document.getElementById("gmail").value.trim();
        const emailPattern = /^[\w.+-]+@([\w-]+\.)+[a-zA-Z]{2,}$/;

        if (!/^[0-9]{10}$/.test(mobile)) {
            e.preventDefault();
            alert("Please enter a valid 10-digit mobile number (numbers only).");
            mobileInput.focus();
            return;
        }

        if (!emailPattern.test(email)) {
            e.preventDefault();
            alert("Please enter a valid email address with a proper extension (e.g. name@example.com).");
            document.getElementById("gmail").focus();
            return;
        }
    });
}