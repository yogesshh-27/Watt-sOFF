/**
 * firebase-auth.js — Genuine Firebase Google Authentication for Watt's Off Citizen Portal
 *
 * Uses Firebase Auth with GoogleAuthProvider for real Google OAuth login.
 * No mock fallbacks — this is the real thing.
 *
 * Prerequisites (do once in Firebase Console):
 *   1. Build → Authentication → Get started → Enable "Google" provider
 *   2. Authentication → Settings → Authorized domains → add "localhost"
 *   3. Paste your firebaseConfig into static/firebase-config.js
 */

// ─── Initialize Firebase ────────────────────────────────────────────────────

if (!window.FIREBASE_CONFIG || window.FIREBASE_CONFIG.apiKey === "YOUR_FIREBASE_API_KEY") {
    console.error("[Firebase] firebase-config.js is not configured. Please paste your Firebase project keys.");
}

let firebaseApp    = null;
let firebaseAuth   = null;
let googleProvider = null;

try {
    if (typeof firebase === 'undefined') {
        throw new Error("Firebase SDK not loaded. Check that firebase-app-compat.js and firebase-auth-compat.js scripts are in the page.");
    }

    firebaseApp = firebase.apps.length
        ? firebase.app()
        : firebase.initializeApp(window.FIREBASE_CONFIG);

    firebaseAuth = firebase.auth();

    googleProvider = new firebase.auth.GoogleAuthProvider();
    googleProvider.addScope('profile');
    googleProvider.addScope('email');
    // Force account chooser every time so user can pick their Google account
    googleProvider.setCustomParameters({ prompt: 'select_account' });

    console.log("[Firebase] Initialized project:", window.FIREBASE_CONFIG.projectId);
} catch (initErr) {
    console.error("[Firebase] Initialization failed:", initErr);
}

// ─── Sign In ────────────────────────────────────────────────────────────────

/**
 * Launch the real Google Sign-In popup via Firebase.
 * Returns { success: true, user } on success.
 * Returns { success: false, cancelled: true } if user closed the popup.
 * Throws a descriptive Error on Firebase config/setup problems.
 */
async function signInWithGoogleFirebase() {
    if (!firebaseAuth || !googleProvider) {
        throw new Error("Firebase is not initialized. Check your firebase-config.js and SDK script tags.");
    }

    try {
        console.log("[Firebase] Opening Google Sign-In popup...");
        const result = await firebaseAuth.signInWithPopup(googleProvider);
        const user   = result.user;

        // Persist session for page navigation
        sessionStorage.setItem('wattsoff_google_auth',   'true');
        sessionStorage.setItem('wattsoff_citizen_name',  user.displayName || 'Google User');
        sessionStorage.setItem('wattsoff_citizen_email', user.email       || '');
        sessionStorage.setItem('wattsoff_citizen_uid',   user.uid);
        sessionStorage.setItem('wattsoff_citizen_photo', user.photoURL    || '');
        sessionStorage.setItem('wattsoff_auth_provider', 'firebase_google');

        console.log("[Firebase] Signed in as:", user.email);
        return { success: true, user };

    } catch (error) {
        console.error("[Firebase] Sign-in error:", error.code, error.message);

        // User simply closed the popup — not an error
        if (error.code === 'auth/popup-closed-by-user' ||
            error.code === 'auth/cancelled-popup-request') {
            return { success: false, cancelled: true };
        }

        // Actionable guidance for common setup errors
        if (error.code === 'auth/api-key-not-valid' ||
            error.code === 'auth/invalid-api-key') {
            throw new Error(
                "Firebase API Key is not valid or not yet activated.\n\n" +
                "ACTION REQUIRED:\n" +
                "1. Go to console.firebase.google.com\n" +
                "2. Select your project (cobuild-e996a)\n" +
                "3. Build → Authentication → Get started\n" +
                "4. Sign-in method → Enable 'Google'\n" +
                "5. Reload this page."
            );
        }

        if (error.code === 'auth/operation-not-allowed') {
            throw new Error(
                "Google Sign-In is not enabled in your Firebase project.\n\n" +
                "ACTION REQUIRED:\n" +
                "1. Firebase Console → Build → Authentication\n" +
                "2. Sign-in method tab → Click 'Google'\n" +
                "3. Toggle Enable → Save\n" +
                "4. Reload this page."
            );
        }

        if (error.code === 'auth/unauthorized-domain') {
            throw new Error(
                "localhost is not in your Firebase authorized domains list.\n\n" +
                "ACTION REQUIRED:\n" +
                "1. Firebase Console → Build → Authentication\n" +
                "2. Settings tab → Authorized domains\n" +
                "3. Add 'localhost' and '127.0.0.1'\n" +
                "4. Reload this page."
            );
        }

        if (error.code === 'auth/configuration-not-found') {
            throw new Error(
                "Firebase Authentication is not set up for this project.\n\n" +
                "ACTION REQUIRED:\n" +
                "1. Firebase Console → Build → Authentication → Get started\n" +
                "2. Enable 'Google' in Sign-in method\n" +
                "3. Reload this page."
            );
        }

        // Re-throw any other unexpected error with original message
        throw error;
    }
}

// ─── Sign Out ───────────────────────────────────────────────────────────────

/**
 * Sign the current user out of Firebase and clear session data.
 */
async function signOutFirebase() {
    try {
        if (firebaseAuth) {
            await firebaseAuth.signOut();
            console.log("[Firebase] Signed out.");
        }
    } catch (err) {
        console.warn("[Firebase] Sign-out error:", err);
    } finally {
        sessionStorage.removeItem('wattsoff_google_auth');
        sessionStorage.removeItem('wattsoff_citizen_name');
        sessionStorage.removeItem('wattsoff_citizen_email');
        sessionStorage.removeItem('wattsoff_citizen_uid');
        sessionStorage.removeItem('wattsoff_citizen_photo');
        sessionStorage.removeItem('wattsoff_auth_provider');
    }
}

// ─── Auth State Listener ────────────────────────────────────────────────────

/**
 * Subscribe to Firebase auth state changes.
 * Keeps sessionStorage in sync when the user's auth state changes
 * (e.g. token refresh, sign-out from another tab).
 *
 * @param {function} onUserChanged  Called with (user | null) on every change.
 */
function listenToFirebaseAuth(onUserChanged) {
    if (!firebaseAuth) return;

    firebaseAuth.onAuthStateChanged((user) => {
        if (user) {
            sessionStorage.setItem('wattsoff_google_auth',   'true');
            sessionStorage.setItem('wattsoff_citizen_name',  user.displayName || 'Google User');
            sessionStorage.setItem('wattsoff_citizen_email', user.email       || '');
            sessionStorage.setItem('wattsoff_citizen_uid',   user.uid);
            sessionStorage.setItem('wattsoff_citizen_photo', user.photoURL    || '');
        } else {
            // Signed out externally — clear stale session
            sessionStorage.removeItem('wattsoff_google_auth');
            sessionStorage.removeItem('wattsoff_citizen_name');
            sessionStorage.removeItem('wattsoff_citizen_email');
            sessionStorage.removeItem('wattsoff_citizen_uid');
            sessionStorage.removeItem('wattsoff_citizen_photo');
        }

        if (typeof onUserChanged === 'function') {
            onUserChanged(user);
        }
    });
}

