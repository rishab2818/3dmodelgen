//! Tauri shell for 3dmodel_gen.
//!
//! The Rust side is intentionally thin (per app/CLAUDE.md):
//!   - register native plugins (dialog, shell)
//!   - declare the main window via tauri.conf.json
//!   - expose tiny commands that the OS owns
//!
//! All business logic lives in the Python backend (which we expect to be running on
//! localhost:7878). M1 does NOT spawn the backend from here; the dev workflow runs the
//! backend in a separate terminal. Spawn-and-supervise is wired up in M2 alongside the
//! resumability test suite.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|_app| Ok(()))
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
