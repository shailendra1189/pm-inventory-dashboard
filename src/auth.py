"""Shared authentication helper for all pages."""
import os
import re
import yaml
import bcrypt
from yaml.loader import SafeLoader
import streamlit as st
import streamlit_authenticator as stauth
from src.config import BASE_DIR


def _load_config():
    config_path = os.path.join(BASE_DIR, "config.yaml")
    with open(config_path, encoding="utf-8") as f:
        return yaml.load(f, Loader=SafeLoader)


def _save_config(config):
    """Write the config dict back to config.yaml."""
    config_path = os.path.join(BASE_DIR, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


# ─── User Management helpers ──────────────────────────────────────────────────

ROLES = ("admin", "manager", "viewer")


def get_all_users():
    """Return list of user dicts (passwords excluded), sorted by username."""
    config = _load_config()
    users = []
    for username, data in config["credentials"]["usernames"].items():
        users.append({
            "username": username,
            "name":     data.get("name",  ""),
            "email":    data.get("email", ""),
            "role":     data.get("role",  "viewer"),
        })
    return sorted(users, key=lambda x: x["username"])


def add_user(username, name, email, password_plain, role="viewer"):
    """Add a new user.  Returns (True, '') or (False, error_msg)."""
    username = username.strip().lower()

    if not re.match(r"^[a-z0-9_]{3,32}$", username):
        return False, ("Username must be 3–32 characters containing only "
                       "lowercase letters, numbers, or underscores (no spaces).")
    if len(password_plain) < 6:
        return False, "Password must be at least 6 characters."
    if role not in ROLES:
        return False, f"Role must be one of: {', '.join(ROLES)}."

    config = _load_config()
    if username in config["credentials"]["usernames"]:
        return False, f"Username '{username}' is already taken — choose a different one."

    hashed_pw = bcrypt.hashpw(password_plain.encode(), bcrypt.gensalt()).decode()
    config["credentials"]["usernames"][username] = {
        "name":     name.strip(),
        "email":    email.strip().lower(),
        "password": hashed_pw,
        "role":     role,
    }
    _save_config(config)
    return True, ""


def update_user(username, name=None, email=None, role=None, password_plain=None):
    """Update an existing user's details.  Returns (True, '') or (False, error_msg)."""
    config = _load_config()
    if username not in config["credentials"]["usernames"]:
        return False, f"User '{username}' not found."

    user = config["credentials"]["usernames"][username]

    if name is not None:
        user["name"] = name.strip()
    if email is not None:
        user["email"] = email.strip().lower()
    if role is not None:
        if role not in ROLES:
            return False, f"Role must be one of: {', '.join(ROLES)}."
        # Prevent demoting the last admin
        if user.get("role") == "admin" and role != "admin":
            remaining = [
                u for u, d in config["credentials"]["usernames"].items()
                if d.get("role") == "admin" and u != username
            ]
            if not remaining:
                return False, "Cannot change role — this is the last admin account."
        user["role"] = role
    if password_plain is not None:
        if len(password_plain) < 6:
            return False, "Password must be at least 6 characters."
        user["password"] = bcrypt.hashpw(password_plain.encode(), bcrypt.gensalt()).decode()

    _save_config(config)
    return True, ""


def delete_user(username, current_username):
    """Delete a user.  Returns (True, '') or (False, error_msg).

    Safeguards:
    - Cannot delete yourself.
    - Cannot delete the last admin account.
    """
    if username == current_username:
        return False, "You cannot delete your own account."

    config = _load_config()
    if username not in config["credentials"]["usernames"]:
        return False, f"User '{username}' not found."

    target_role = config["credentials"]["usernames"][username].get("role")
    if target_role == "admin":
        remaining = [
            u for u, d in config["credentials"]["usernames"].items()
            if d.get("role") == "admin" and u != username
        ]
        if not remaining:
            return False, "Cannot delete the last admin account."

    del config["credentials"]["usernames"][username]
    _save_config(config)
    return True, ""


def get_authenticator():
    """Create a fresh Authenticate instance per page load. Never cache this object."""
    config = _load_config()
    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
        auto_hash=False,
    )
    return authenticator, config


def require_auth():
    """
    Call at the top of every sub-page.
    - Silently checks the auth cookie (no login form rendered).
    - Returns (authenticator, config) when the user is authenticated.
    - Shows a redirect message and stops execution if not authenticated.
    """
    authenticator, config = get_authenticator()

    # Check session_state first (fastest path — already authenticated this session)
    if st.session_state.get("authentication_status"):
        return authenticator, config

    # Try to restore from cookie without rendering any UI
    try:
        authenticator.login(location="unrendered")
    except Exception:
        pass  # Cookie absent or malformed — treat as not authenticated

    if st.session_state.get("authentication_status"):
        return authenticator, config

    # Not authenticated — send user to home page
    st.warning("🔒 You need to log in first.")
    st.page_link("streamlit_app.py", label="Go to Home / Login →", icon="🏠")
    st.stop()


def sidebar_nav(authenticator):
    with st.sidebar:
        st.markdown(f"**👤 {st.session_state.get('name', 'User')}**")
        try:
            authenticator.logout("Logout", location="sidebar")
        except Exception:
            if st.button("Logout"):
                for key in ["authentication_status", "name", "username"]:
                    st.session_state.pop(key, None)
                st.rerun()
        st.divider()
        st.page_link("streamlit_app.py",                 label="Overview",             icon="🏠")
        st.page_link("pages/1_Mother_Hub.py",           label="Mother Hub",           icon="🏭")
        st.page_link("pages/2_City_Dashboard.py",       label="City Dashboard",       icon="🏙️")
        st.page_link("pages/3_In_Transit.py",           label="In Transit",           icon="🚛")
        st.page_link("pages/5_Demand_Planning.py",       label="Demand Planning",      icon="📊")
        st.page_link("pages/6_SOP_Compliance.py",       label="SOP Compliance",       icon="⚠️")
        st.page_link("pages/4_Admin.py",                label="Admin & Settings",     icon="⚙️")
