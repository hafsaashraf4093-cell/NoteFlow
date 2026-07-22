// Dark mode toggle
function toggleDarkMode() {
    document.body.classList.toggle("dark");
    showToast("Theme switched!");
}

// Toast notifications
function showToast(message) {
    let toast = document.createElement("div");
    toast.className = "toast";
    toast.innerText = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.remove();
    }, 3000);
}

// Character counter
function updateCounter(textarea, counterId) {
    let counter = document.getElementById(counterId);
    counter.innerText = `${textarea.value.length} characters`;
}

// Auto-save draft
function autoSaveDraft(id) {
    let textarea = document.getElementById(id);
    if (!textarea) return;
    textarea.value = localStorage.getItem(id) || "";
    textarea.addEventListener("input", () => {
        localStorage.setItem(id, textarea.value);
    });
}

// Toast CSS injection
const style = document.createElement('style');
style.innerHTML = `
.toast {
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: linear-gradient(135deg, #667eea, #764ba2);
    color: white;
    padding: 12px 20px;
    border-radius: 8px;
    box-shadow: 0 5px 15px rgba(0,0,0,0.3);
    animation: fadeIn 0.5s ease-in-out;
}
`;
document.head.appendChild(style);
