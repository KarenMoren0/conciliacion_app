document.addEventListener("DOMContentLoaded", function () {

    const toast = document.getElementById("toast");

    if (toast) {
        toast.classList.add("show");

        setTimeout(() => {
            toast.classList.remove("show");
        }, 3000);
    }
    const passwordInput = document.getElementById("password");
    const togglePassword = document.querySelector(".toggle-password");

    togglePassword.style.display = "none";

    passwordInput.addEventListener("input", function () {

        if (passwordInput.value.length > 0) {
            togglePassword.style.display = "block";
        } else {
            togglePassword.style.display = "none";
        }
    });
});

function mostrarPassword() {

    const password = document.getElementById("password");
    const icon = document.querySelector(".toggle-password i");

    if (password.type === "password") {

        password.type = "text";

        icon.classList.remove("fa-eye-slash");
        icon.classList.add("fa-eye");

    } else {

        password.type = "password";

        icon.classList.remove("fa-eye");
        icon.classList.add("fa-eye-slash");
    }
}